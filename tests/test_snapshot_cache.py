"""Snapshot cache — freezing a run's fetched inputs per (ticker, date).

Price data was already cached to disk; news/social/filings used only
lru_cache, which dies with the process. Measured on SIEMENS.NS 2026-08-12,
two runs 11 minutes apart with the market closed: the market snapshot was
byte-identical while **22 of 63 news headlines differed**, because Google News
returns a rolling result set and the macro blocks include live index blogs.
That input drift, not model sampling, is what made two runs of the same ticker
on the same day incomparable.
"""

import pytest

from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.snapshot_cache import (
    clear_snapshot_date,
    get_snapshot_date,
    set_snapshot_date,
    snapshot_cached,
)
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def cache_dir(tmp_path):
    before = dict(get_config())
    set_config({**DEFAULT_CONFIG, "data_cache_dir": str(tmp_path)})
    yield tmp_path
    set_config(before)
    clear_snapshot_date()


@pytest.mark.unit
def test_inert_until_a_snapshot_date_is_set(cache_dir):
    """Must be a no-op by default, so tests and ad-hoc calls are unaffected."""
    calls = []

    @snapshot_cached("probe")
    def fetch(x):
        calls.append(x)
        return f"live-{x}"

    clear_snapshot_date()
    assert fetch("a") == "live-a"
    assert fetch("a") == "live-a"
    assert calls == ["a", "a"], "no date set -> every call must hit the network"


@pytest.mark.unit
def test_second_call_replays_from_disk(cache_dir):
    calls = []

    @snapshot_cached("probe")
    def fetch(x):
        calls.append(x)
        return f"live-{x}-{len(calls)}"

    set_snapshot_date("2026-08-12")
    first = fetch("a")
    second = fetch("a")

    assert first == second == "live-a-1"
    assert calls == ["a"], "second call must be served from disk"


@pytest.mark.unit
def test_survives_a_new_process(cache_dir):
    """The whole point: lru_cache dies with the process, this must not."""
    calls = []

    def build():
        @snapshot_cached("probe")
        def fetch(x):
            calls.append(x)
            return "fetched"

        return fetch

    set_snapshot_date("2026-08-12")
    build()("a")
    # A freshly-decorated function stands in for a fresh interpreter: it shares
    # no in-memory state with the one above, only the directory on disk.
    build()("a")

    assert calls == ["a"]


@pytest.mark.unit
def test_a_different_date_refetches(cache_dir):
    """Daily runs must still pull fresh data."""
    calls = []

    @snapshot_cached("probe")
    def fetch(x):
        calls.append(x)
        return "v"

    set_snapshot_date("2026-08-12")
    fetch("a")
    set_snapshot_date("2026-08-13")
    fetch("a")

    assert len(calls) == 2


@pytest.mark.unit
def test_different_arguments_are_different_entries(cache_dir):
    calls = []

    @snapshot_cached("probe")
    def fetch(x):
        calls.append(x)
        return x

    set_snapshot_date("2026-08-12")
    fetch("a")
    fetch("b")
    fetch("a")

    assert calls == ["a", "b"]


@pytest.mark.unit
def test_namespaces_do_not_collide(cache_dir):
    """Two fetchers with identical signatures must not read each other."""
    @snapshot_cached("alpha")
    def one(x):
        return "from-alpha"

    @snapshot_cached("beta")
    def two(x):
        return "from-beta"

    set_snapshot_date("2026-08-12")
    assert one("k") == "from-alpha"
    assert two("k") == "from-beta"


@pytest.mark.unit
def test_tuple_return_type_is_preserved(cache_dir):
    """google_news._search_cached returns tuple[dict, ...] so it stays
    hashable for lru_cache — JSON would hand back a list and break it."""
    @snapshot_cached("probe")
    def fetch():
        return ({"a": 1}, {"b": 2})

    set_snapshot_date("2026-08-12")
    fetch()
    replayed = fetch()

    assert isinstance(replayed, tuple)
    assert replayed == ({"a": 1}, {"b": 2})


@pytest.mark.unit
def test_disabling_the_cache_refetches(cache_dir):
    """What --refresh does."""
    calls = []

    @snapshot_cached("probe")
    def fetch():
        calls.append(1)
        return "v"

    set_snapshot_date("2026-08-12")
    fetch()
    set_config({**get_config(), "snapshot_cache_enabled": False})
    fetch()

    assert len(calls) == 2


@pytest.mark.unit
def test_an_unwritable_cache_never_breaks_the_fetch(cache_dir):
    """A cache is an optimisation, never a correctness dependency."""
    @snapshot_cached("probe")
    def fetch():
        return "live"

    set_snapshot_date("2026-08-12")
    set_config({**get_config(), "data_cache_dir": "\0invalid"})

    assert fetch() == "live"


@pytest.mark.unit
def test_unserialisable_results_still_return(cache_dir):
    """json.dump raises on these; the caller must still get its value."""
    sentinel = object()

    @snapshot_cached("probe")
    def fetch():
        return sentinel

    set_snapshot_date("2026-08-12")

    assert fetch() is sentinel


@pytest.mark.unit
def test_propagate_sets_the_snapshot_date():
    """Wiring check: without this the decorator stays inert in real runs."""
    from unittest.mock import MagicMock

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = MagicMock()
    graph.config = {"checkpoint_enabled": False}
    clear_snapshot_date()
    try:
        TradingAgentsGraph.propagate(graph, "SIEMENS.NS", "2026-08-12")
    except Exception:
        # The mock cannot complete a real run; only the early wiring matters.
        pass

    assert get_snapshot_date() == "2026-08-12"
    clear_snapshot_date()


@pytest.mark.unit
def test_every_live_fetcher_is_wrapped():
    """A new live fetcher added without this decorator silently reintroduces
    the drift, so enumerate them rather than trusting review."""
    from tradingagents.dataflows import (
        google_news,
        india_insider,
        india_news,
        nse_announcements,
        reddit,
        stocktwits,
    )

    expected = {
        google_news._search_cached: "google_news",
        india_news._fetch_articles_cached: "india_news",
        nse_announcements._fetch_cached: "nse_filings",
        stocktwits._fetch_stocktwits_messages_cached: "stocktwits",
        reddit._fetch_reddit_posts_cached: "reddit",
        india_insider._fetch_bulk_deals_csv: "nse_bulk_deals",
    }
    for fn, namespace in expected.items():
        inner = getattr(fn, "__wrapped__", fn)
        assert getattr(inner, "__wrapped_by_snapshot_cache__", None) == namespace, (
            f"{namespace} fetcher is not snapshot-cached"
        )
