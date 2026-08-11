from tradingagents.agents.utils import market_data_validation_tools, news_data_tools


def test_get_news_reuses_identical_vendor_call(monkeypatch):
    calls = {"count": 0}
    news_data_tools._cached_route_to_vendor.cache_clear()

    def fake_route(method, *args):
        calls["count"] += 1
        return f"{method}:{args}"

    monkeypatch.setattr(news_data_tools, "route_to_vendor", fake_route)

    first = news_data_tools.get_news.func("ORCL", "2026-05-27", "2026-06-03")
    second = news_data_tools.get_news.func("ORCL", "2026-05-27", "2026-06-03")

    assert first == second
    assert calls["count"] == 1


def test_verified_market_snapshot_reuses_identical_build(monkeypatch):
    calls = {"count": 0}
    market_data_validation_tools._cached_verified_market_snapshot.cache_clear()

    def fake_snapshot(symbol, curr_date, look_back_days):
        calls["count"] += 1
        return f"{symbol}:{curr_date}:{look_back_days}"

    monkeypatch.setattr(
        market_data_validation_tools,
        "build_verified_market_snapshot",
        fake_snapshot,
    )

    first = market_data_validation_tools.get_verified_market_snapshot.func(
        "ORCL",
        "2026-06-03",
        30,
    )
    second = market_data_validation_tools.get_verified_market_snapshot.func(
        "ORCL",
        "2026-06-03",
        30,
    )

    assert first == second
    assert calls["count"] == 1
