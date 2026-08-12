"""Persist a run's fetched inputs to disk so re-runs replay identical data.

Why this exists
---------------
Price data was already cached to disk (``data_cache_dir/*.csv``), but every
news/social/filings fetcher used only ``functools.lru_cache`` — which lives in
process memory and dies when the CLI exits. So every run started cold and
re-fetched live, and Google News returns a rolling result set while the
"past week" macro blocks include live index blogs that update continuously.

Measured on SIEMENS.NS 2026-08-12, two runs 11 minutes apart with the market
closed: the verified market snapshot was byte-identical (it was disk-cached),
while **22 of 63 news headlines differed**. Between the 11:00 and 12:52 runs
the Sensex line moved from "-325 points, Nifty below 24,400" to "-600 points,
Nifty below 24,300" and "Siemens Boosts Full-Year Guidance" appeared.

That is a real input change, not model randomness — and it made A/B comparison
of two prompt profiles impossible, because the two arms were never reading the
same thing. Freezing the inputs per (ticker, analysis date) is a precondition
for measuring anything else, including whether pinned sampling helps.

Semantics
---------
- The key is (namespace, call arguments, ``snapshot_date``). A different
  analysis date is a different key, so daily runs still fetch fresh data.
- If ``snapshot_date`` is not set in config the decorator is a **no-op** and
  the wrapped function behaves exactly as before. Tests and any non-run caller
  are therefore unaffected unless they opt in.
- ``snapshot_cache_enabled: False`` disables it globally; the CLI's
  ``--refresh`` sets that for one run to deliberately pull fresh data.
- A read or write failure is swallowed and the real fetcher runs. A cache is
  an optimisation, never a correctness dependency.
"""

import hashlib
import json
import os
from functools import wraps


# Set explicitly by TradingAgentsGraph.propagate() for the duration of a run.
# A module global rather than a config key or a contextvar, deliberately:
# putting it in the shared config leaked between pytest cases (and wrote real
# directories into the user's cache dir), while contextvars do NOT propagate
# into ThreadPoolExecutor workers — and the fundamentals analyst pre-fetches
# through exactly such a pool. A plain global is visible from every thread and
# is cleared explicitly.
_SNAPSHOT_DATE = None


def set_snapshot_date(date):
    """Freeze fetches under ``date``. Pass None to disable."""
    global _SNAPSHOT_DATE
    _SNAPSHOT_DATE = str(date) if date else None


def get_snapshot_date():
    return _SNAPSHOT_DATE


def clear_snapshot_date():
    set_snapshot_date(None)


def _cache_root():
    from tradingagents.dataflows.config import get_config

    if not _SNAPSHOT_DATE:
        return None
    config = get_config()
    if not config.get("snapshot_cache_enabled", True):
        return None
    base = config.get("data_cache_dir")
    if not base:
        return None
    return os.path.join(base, "snapshots", _SNAPSHOT_DATE)


def _key(namespace, args, kwargs):
    # repr() over sorted kwargs so the key is stable across call styles.
    payload = repr((namespace, args, tuple(sorted(kwargs.items()))))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{namespace}-{digest}.json"


def _encode(value):
    """Preserve tuple-vs-list, which JSON would otherwise flatten.

    ``google_news._search_cached`` returns tuple[dict, ...] specifically so it
    is hashable for lru_cache; handing it back a list would break the caller.
    """
    if isinstance(value, tuple):
        return {"type": "tuple", "value": list(value)}
    return {"type": "raw", "value": value}


def _decode(payload):
    if payload.get("type") == "tuple":
        return tuple(payload["value"])
    return payload["value"]


def snapshot_cached(namespace):
    """Persist this fetcher's result under the current run's snapshot date.

    Stack it INSIDE ``lru_cache`` so the in-process memo still short-circuits
    repeat calls within a single run, and this only pays disk cost on the
    first call per key::

        @lru_cache(maxsize=64)
        @snapshot_cached("google_news")
        def _search_cached(query, timeout): ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            root = _cache_root()
            if root is None:
                return func(*args, **kwargs)

            path = os.path.join(root, _key(namespace, args, kwargs))
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return _decode(json.load(handle))
            except (OSError, ValueError, KeyError):
                pass

            result = func(*args, **kwargs)

            try:
                os.makedirs(root, exist_ok=True)
                # Write to a temp file then replace, so an interrupted run
                # cannot leave a truncated entry that later reads as valid.
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(_encode(result), handle)
                os.replace(tmp, path)
            except (OSError, TypeError, ValueError):
                pass

            return result

        wrapper.__wrapped_by_snapshot_cache__ = namespace
        return wrapper

    return decorator
