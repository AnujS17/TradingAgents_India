import pytest

from tradingagents.graph.propagation import Propagator


@pytest.mark.unit
def test_initial_state_includes_resolved_instrument_context(monkeypatch):
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
