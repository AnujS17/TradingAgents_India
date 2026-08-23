import pytest

from tradingagents.graph.propagation import Propagator


@pytest.mark.unit
def test_initial_state_includes_resolved_instrument_context(monkeypatch):
    # Also mock resolve_ticker_symbol: this test is about how a resolved
    # identity gets woven into instrument_context, not about ticker
    # resolution itself, so it should not depend on live network/real
    # ticker validity (a bare "ORCL" is a real NYSE ticker and would now
    # correctly raise TickerNotFoundError -- this tool only resolves
    # NSE/BSE). Returns the ticker unchanged to keep every existing
    # assertion below valid without further changes.
    monkeypatch.setattr(
        "tradingagents.graph.propagation.resolve_ticker_symbol",
        lambda ticker, asset_type="stock": ticker,
    )
    monkeypatch.setattr(
        "tradingagents.graph.propagation.resolve_instrument_identity",
        lambda ticker: {
            "company_name": "Oracle Corporation",
            "sector": "Technology",
            "industry": "Software",
            "exchange": "NYSE",
        },
    )

    state = Propagator().create_initial_state("ORCL", "2026-06-03")

    assert "instrument_context" in state
    assert "ORCL" in state["instrument_context"]
    assert "Oracle Corporation" in state["instrument_context"]
    assert "Technology / Software" in state["instrument_context"]


@pytest.mark.unit
def test_initial_state_defaults_investment_horizon_to_empty(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.graph.propagation.resolve_ticker_symbol",
        lambda ticker, asset_type="stock": ticker,
    )
    monkeypatch.setattr(
        "tradingagents.graph.propagation.resolve_instrument_identity",
        lambda ticker: {
            "company_name": "Oracle Corporation",
            "sector": "Technology",
            "industry": "Software",
            "exchange": "NYSE",
        },
    )

    state = Propagator().create_initial_state("ORCL", "2026-06-03")

    assert state["investment_horizon"] == ""


@pytest.mark.unit
def test_initial_state_carries_a_requested_investment_horizon(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.graph.propagation.resolve_ticker_symbol",
        lambda ticker, asset_type="stock": ticker,
    )
    monkeypatch.setattr(
        "tradingagents.graph.propagation.resolve_instrument_identity",
        lambda ticker: {
            "company_name": "Oracle Corporation",
            "sector": "Technology",
            "industry": "Software",
            "exchange": "NYSE",
        },
    )

    state = Propagator().create_initial_state(
        "ORCL", "2026-06-03", investment_horizon="3-6 months"
    )

    assert state["investment_horizon"] == "3-6 months"
