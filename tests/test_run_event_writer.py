"""Guard for api.streaming.RunEventWriter's buffering/flush behavior.

Uses a real temp sqlite file, not a mock -- the whole point of this
writer is a real, working sync sqlite3 connection.
"""

import sqlite3
import time

import pytest

from api.streaming import RunEventWriter


def _rows(db_path, run_id):
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT node_name, text_delta, seq FROM run_events WHERE run_id = ? ORDER BY seq",
        (run_id,),
    ).fetchall()
    conn.close()
    return rows


@pytest.mark.unit
def test_flushes_when_char_threshold_is_crossed(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=999, flush_chars=5)

    writer.on_token("market_analyst", "hello")  # exactly at threshold

    assert _rows(db_path, "run1") == [("market_analyst", "hello", 1)]
    writer.close()


@pytest.mark.unit
def test_buffers_below_threshold_until_flush_all(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=999, flush_chars=100)

    writer.on_token("market_analyst", "hi")
    assert _rows(db_path, "run1") == []  # below threshold, not yet flushed

    writer.flush_all()
    assert _rows(db_path, "run1") == [("market_analyst", "hi", 1)]
    writer.close()


@pytest.mark.unit
def test_separate_nodes_get_separate_buffers_and_increasing_seq(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=999, flush_chars=1)

    writer.on_token("bull_researcher", "a")
    writer.on_token("bear_researcher", "b")

    rows = _rows(db_path, "run1")
    assert [r[0] for r in rows] == ["bull_researcher", "bear_researcher"]
    assert [r[2] for r in rows] == [1, 2]  # seq increases across the whole run, not per-node
    writer.close()


@pytest.mark.unit
def test_flushes_on_time_threshold(tmp_path):
    db_path = tmp_path / "events.db"
    writer = RunEventWriter(str(db_path), "run1", flush_interval_s=0.05, flush_chars=9999)

    writer.on_token("market_analyst", "x")
    assert _rows(db_path, "run1") == []  # below char threshold

    time.sleep(0.08)
    writer.on_token("market_analyst", "y")  # triggers the time-based flush check

    assert _rows(db_path, "run1") == [("market_analyst", "xy", 1)]
    writer.close()
