from cli.main import MessageBuffer, _compact_log_content


def test_message_buffer_skips_duplicate_tool_calls_with_same_args():
    buffer = MessageBuffer()

    assert buffer.add_tool_call("get_news", {"ticker": "ORCL", "end_date": "2026-06-03"})
    assert not buffer.add_tool_call(
        "get_news",
        {"end_date": "2026-06-03", "ticker": "ORCL"},
    )

    assert len(buffer.tool_calls) == 1


def test_data_log_content_is_compacted_with_hash():
    content = "x" * 5000

    compacted = _compact_log_content("Data", content)

    assert len(compacted) < len(content)
    assert "truncated 1000 chars" in compacted
    assert "sha256=" in compacted


def _process_audit_call(buffer, name, args, result):
    """Mirrors run_analysis()'s stream-loop handling of a single audit_tool_calls
    entry (cli/main.py) — kept in sync with that code intentionally, since the
    loop itself isn't a standalone testable function.
    """
    is_new_call = buffer.add_tool_call(name, args)
    if is_new_call and result is not None:
        buffer.add_message("Data", str(result))


def test_audit_call_data_message_not_duplicated_on_repeat_chunk():
    # Regression test: stream_mode="values" re-emits the FULL state after
    # every graph node, and audit_tool_calls isn't cleared between an
    # analyst's own chunk and the "Msg Clear <X>" node immediately after it —
    # so the same audit_tool_calls entries arrive again on the very next
    # chunk. add_tool_call() already dedupes and returns False for a repeat,
    # but the caller used to log the [Data] message unconditionally
    # regardless of that return value, so the (often large) result was
    # re-logged every time even though the [Tool Call] announcement
    # correctly wasn't. Observed live: every analyst's full data dump
    # duplicated once in message_tool.log (LAURUSLABS.BO run, 2026-08-10).
    buffer = MessageBuffer()

    _process_audit_call(buffer, "get_news", {"ticker": "LAURUSLABS.BO"}, "some news data")
    _process_audit_call(buffer, "get_news", {"ticker": "LAURUSLABS.BO"}, "some news data")

    data_messages = [m for m in buffer.messages if m[1] == "Data"]
    assert len(data_messages) == 1
    assert data_messages[0][2] == "some news data"


def test_bulk_deals_audit_call_not_duplicated_across_whole_run():
    # fetch_promoter_bulk_deals (india_insider.py, called from
    # fundamentals_analyst.py) has no dedicated dedup logic of its own — it
    # relies entirely on this same generic mechanism. Its args (ticker,
    # curr_date) never change within a run, so once fundamentals_analyst
    # sets audit_tool_calls (no reducer on that state key means it persists
    # unchanged for every later node), the same entry re-arrives on every
    # subsequent stream_mode="values" chunk for the rest of the run — not
    # just the one immediately after. Confirms fix #8 covers this
    # tool-agnostically, without needing a bulk-deals-specific fix.
    buffer = MessageBuffer()

    for _ in range(12):
        _process_audit_call(
            buffer,
            "fetch_promoter_bulk_deals",
            {"ticker": "LAURUSLABS.BO", "curr_date": "2026-08-10"},
            "## NSE Bulk-Deal Activity for LAURUSLABS.BO\n- BUY: SOME FUND",
        )

    data_messages = [m for m in buffer.messages if m[1] == "Data"]
    assert len(data_messages) == 1
