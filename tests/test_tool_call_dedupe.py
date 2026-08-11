from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.graph.trading_graph import _dedupe_tool_call


def test_duplicate_tool_call_is_short_circuited():
    calls = {"count": 0}

    request = SimpleNamespace(
        tool_call={
            "id": "call_2",
            "name": "sample_tool",
            "args": {"ticker": "ORCL"},
        },
        state=_state_with_prior_and_current("ORCL", "ORCL"),
    )

    def execute(req):
        calls["count"] += 1
        return ToolMessage(
            content="fresh data for ORCL",
            name="sample_tool",
            tool_call_id=req.tool_call["id"],
        )

    result = _dedupe_tool_call(request, execute)

    assert calls["count"] == 0
    assert "Duplicate tool call skipped" in result.content


def test_changed_tool_args_are_not_short_circuited():
    calls = {"count": 0}

    request = SimpleNamespace(
        tool_call={
            "id": "call_2",
            "name": "sample_tool",
            "args": {"ticker": "MSFT"},
        },
        state=_state_with_prior_and_current("ORCL", "MSFT"),
    )

    def execute(req):
        calls["count"] += 1
        return ToolMessage(
            content="fresh data for MSFT",
            name="sample_tool",
            tool_call_id=req.tool_call["id"],
        )

    result = _dedupe_tool_call(request, execute)

    assert calls["count"] == 1
    assert result.content == "fresh data for MSFT"


def _state_with_prior_and_current(prior_ticker: str, current_ticker: str):
    return {
        "messages": [
            AIMessage(
                content="Fetching data",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "sample_tool",
                        "args": {"ticker": prior_ticker},
                    }
                ],
            ),
            ToolMessage(
                content=f"fresh data for {prior_ticker}",
                name="sample_tool",
                tool_call_id="call_1",
            ),
            AIMessage(
                content="Fetching data again",
                tool_calls=[
                    {
                        "id": "call_2",
                        "name": "sample_tool",
                        "args": {"ticker": current_ticker},
                    }
                ],
            ),
        ]
    }
