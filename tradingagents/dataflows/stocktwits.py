"""StockTwits public symbol-stream fetcher.

StockTwits exposes a per-symbol message stream at
``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` that requires no
API key, no OAuth, and no registration. Each message includes a
user-labeled sentiment field (``Bullish``/``Bearish``/null), the message
body, timestamp, and posting user.

The function is deliberately self-contained: short timeout, graceful
degradation on any HTTP or parse failure, and a string return type so
the calling agent gets a uniform interface regardless of whether the
network call succeeded.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from tradingagents.dataflows.snapshot_cache import snapshot_cached
from datetime import datetime, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# StockTwits identifies Indian equities with a `.NSE` suffix, not the
# yfinance `.NS`/`.BO` convention this codebase carries everywhere else.
# Passing the yfinance symbol straight through returns 404 for every single
# Indian ticker, which surfaced as "<stocktwits unavailable: HTTPError>" and
# was misread as the service being down (observed live: LAURUSLABS.BO 404s
# while LAURUSLABS.NSE returns a full 30-message stream, 2026-08-10).
# BSE-suffixed symbols map to `.NSE` too — StockTwits carries no separate
# `.BSE` namespace (LAURUSLABS.BSE also 404s).
_INDIA_SUFFIXES = (".NS", ".BO")
_STOCKTWITS_INDIA_SUFFIX = ".NSE"


def _symbol_candidates(ticker: str) -> tuple[str, ...]:
    """Symbol forms to try, most likely first.

    Indian tickers are retried bare after `.NSE` so a symbol StockTwits
    happens to list without a suffix still resolves.
    """
    normalized = ticker.upper().strip()
    for suffix in _INDIA_SUFFIXES:
        if normalized.endswith(suffix):
            base = normalized[: -len(suffix)]
            return (f"{base}{_STOCKTWITS_INDIA_SUFFIX}", base)
    return (normalized,)


def fetch_stocktwits_messages(ticker: str, limit: int = 30, timeout: float = 10.0) -> str:
    return _fetch_stocktwits_messages_cached(ticker.upper(), limit, timeout)


def _request_stream(symbol: str, timeout: float):
    """Return the parsed StockTwits payload for ``symbol``, or None on failure."""
    req = Request(
        _API.format(ticker=symbol),
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("StockTwits fetch failed for %s: %s", symbol, exc)
        return None


@lru_cache(maxsize=128)
@snapshot_cached("stocktwits")
def _fetch_stocktwits_messages_cached(ticker: str, limit: int, timeout: float) -> str:
    """Fetch recent StockTwits messages for ``ticker`` and return them as a
    formatted plaintext block ready for prompt injection.

    Returns a placeholder string when the endpoint is unreachable, the
    symbol has no messages, or the response shape is unexpected — the
    caller never has to special-case None or exceptions.
    """
    candidates = _symbol_candidates(ticker)
    data = None
    resolved = candidates[0]
    for candidate in candidates:
        data = _request_stream(candidate, timeout)
        if data is not None:
            resolved = candidate
            break

    if data is None:
        return f"<stocktwits unavailable for {ticker} (tried: {', '.join(candidates)})>"

    messages = data.get("messages", []) if isinstance(data, dict) else []
    if not messages:
        return f"<no StockTwits messages found for ${resolved}>"

    lines = []
    bullish = bearish = unlabeled = 0
    for m in messages[:limit]:
        created = m.get("created_at", "")
        user = (m.get("user") or {}).get("username", "?")
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"

        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "no-label"
        lines.append(f"[{created} · @{user} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} most-recent messages"
    )
    return summary + "\n\n" + "\n".join(lines)
