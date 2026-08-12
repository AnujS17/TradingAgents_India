"""Reddit search fetcher for ticker-specific discussion posts.

Primary path: PRAW/OAuth, using REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.
Fallback path: Reddit public JSON endpoints with browser-shaped headers.
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache

from tradingagents.dataflows.snapshot_cache import snapshot_cached
from typing import Iterable, Optional
from urllib.parse import quote_plus

import requests

from .company_names import company_search_terms

logger = logging.getLogger(__name__)

# India-market subreddits only. r/stocks and r/investing were dropped: they
# are overwhelmingly US-equity boards, so for an NSE/BSE ticker they cost two
# network round-trips per run and essentially never contain the symbol, while
# crowding out India-specific boards where the discussion actually happens.
# All seven below were verified live to exist and be reachable via the PRAW
# path (2026-08-10); ordered by subscriber count so the highest-signal boards
# are queried first.
DEFAULT_SUBREDDITS = (
    "IndianStockMarket",
    "IndiaInvestments",
    "IndianStreetBets",
    "StockMarketIndia",
    "IndianStocks",
    "NSEbets",
    "DalalStreetTalks",
)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36 TradingAgents/0.2"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.reddit.com/",
}


def _query_variants(ticker: str) -> list[str]:
    """Search terms for ``ticker``, base symbol and company name included.

    Suffixed tickers (e.g. RELIANCE.NS) essentially never appear verbatim in
    casual Reddit posts — retail traders write "RELIANCE", "$RELIANCE", or
    the company's actual name — so the exchange-qualified symbol is never
    searched. Company-name terms matter most for mid-caps whose ticker is a
    compressed form of the name: posts about Laurus Labs say "Laurus Labs",
    never "LAURUSLABS", so a symbol-only search reported zero discussion for
    a company that was being actively discussed.
    """
    return list(company_search_terms(ticker))


def _post_from_praw(p) -> dict:
    return {
        "title": p.title,
        "score": p.score,
        "num_comments": p.num_comments,
        "created_utc": p.created_utc,
        "selftext": p.selftext,
    }


def _get_reddit_client():
    try:
        import praw
    except ImportError:
        raise ImportError("Run: pip install praw")

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET in environment. "
            "Get credentials at https://www.reddit.com/prefs/apps"
        )

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=_BROWSER_HEADERS["User-Agent"],
    )


def _match_terms(ticker: str) -> list[str]:
    """Lowercased bare terms used to verify a post really is about ``ticker``."""
    return [term.strip('"').lower().lstrip("$") for term in _query_variants(ticker)]


def _post_mentions_ticker(title: str, selftext: str, terms: list[str]) -> bool:
    """True when the post text actually contains one of ``terms``.

    Reddit's own search cannot be trusted as a filter. Searching r/IndianStockMarket
    for "TMPV" returns generic portfolio-review threads whose title and body contain
    neither "TMPV" nor "Tata" — Reddit ranks on its own relevance signals (including
    comments, flair and image content) rather than restricting to the query. The
    search legs used to append those hits verbatim, so the sentiment prompt was
    handed portfolio chatter labelled "posts mentioning TMPV.NS" (observed live,
    TMPV.NS run 2026-08-10). The listing-scan leg always applied this check; the
    search legs did not, and that asymmetry was the bug.
    """
    haystack = f"{title or ''} {selftext or ''}".lower()
    return any(term and term in haystack for term in terms)


def _fetch_subreddit(reddit, ticker: str, sub: str, limit: int) -> list[dict]:
    """Fetch via PRAW, then scan listings if Reddit search returns nothing."""
    terms = _match_terms(ticker)
    results: list[dict] = []
    seen_ids: set[str] = set()

    # Search each variant, not the raw ticker: the exchange-qualified symbol
    # ("LAURUSLABS.BO") matches nothing on Reddit, so passing it straight
    # through made the search leg a guaranteed miss and left every result to
    # the listing-scan fallback below.
    for query in _query_variants(ticker):
        if len(results) >= limit:
            break
        try:
            posts = reddit.subreddit(sub).search(
                query, sort="new", time_filter="week", limit=limit
            )
            for p in posts:
                if p.id in seen_ids:
                    continue
                seen_ids.add(p.id)
                if not _post_mentions_ticker(
                    getattr(p, "title", ""), getattr(p, "selftext", ""), terms
                ):
                    continue
                results.append(_post_from_praw(p))
                if len(results) >= limit:
                    break
        except Exception as exc:
            logger.warning("Reddit search failed for r/%s / %s: %s", sub, query, exc)

    if len(results) >= limit:
        return results

    try:
        subreddit = reddit.subreddit(sub)
        listing_posts = list(subreddit.new(limit=50)) + list(subreddit.hot(limit=50))
        for p in listing_posts:
            if p.id in seen_ids:
                continue
            if not _post_mentions_ticker(
                getattr(p, "title", ""), getattr(p, "selftext", ""), terms
            ):
                continue
            seen_ids.add(p.id)
            results.append(_post_from_praw(p))
            if len(results) >= limit:
                break
    except Exception as exc:
        logger.warning("Reddit listing fetch failed for r/%s / %s: %s", sub, ticker, exc)

    return results


def _json_payload_or_none(response) -> Optional[dict]:
    """Parse a Reddit JSON response, returning None when Reddit is blocking us.

    Reddit refuses unauthenticated API access in two different shapes, and
    only one of them looks like a refusal:

    * ``www.reddit.com`` answers **403** with an HTML body — caught by a
      status check.
    * ``old.reddit.com`` answers **200** with an HTML body. The status check
      passes, ``raise_for_status()`` passes, and ``.json()`` then fails with
      ``Expecting value: line 2 column 5 (char 5)`` — which is simply the
      ``<`` of ``<!DOCTYPE html>`` on the second line. That surfaced as a
      parse error per query per subreddit, reading like a bug in our parsing
      rather than "Reddit is blocking anonymous access" (observed on the
      BLUEJET run, 2026-08-11).

    Detecting the HTML body directly turns a confusing stack of decode errors
    into one honest "blocked" signal.
    """
    if response.status_code in {403, 429}:
        return None
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "json" not in content_type:
        return None
    try:
        response.raise_for_status()
        return response.json()
    except Exception:  # noqa: BLE001 — caller logs once per subreddit
        return None


def _post_from_json(data: dict) -> dict:
    return {
        "title": data.get("title", ""),
        "score": data.get("score", 0),
        "num_comments": data.get("num_comments", 0),
        "created_utc": data.get("created_utc"),
        "selftext": data.get("selftext", ""),
    }


def _fetch_subreddit_json(ticker: str, sub: str, limit: int, timeout: float) -> list[dict]:
    """Fetch subreddit search results through browser-shaped JSON requests."""
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    seen_ids: set[str] = set()
    results: list[dict] = []
    terms = _match_terms(ticker)
    blocked = False

    for query in _query_variants(ticker):
        encoded_query = quote_plus(query)
        urls = [
            (
                f"https://www.reddit.com/r/{sub}/search.json"
                f"?q={encoded_query}&restrict_sr=1&sort=new&t=week&limit={limit}&raw_json=1"
            ),
            (
                f"https://old.reddit.com/r/{sub}/search.json"
                f"?q={encoded_query}&restrict_sr=1&sort=new&t=week&limit={limit}&raw_json=1"
            ),
        ]

        for url in urls:
            try:
                response = session.get(url, timeout=timeout)
            except Exception as exc:
                logger.debug("Reddit JSON request failed for r/%s / %s: %s", sub, query, exc)
                continue
            payload = _json_payload_or_none(response)
            if payload is None:
                blocked = True
                continue

            for child in payload.get("data", {}).get("children", []):
                data = child.get("data", {})
                post_id = data.get("id")
                if not post_id or post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                # Same untrusted-search problem as the PRAW leg: verify the
                # post text really mentions the company before keeping it.
                if not _post_mentions_ticker(
                    data.get("title", ""), data.get("selftext", ""), terms
                ):
                    continue
                results.append(_post_from_json(data))
                if len(results) >= limit:
                    return results

            if results:
                break

    if results:
        return results
    if blocked:
        # One honest line per subreddit instead of one decode error per query.
        logger.warning(
            "Reddit is refusing anonymous API access for r/%s; set "
            "REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET to use the authenticated path",
            sub,
        )
        return []
    return _fetch_subreddit_listing_json(ticker, sub, limit, timeout)


def _fetch_subreddit_listing_json(ticker: str, sub: str, limit: int, timeout: float) -> list[dict]:
    """Fetch listing pages and filter locally when public JSON search is empty."""
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    terms = _match_terms(ticker)
    urls = [
        f"https://{host}/r/{sub}/{listing}.json?limit=50&raw_json=1"
        for host in ("www.reddit.com", "old.reddit.com")
        for listing in ("new", "hot")
    ]

    seen_ids: set[str] = set()
    results: list[dict] = []

    for url in urls:
        try:
            response = session.get(url, timeout=timeout)
        except Exception as exc:
            logger.debug("Reddit listing request failed for r/%s: %s", sub, exc)
            continue
        payload = _json_payload_or_none(response)
        if payload is None:
            continue

        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            post_id = data.get("id")
            if not post_id or post_id in seen_ids:
                continue
            if not _post_mentions_ticker(
                data.get("title", ""), data.get("selftext", ""), terms
            ):
                continue
            seen_ids.add(post_id)
            results.append(_post_from_json(data))
            if len(results) >= limit:
                return results

    return results


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 0.4,
) -> str:
    return _fetch_reddit_posts_cached(
        ticker.upper(),
        tuple(subreddits),
        limit_per_sub,
        timeout,
        inter_request_delay,
    )


@lru_cache(maxsize=128)
@snapshot_cached("reddit")
def _fetch_reddit_posts_cached(
    ticker: str,
    subreddits: tuple[str, ...],
    limit_per_sub: int,
    timeout: float,
    inter_request_delay: float,
) -> str:
    reddit = None
    try:
        reddit = _get_reddit_client()
    except (ImportError, ValueError) as exc:
        logger.warning("Reddit client init failed: %s", exc)

    blocks = []
    total_posts = 0

    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(inter_request_delay)

        # An authenticated PRAW query is authoritative: if it ran, "no posts"
        # is an answer, not a failure to be retried. Falling back on a
        # legitimate zero result meant every quiet ticker ran the (now dead)
        # public-JSON path across every subreddit — 6 failed requests per
        # subreddit, 42 warning lines for a 7-subreddit run, for a fallback
        # that cannot succeed. The JSON path is kept only for the case it was
        # written for: no PRAW credentials at all.
        if reddit is not None:
            posts = _fetch_subreddit(reddit, ticker, sub, limit_per_sub)
        else:
            posts = _fetch_subreddit_json(ticker, sub, limit_per_sub, timeout)
        total_posts += len(posts)

        if not posts:
            blocks.append(f"r/{sub}: <no posts found mentioning {ticker.upper()} in the past 7 days>")
            continue

        lines = [f"r/{sub} - {len(posts)} recent posts mentioning {ticker.upper()}:"]
        for p in posts:
            title = (p.get("title") or "").replace("\n", " ").strip()
            score = p.get("score", 0)
            comments = p.get("num_comments", 0)
            created = p.get("created_utc")
            created_str = (
                time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "?"
            )
            selftext = (p.get("selftext") or "").replace("\n", " ").strip()
            if len(selftext) > 240:
                selftext = selftext[:240] + "..."
            lines.append(
                f"  [{created_str} / {score:>4} up / {comments:>3}c] {title}"
                + (f"\n    body excerpt: {selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    if total_posts == 0:
        return (
            f"<no Reddit posts found mentioning {ticker.upper()} across "
            f"{', '.join(f'r/{s}' for s in subreddits)} in the past 7 days>"
        )
    return "\n\n".join(blocks)
