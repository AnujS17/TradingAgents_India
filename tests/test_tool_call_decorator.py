"""The logging decorator must preserve add_tool_call's return value.

`run_analysis` replaces `MessageBuffer.add_tool_call` on the instance with a
logging wrapper, so that wrapper *is* add_tool_call for every caller. It used
to swallow the boolean, so the audit loop's
``is_new_call = message_buffer.add_tool_call(...)`` always read None and the
`[Data]` payload line it gates was never written for any deterministic
pre-fetch. The BLUEJET run (2026-08-11) logged 26 [Tool Call] lines but only
16 [Data] lines — exactly the 16 belonging to the LLM's own ReAct calls, which
take a different code path. News, StockTwits, Reddit, NSE filings and the
market snapshot all recorded that they ran but not what they returned, which
is exactly what a hallucination audit needs.

The existing MessageBuffer tests could not catch this: they call the
undecorated method directly.
"""

from functools import wraps

import pytest

from cli.main import MessageBuffer


def _decorate(obj, func_name, log_lines):
    """Mirror run_analysis's save_tool_call_decorator, writing to a list."""
    func = getattr(obj, func_name)

    @wraps(func)
    def wrapper(*args, **kwargs):
        added = func(*args, **kwargs)
        if not added:
            return added
        timestamp, tool_name, call_args = obj.tool_calls[-1]
        log_lines.append(f"[Tool Call] {tool_name}")
        return added

    return wrapper


@pytest.fixture
def buffer_and_log():
    buffer = MessageBuffer()
    log: list[str] = []
    buffer.add_tool_call = _decorate(buffer, "add_tool_call", log)
    return buffer, log


@pytest.mark.unit
def test_decorated_add_tool_call_returns_true_for_a_new_call(buffer_and_log):
    buffer, _ = buffer_and_log

    assert buffer.add_tool_call("get_news", {"ticker": "BLUEJET.NS"}) is True


@pytest.mark.unit
def test_decorated_add_tool_call_returns_false_for_a_repeat(buffer_and_log):
    buffer, _ = buffer_and_log
    buffer.add_tool_call("get_news", {"ticker": "BLUEJET.NS"})

    assert buffer.add_tool_call("get_news", {"ticker": "BLUEJET.NS"}) is False


@pytest.mark.unit
def test_data_payload_is_logged_for_each_distinct_prefetch(buffer_and_log):
    """End-to-end of the audit loop's gating, through the decorator."""
    buffer, log = buffer_and_log

    prefetches = [
        ("get_news", {"ticker": "BLUEJET.NS"}, "30 google news articles"),
        ("fetch_stocktwits_messages", {"ticker": "BLUEJET.NS"}, "30 messages"),
        ("fetch_corporate_announcements", {"ticker": "BLUEJET.NS"}, "NSE filings"),
    ]
    for name, args, result in prefetches:
        if buffer.add_tool_call(name, args):
            buffer.add_message("Data", result)

    data_messages = [m for m in buffer.messages if m[1] == "Data"]
    assert len(data_messages) == 3
    assert [m[2] for m in data_messages] == [p[2] for p in prefetches]


@pytest.mark.unit
def test_repeat_prefetch_still_suppresses_its_data_line(buffer_and_log):
    # The dedup this gating was introduced for must still work.
    buffer, _ = buffer_and_log

    for _ in range(5):
        if buffer.add_tool_call("get_news", {"ticker": "BLUEJET.NS"}):
            buffer.add_message("Data", "payload")

    assert len([m for m in buffer.messages if m[1] == "Data"]) == 1
