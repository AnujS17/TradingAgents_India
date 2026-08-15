# UI Kickoff Prompt — TradingAgents_Ind Web Platform

Paste this into a new Claude Code conversation (in this worktree) to start the UI design + build.

---

## Product Vision

Build a web platform where retail investors researching a stock can watch a team of AI analysts investigate it, debate the call, and reach a verdict — live, in an engaging and trustworthy interface. The differentiator versus a static "AI stock rating" tool is **transparency of reasoning**: the user sees *why*, not just *what*, including where the analysts disagree.

## Target User

A retail investor evaluating whether to buy/hold/sell an Indian-listed stock (NSE/BSE). Not a quant — wants clarity, not raw data dumps. Trusts the tool more when they can see its work, not just its conclusion.

## Core User Journey

1. **Search/select a stock** (ticker or company name, NSE/BSE India-focused — reuse the existing bare-ticker resolution, e.g. typing "TCS" should resolve to `TCS.NS`).
2. **Kick off an analysis** for today (or a past date for backtesting-style review).
3. **Watch it run, live** — analysts light up as they start/finish, partial findings stream in as each one completes, not just a spinner. This is the "engaging" part — reads like a live newsroom/war-room, not a progress bar.
4. **See the debate unfold** — bull vs. bear arguing the investment case; then, separately, three risk analysts (aggressive/neutral/conservative) debating the trade itself. Surface actual disagreement, not just a merged summary — that's the trust-building differentiator.
5. **Get the verdict** — final call (BUY/HOLD/SELL), confidence, entry/stop/target if given, and a plain-English "why" a non-expert can act on.
6. **Drill down** — every claim in the verdict should be traceable back to which analyst said it and what data backed it (this system is built specifically to avoid hallucinated numbers — that discipline should be visible in the UI, not just the backend).
7. **(Later) Compare past runs** for the same stock — the backend already keeps a decision history per ticker.

## What Data Actually Exists (ground the UI in this, don't invent a shape)

The backend is a LangGraph pipeline (`tradingagents/graph/trading_graph.py`) with these stages, in order:

**Analysts (run in parallel/sequence, each pre-fetches real data before reasoning):**
- **Market Analyst** — technical snapshot (OHLCV, RSI/MACD/Bollinger/ATR/VWMA/MFI + a 10-session trend for momentum indicators)
- **Fundamentals Analyst** — financial statements, ratios, promoter bulk-deal activity
- **News Analyst** — company news (Google News search), NSE exchange filings, macro/India news, StockTwits leads (flagged unverified); produces both a full report and a compact `news_synthesis`
- **Sentiment Analyst** — StockTwits + Reddit + India news, rendered as a structured band/score/confidence

**Research debate** (`investment_debate_state`): Bull and Bear analysts argue in rounds (`bull_history`, `bear_history`, `history`, `count`), then a Research Manager renders a verdict (`investment_plan`).

**Trader**: turns the plan into a concrete proposal (`trader_investment_plan`).

**Risk debate** (`risk_debate_state`): Aggressive, Neutral, and Conservative analysts debate the trader's plan in rounds (`aggressive_history`, `conservative_history`, `neutral_history`, `current_*_response` per speaker).

**Portfolio Manager**: final call (`final_trade_decision`) — approve/reject/adjust.

Every one of these steps is logged as it happens (`message_tool.log`: `[Tool Call]` / `[Data]` / analyst status lines) — this is exactly the event stream a "watch it run live" UI should consume. The CLI (`cli/main.py`, `MessageBuffer` class) already implements a terminal version of this live-status concept — read it for the state machine (`agent_status`, `report_sections`, streaming updates) before designing the web equivalent; don't reinvent that part.

## Suggested Tech Stack

- **Backend**: wrap `TradingAgentsGraph.propagate()` behind a FastAPI (or similar) service; stream progress over WebSocket/SSE rather than polling — the LangGraph `stream_mode="values"` the CLI already uses maps naturally onto server-sent events.
- **Frontend**: React/Next.js. Real-time UI (agent status, streaming debate text) is the core UX, so pick something with good WebSocket/streaming ergonomics.
- Keep the analysis engine (`tradingagents/`) untouched — this is a UI/API layer on top, not a rewrite.

## Key Screens to Design

1. **Search / Home** — ticker search with resolution feedback (typed "TCS" → resolves to "TCS.NS, Tata Consultancy Services").
2. **Live Analysis View** — the centerpiece. Agent roster with live status (queued/running/done), streaming in each analyst's findings as they land, not after the whole run finishes.
3. **Debate View** — bull vs. bear and the 3-way risk debate, visually distinct from the analyst reports (this is argument, not data) — maybe a chat/transcript layout, speaker-attributed.
4. **Verdict Card** — the final decision, prominent, with confidence and the entry/stop/target if present, plus a one-line "why."
5. **Source Drill-down** — click any claim → see the underlying tool data it came from (this is the hallucination-avoidance discipline made visible).
6. **History** (later) — past runs for a ticker, decision log.

## Design Direction

Trustworthy and professional, but approachable — not a Bloomberg terminal, not a meme-stock app. The live "agents at work" moment is the emotional hook; the verdict card is the payoff. Lean toward progressive disclosure: summary-first, expandable detail, so a non-expert isn't overwhelmed by default but power users can dig in.

## What to Do With This Prompt

Don't start writing code immediately. First:
1. Read `cli/main.py`'s `MessageBuffer` and streaming loop to understand the real event shape available to build on.
2. Propose an API contract (what the backend streams, in what shape) before touching the frontend.
3. Propose 2-3 concrete UI directions (wireframe-level) for the Live Analysis and Debate views specifically — those are the novel parts, not the search/verdict screens.
4. Then plan the build in phases (MVP: single-stock, single-run, live view + verdict; later: history, comparison, auth/accounts if needed).
