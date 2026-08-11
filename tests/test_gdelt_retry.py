"""GDELT rate-limit retry tests.

GDELT throttles aggressively (HTTP 429 after only a few requests) and is
*first* in the news vendor chain. Without retry, a throttled call raised
straight through to route_to_vendor, which swallowed it into a silent
fallback — so the highest-reach news source was skipped with nothing in the
report to say so, leaving the run on yfinance's ~12-article cap.
"""

import time
from unittest.mock import patch

import pytest
import requests

from tradingagents.dataflows.gdelt_news import _retry_delay, _search_articles


THROTTLE_TEXT = (
    "Please limit requests to one every 5 seconds or contact "
    "kalev.leetaru5@gmail.com for larger queries."
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"articles": []}
        self.headers = headers or {}
        # `text` matters: GDELT's second throttle form is HTTP 200 with a
        # plain-text body, so throttle detection reads the body, not just the
        # status code. Default to a JSON-looking body for success responses.
        self.text = text if text is not None else '{"articles": []}'

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._payload


def _config(**overrides):
    cfg = {
        "gdelt_max_retries": 2,
        "gdelt_retry_base_delay": 2.0,
        "gdelt_timeout_seconds": 15,
        # Disabled so these tests measure retry backoff only; the process-wide
        # spacer has its own tests below.
        "gdelt_min_request_interval": 0,
    }
    cfg.update(overrides)
    return cfg


def _run(responses, config=None, sleeps=None):
    """Drive _search_articles against a scripted sequence of responses."""
    it = iter(responses)
    recorded = sleeps if sleeps is not None else []

    with patch("tradingagents.dataflows.gdelt_news.requests.get", side_effect=lambda *a, **k: next(it)):
        with patch("tradingagents.dataflows.gdelt_news.get_config", return_value=config or _config()):
            with patch("tradingagents.dataflows.gdelt_news.time.sleep", side_effect=recorded.append):
                return _search_articles("(\"X\")", "2026-07-11", "2026-08-10", 30)


@pytest.mark.unit
def test_retries_then_succeeds_on_429():
    articles = _run([
        FakeResponse(429),
        FakeResponse(429),
        FakeResponse(200, {"articles": [{"title": "recovered"}]}),
    ])

    assert articles == [{"title": "recovered"}]


@pytest.mark.unit
def test_retry_uses_exponential_backoff():
    sleeps = []
    _run(
        [FakeResponse(429), FakeResponse(429), FakeResponse(200)],
        sleeps=sleeps,
    )

    assert sleeps == [2.0, 4.0]


@pytest.mark.unit
def test_503_is_also_retried():
    articles = _run([
        FakeResponse(503),
        FakeResponse(200, {"articles": [{"title": "ok"}]}),
    ])

    assert articles == [{"title": "ok"}]


@pytest.mark.unit
def test_gives_up_after_max_retries_and_raises():
    # Exhausted retries must still raise so route_to_vendor falls back to the
    # next vendor rather than returning an empty result as if it were real.
    with pytest.raises(requests.exceptions.HTTPError):
        _run([FakeResponse(429), FakeResponse(429), FakeResponse(429)])


@pytest.mark.unit
def test_non_retryable_error_is_not_retried():
    sleeps = []
    with pytest.raises(requests.exceptions.HTTPError):
        _run([FakeResponse(404)], sleeps=sleeps)

    assert sleeps == []


@pytest.mark.unit
def test_success_makes_no_extra_requests():
    sleeps = []
    articles = _run(
        [FakeResponse(200, {"articles": [{"title": "first try"}]})],
        sleeps=sleeps,
    )

    assert articles == [{"title": "first try"}]
    assert sleeps == []


@pytest.mark.unit
def test_retry_after_header_is_honoured():
    response = FakeResponse(429, headers={"Retry-After": "7"})

    assert _retry_delay(response, base_delay=2.0, attempt=0) == 7.0


@pytest.mark.unit
def test_absurd_retry_after_is_capped():
    # A pathological Retry-After must not stall the whole run.
    response = FakeResponse(429, headers={"Retry-After": "86400"})

    assert _retry_delay(response, base_delay=2.0, attempt=0) == 30.0


@pytest.mark.unit
def test_unparseable_retry_after_falls_back_to_backoff():
    # Retry-After may legally be an HTTP date, which we do not parse.
    response = FakeResponse(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})

    assert _retry_delay(response, base_delay=2.0, attempt=1) == 4.0


@pytest.mark.unit
def test_retries_are_configurable_to_zero():
    sleeps = []
    with pytest.raises(requests.exceptions.HTTPError):
        _run([FakeResponse(429)], config=_config(gdelt_max_retries=0), sleeps=sleeps)

    assert sleeps == []


# --- HTTP 200 plain-text throttle form -------------------------------------
# GDELT does not always use a 429. It also answers with HTTP 200 and a
# plain-text notice, which a status-code-only check treats as success and
# hands to response.json() -> JSONDecodeError, which route_to_vendor swallows
# into a silent fallback. Reproduced live against TMPV.NS on 2026-08-10.


@pytest.mark.unit
def test_plain_text_throttle_body_with_http_200_is_retried():
    articles = _run([
        FakeResponse(200, text=THROTTLE_TEXT),
        FakeResponse(200, {"articles": [{"title": "recovered"}]}),
    ])

    assert articles == [{"title": "recovered"}]


@pytest.mark.unit
def test_plain_text_throttle_raises_http_error_not_json_decode_error():
    # The whole point: fail as a RequestException route_to_vendor understands,
    # not as a JSONDecodeError that looks like a parsing bug.
    with pytest.raises(requests.exceptions.HTTPError):
        _run([FakeResponse(200, text=THROTTLE_TEXT)], config=_config(gdelt_max_retries=0))


@pytest.mark.unit
def test_genuine_json_body_is_not_mistaken_for_a_throttle():
    articles = _run([
        FakeResponse(200, {"articles": [{"title": "real"}]}, text='{"articles":[{"title":"real"}]}')
    ])

    assert articles == [{"title": "real"}]


@pytest.mark.unit
def test_empty_body_is_treated_as_throttle_not_parsed():
    # GDELT sometimes returns an empty 200 body; parsing it raised
    # JSONDecodeError before. It is not JSON, so it must not reach .json().
    with pytest.raises(requests.exceptions.HTTPError):
        _run([FakeResponse(200, text="")], config=_config(gdelt_max_retries=0))


@pytest.mark.unit
def test_backoff_never_dips_below_gdelt_documented_floor():
    # GDELT documents "one request every 5 seconds". The shipped default used
    # to be 2.0, producing 2s/4s waits that were both under GDELT's own floor
    # and therefore guaranteed to be refused again — three failures dressed up
    # as a retry policy.
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["gdelt_retry_base_delay"] >= 5.0


# --- process-wide request spacing -------------------------------------------


@pytest.mark.unit
def test_back_to_back_requests_are_spaced_by_min_interval():
    # A run issues get_news + get_global_news, and merging hits GDELT on every
    # news fetch. Unspaced that is a burst, and bursts earn a sustained block
    # rather than a single retryable 429.
    import tradingagents.dataflows.gdelt_news as gdelt

    gdelt._last_request_at = 0.0
    sleeps = []
    responses = iter([FakeResponse(200, {"articles": []}) for _ in range(2)])
    config = _config(gdelt_min_request_interval=5.0)

    with patch("tradingagents.dataflows.gdelt_news.requests.get", side_effect=lambda *a, **k: next(responses)):
        with patch("tradingagents.dataflows.gdelt_news.get_config", return_value=config):
            with patch("tradingagents.dataflows.gdelt_news.time.sleep", side_effect=sleeps.append):
                _search_articles('("X")', "2026-07-11", "2026-08-10", 30)
                first_call_sleeps = list(sleeps)
                _search_articles('("Y")', "2026-07-11", "2026-08-10", 30)

    # The first call has no recent predecessor and proceeds immediately; the
    # second, issued straight after, must be held back by the interval.
    assert first_call_sleeps == []
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 5.0


@pytest.mark.unit
def test_spacing_disabled_when_interval_is_zero():
    import tradingagents.dataflows.gdelt_news as gdelt

    gdelt._last_request_at = time.monotonic()  # a request "just happened"
    sleeps = []
    _run([FakeResponse(200, {"articles": []})], config=_config(gdelt_min_request_interval=0), sleeps=sleeps)

    assert sleeps == []
