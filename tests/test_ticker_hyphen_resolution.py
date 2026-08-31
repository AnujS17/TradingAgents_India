"""A hyphen inside an NSE symbol must not read as "already qualified".

resolve_ticker_symbol short-circuited on any "." or "-", to pass crypto
pairs like BTC-USD through untouched. But hyphens are legal INSIDE NSE
symbols -- BAJAJ-AUTO is the textbook case -- so a real Indian ticker was
treated as exchange-qualified, never had .NS appended, and yfinance
answered "possibly delisted; no timezone found" while BAJAJ-AUTO.NS returns
1241 rows. Observed 2026-08-29: "Error building verified market snapshot
for BAJAJ-AUTO: yfinance returned no data".

It is worse than one failed snapshot. Every deterministic pre-fetch reads
the same resolved value (resolve_ticker_symbol's own docstring), so the
substitution degrades news, bulk deals, StockTwits and Reddit for the whole
run. It also bypassed the never-accept-a-bare-ticker protection, which
lives after the short-circuit and so never ran.
"""

import pytest

from tradingagents.agents.utils.agent_utils import (
    _has_exchange_suffix,
    resolve_ticker_symbol,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol,qualified",
    [
        # The bug: a hyphenated NSE symbol is NOT exchange-qualified.
        ("BAJAJ-AUTO", False),
        ("BAJAJ-AUTO.NS", True),
        # Crypto pairs must still pass through -- the reason the hyphen
        # rule existed at all.
        ("BTC-USD", True),
        ("ETH-INR", True),
        # Other venues Yahoo addresses with a dotted suffix.
        ("CNC.TO", True),
        ("VOD.L", True),
        ("7203.T", True),
        ("RELIANCE.NS", True),
        # Bare symbols must fall through to the NSE/BSE probe.
        ("RELIANCE", False),
        ("SKYGOLD", False),
        # A hyphenated non-crypto US symbol is still bare, not qualified.
        ("BRK-B", False),
    ],
)
def test_only_a_real_exchange_suffix_counts_as_qualified(symbol, qualified):
    assert _has_exchange_suffix(symbol) is qualified


@pytest.mark.unit
def test_a_hyphenated_nse_symbol_reaches_the_exchange_probe(monkeypatch):
    """The behavioural consequence: BAJAJ-AUTO must now be probed against
    NSE/BSE instead of being returned bare. Probes are stubbed so this
    asserts routing, not network behaviour."""
    import tradingagents.agents.utils.agent_utils as au

    probed = []

    def fake_probe(func, *a, **k):
        probed.append(True)
        return {"previousClose": 100.0}

    monkeypatch.setattr(au, "_probe_with_retry", fake_probe)
    monkeypatch.setattr(au, "_has_recent_history", lambda *a, **k: True)

    assert resolve_ticker_symbol("BAJAJ-AUTO", "stock") == "BAJAJ-AUTO.NS"
    assert probed, "a bare hyphenated symbol was returned without probing an exchange"


@pytest.mark.unit
def test_crypto_is_still_returned_untouched(monkeypatch):
    """Regression guard on the rule this change relaxed: a crypto pair must
    never be probed against NSE/BSE."""
    import tradingagents.agents.utils.agent_utils as au

    def explode(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("crypto must not be probed against an equity exchange")

    monkeypatch.setattr(au, "_probe_with_retry", explode)

    assert resolve_ticker_symbol("BTC-USD", "crypto") == "BTC-USD"


@pytest.mark.unit
def test_an_already_qualified_symbol_is_not_double_suffixed(monkeypatch):
    import tradingagents.agents.utils.agent_utils as au

    def explode(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("an already-qualified symbol must not be probed")

    monkeypatch.setattr(au, "_probe_with_retry", explode)

    assert resolve_ticker_symbol("KAYNES.NS", "stock") == "KAYNES.NS"
