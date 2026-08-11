import pytest

from tradingagents.dataflows import india_insider

SAMPLE_CSV = (
    "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
    "Trade Price / Wght. Avg. Price,Remarks\n"
    "07-AUG-2026,RELIANCE,Reliance Industries Ltd,BIG FUND HOUSE LTD,BUY,500000,1400.50,-\n"
    "07-AUG-2026,RELIANCE,Reliance Industries Ltd,ANOTHER TRADER LLP,SELL,120000,1401.00,-\n"
    "07-AUG-2026,TCS,Tata Consultancy Services,SOME PROMOTER ENTITY,BUY,80000,3600.00,-\n"
)


@pytest.mark.unit
def test_fetch_promoter_bulk_deals_filters_by_symbol(monkeypatch):
    monkeypatch.setattr(india_insider, "_fetch_bulk_deals_csv", lambda: SAMPLE_CSV)

    result = india_insider.fetch_promoter_bulk_deals("RELIANCE.NS", "2026-08-07")

    assert "NSE Bulk-Deal Activity for RELIANCE" in result
    assert "BIG FUND HOUSE LTD" in result
    assert "ANOTHER TRADER LLP" in result
    assert "SOME PROMOTER ENTITY" not in result


@pytest.mark.unit
def test_fetch_promoter_bulk_deals_strips_bo_suffix(monkeypatch):
    monkeypatch.setattr(india_insider, "_fetch_bulk_deals_csv", lambda: SAMPLE_CSV)

    result = india_insider.fetch_promoter_bulk_deals("TCS.BO", "2026-08-07")

    assert "NSE Bulk-Deal Activity for TCS" in result
    assert "SOME PROMOTER ENTITY" in result


@pytest.mark.unit
def test_fetch_promoter_bulk_deals_no_match_returns_placeholder(monkeypatch):
    monkeypatch.setattr(india_insider, "_fetch_bulk_deals_csv", lambda: SAMPLE_CSV)

    result = india_insider.fetch_promoter_bulk_deals("INFY.NS", "2026-08-07")

    assert "no bulk-deal activity found for INFY" in result


@pytest.mark.unit
def test_fetch_promoter_bulk_deals_flags_stale_data(monkeypatch):
    monkeypatch.setattr(india_insider, "_fetch_bulk_deals_csv", lambda: SAMPLE_CSV)

    result = india_insider.fetch_promoter_bulk_deals("RELIANCE.NS", "2020-01-01")

    assert "may not reflect activity as of the requested analysis date 2020-01-01" in result


@pytest.mark.unit
def test_fetch_promoter_bulk_deals_degrades_gracefully_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(india_insider, "_fetch_bulk_deals_csv", lambda: None)

    result = india_insider.fetch_promoter_bulk_deals("RELIANCE.NS", "2026-08-07")

    assert "bulk-deal data unavailable" in result


@pytest.mark.unit
def test_fetch_promoter_bulk_deals_uses_configured_limit(monkeypatch):
    from tradingagents.dataflows.config import set_config
    import tradingagents.default_config as default_config

    csv_text = (
        "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
        "Trade Price / Wght. Avg. Price,Remarks\n"
    )
    for i in range(5):
        csv_text += f"07-AUG-2026,RELIANCE,Reliance Industries Ltd,FUND {i},BUY,1000,100.00,-\n"

    monkeypatch.setattr(india_insider, "_fetch_bulk_deals_csv", lambda: csv_text)
    set_config({**default_config.DEFAULT_CONFIG, "promoter_bulk_deals_limit": 2})
    try:
        result = india_insider.fetch_promoter_bulk_deals("RELIANCE.NS", "2026-08-07")
    finally:
        set_config(default_config.DEFAULT_CONFIG)

    assert "(2 deals found)" in result
