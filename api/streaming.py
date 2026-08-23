"""Worker-side buffered writer for streamed token chunks.

Deliberately a plain sync sqlite3 connection, not the async SQLAlchemy
engine -- this runs inside api.worker's asyncio.to_thread call, off the
event loop, so there is nothing to gain from the async stack here (see
docs/superpowers/specs/2026-08-19-live-streaming-design.md).
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone


class RunEventWriter:
    def __init__(
        self,
        db_path: str,
        run_id: str,
        flush_interval_s: float = 0.25,
        flush_chars: int = 200,
    ):
        # check_same_thread=False: this connection is built here (in
        # execute_run's own thread) but on_token fires from inside
        # asyncio.to_thread's pool thread, and flush_all()/close() run
        # back in the original thread once that call returns -- never
        # concurrent, always sequential, but genuinely two different
        # threads over the connection's lifetime. sqlite3's default
        # same-thread check has no way to know that's safe.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._run_id = run_id
        self._flush_interval_s = flush_interval_s
        self._flush_chars = flush_chars
        self._buffers: dict[str, str] = {}
        self._last_flush_at: dict[str, float] = {}
        self._seq = 0
        self._create_table_if_needed()

    def _create_table_if_needed(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                node_name TEXT NOT NULL,
                text_delta TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_run_events_run_seq ON run_events (run_id, seq)
            """
        )
        self._conn.commit()

    def on_token(self, node_name: str, delta: str) -> None:
        # Initialize the node's flush time if not already done
        if node_name not in self._last_flush_at:
            self._last_flush_at[node_name] = time.monotonic()

        self._buffers[node_name] = self._buffers.get(node_name, "") + delta
        last = self._last_flush_at[node_name]
        crossed_chars = len(self._buffers[node_name]) >= self._flush_chars
        crossed_time = (time.monotonic() - last) >= self._flush_interval_s
        if crossed_chars or crossed_time:
            self._flush_node(node_name)

    def should_stop(self) -> bool:
        """Read the run's stop_requested flag straight from the runs table
        via this same connection -- the API process sets it through the
        async SQLAlchemy engine on the same on-disk file; WAL mode (see
        api/db.py) is exactly what makes that write visible to this
        separate sync connection in a different process. The `runs` table
        itself is owned by api/db.py; this only ever reads it."""
        row = self._conn.execute(
            "SELECT stop_requested FROM runs WHERE id = ?", (self._run_id,)
        ).fetchone()
        return bool(row and row[0])

    def flush_all(self) -> None:
        for node_name in list(self._buffers.keys()):
            self._flush_node(node_name)

    def _flush_node(self, node_name: str) -> None:
        text = self._buffers.get(node_name, "")
        if not text:
            return
        self._seq += 1
        self._conn.execute(
            "INSERT INTO run_events (run_id, seq, node_name, text_delta, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self._run_id, self._seq, node_name, text, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()
        self._buffers[node_name] = ""
        self._last_flush_at[node_name] = time.monotonic()

    def close(self) -> None:
        self._conn.close()
