import pytest

from tradingagents.llm_clients.base_client import (
    invoke_with_transient_retries,
    is_transient_llm_error,
)


class ProviderError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.unit
def test_capacity_error_is_transient():
    exc = ProviderError(
        "InternalServerError: Error code: 503 - "
        "{'error': {'metadata': {'raw': '{\"error\":{\"message\":\"No backends available\","
        "\"type\":\"capacity_error\"}}'}}}",
        status_code=503,
    )

    assert is_transient_llm_error(exc)


@pytest.mark.unit
def test_a_real_dropped_connection_is_transient():
    """openai.APIConnectionError and anthropic.APIConnectionError -- what
    every provider client in this codebase actually raises when the local
    network genuinely drops mid-call -- carry no status_code at all and say
    only "Connection error." (verified live against both SDKs). Neither the
    status-code check nor the original marker list could see these, so a
    Wi-Fi blip during an LLM call used to fail the whole run outright
    instead of retrying like every other transient failure does."""
    exc = ProviderError("Connection error.")  # status_code=None, the real shape

    assert is_transient_llm_error(exc)


@pytest.mark.unit
def test_dns_failure_is_transient():
    exc = ProviderError("[Errno 11001] getaddrinfo failed")  # Windows DNS failure

    assert is_transient_llm_error(exc)


@pytest.mark.unit
def test_connection_refused_is_transient():
    exc = ProviderError("Connection refused")

    assert is_transient_llm_error(exc)


@pytest.mark.unit
def test_a_genuinely_unrelated_error_is_still_not_transient():
    """The widened marker list must not swallow real bugs -- a KeyError from
    a malformed response body has nothing to do with connectivity."""
    exc = ProviderError("KeyError: 'choices'")

    assert not is_transient_llm_error(exc)


@pytest.mark.unit
def test_invoke_with_transient_retries_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("tradingagents.llm_clients.base_client.time.sleep", lambda _: None)
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ProviderError("No backends available", status_code=503)
        return "ok"

    assert invoke_with_transient_retries(operation, max_attempts=4) == "ok"
    assert attempts["count"] == 3


@pytest.mark.unit
def test_invoke_with_transient_retries_does_not_retry_non_transient():
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        raise ProviderError("invalid request", status_code=400)

    with pytest.raises(ProviderError):
        invoke_with_transient_retries(operation, max_attempts=4)

    assert attempts["count"] == 1
