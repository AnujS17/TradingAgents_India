# TradingAgents — India (NSE/BSE) Edition

A multi-agent LLM trading-analysis framework focused on Indian equities (NSE/BSE). This is a fork of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), re-pointed end-to-end at Indian markets: ticker resolution, news sources, exchange filings, and social sentiment are all sourced for `.NS`/`.BO` symbols instead of US tickers.

> **Research project, not financial advice.** Trading performance depends heavily on the chosen models, data quality, and market conditions. Nothing this framework outputs should be treated as investment advice. See the [original disclaimer](https://tauric.ai/disclaimer/).

## What this fork does differently

The upstream framework is US-market-oriented. This fork replaces or adds the data layer so every step actually works for Indian tickers:

| Area | Source(s) | Notes |
|---|---|---|
| Price / OHLCV / indicators | yfinance | Ticker auto-resolves a bare symbol (`RELIANCE`) to the right suffix (`RELIANCE.NS` / `.BO`) |
| Company news | Google News RSS search (primary), yfinance, GDELT, Alpha Vantage, Finnhub (fallback chain) | Search-based, not a capped feed — covers 30 days of company-specific news |
| Exchange filings | NSE `top-corp-info` API | Board meetings, results dates, corporate actions — treated as authoritative over news-inferred dates |
| Social sentiment | StockTwits (`.NSE` symbols), Reddit (India-focused subreddits) | Reddit results are verified locally against the ticker/company name before being trusted |
| Supplemental market news | RSS: Economic Times, LiveMint, CNBC-TV18, Business Line, Business Today, Google News India | |
| Promoter/insider activity | NSE bulk-deal data via `jugaad-data` | |
| FX / currency mismatch | yfinance FX tickers | Flags when a reported figure's currency doesn't match the instrument's home currency |

Default LLM provider is **DeepSeek** (`deepseek-v4-flash`); any provider supported by the underlying framework (OpenAI, Anthropic, Google, xAI, Qwen, GLM, MiniMax, OpenRouter, Ollama, Azure) also works — see [Configuration](#configuration).

## Agent Pipeline

```
Analysts (parallel)              Researchers            Trader        Risk Management       Portfolio
─────────────────────            ──────────────         ──────        ────────────────       ─────────
Market Analyst      ──┐                                                Aggressive Analyst
Fundamentals Analyst ─┼──►  Bull vs Bear debate  ──►  Trader  ──►      Neutral Analyst    ──►  Portfolio
News Analyst         ─┤     (Research Manager                          Conservative Analyst    Manager
Sentiment Analyst    ─┘      renders verdict)                          (3-way debate)          (final call)
```

- **Market Analyst** — technical indicators (RSI, MACD, Bollinger, ATR, VWMA, MFI) plus a 10-session trend view for momentum indicators, built from a deterministic, pre-verified snapshot rather than free-form tool calls.
- **Fundamentals Analyst** — financial statements, ratios, and promoter bulk-deal activity.
- **News Analyst** — company news, exchange filings, global/India macro news, and StockTwits (as an explicitly unverified lead source). Produces both the full report (saved to disk) and a compact synthesis reused by every downstream debate agent.
- **Sentiment Analyst** — StockTwits, Reddit, and supplemental India news, rendered as a structured sentiment score with confidence.
- **Researchers** — Bull and Bear agents debate the evidence; the Research Manager renders an investment plan.
- **Trader** — turns the plan into an entry/stop/target proposal.
- **Risk Management** — Aggressive, Neutral, and Conservative analysts debate the trader's plan.
- **Portfolio Manager** — approves, rejects, or adjusts the final decision.

Every analyst pre-fetches its own data deterministically before the LLM is invoked, and every claim in a report is traceable back to a logged tool call in `message_tool.log` — the pipeline is built to avoid hallucinated figures.

## Installation

```bash
git clone <this-repo-url>
cd TradingAgents_Ind

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -e .
```

### API keys

Create a `.env` file in the project root. Only `DEEPSEEK_API_KEY` is required for the default configuration; everything else is optional and improves coverage where noted.

```bash
# LLM provider (pick the one matching llm_provider in your config)
DEEPSEEK_API_KEY=...          # default provider
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
XAI_API_KEY=...

# Optional data-source coverage
ALPHA_VANTAGE_API_KEY=...     # fallback fundamentals/news vendor (rejects Indian tickers for news)
FINNHUB_API_KEY=...           # fallback news vendor
REDDIT_CLIENT_ID=...          # without this, Reddit falls back to a weaker public-JSON path
REDDIT_CLIENT_SECRET=...
```

Set the API key env var for whichever LLM provider you configure — see `tradingagents/default_config.py` for the full provider list and model catalog.

### Tests

```bash
.venv\Scripts\python.exe -m pytest tests/ -q -m unit
```

## CLI Usage

```bash
tradingagents                 # installed console command
python -m cli.main            # equivalent, run from source
```

The CLI walks you through: ticker, analysis date, which analysts to run, research depth, and LLM provider/model. Progress and each analyst's report stream live as the graph runs; the full report is saved under `results/<TICKER>/<date>/` at the end, and a raw tool-call/data log is written to `message_tool.log` in the same run's log directory for auditing.

```bash
tradingagents analyze --checkpoint           # resume a crashed/interrupted run
tradingagents analyze --clear-checkpoints    # reset saved checkpoints before running
tradingagents analyze --fast                 # fast platform profile — see below
```

### Fast mode

A default run analyses each of the four analysts one after another and asks every one of them for an exhaustive report, which commonly takes 10+ minutes end to end. `--fast` cuts that to roughly 3-4 minutes for interactive/platform use:

- the four analysts run **concurrently** instead of chained — they are independent (each needs only the ticker and date, none reads another's report), so the analyst phase collapses from the sum of four round-trips to roughly the slowest one
- 1 debate round instead of 2 (bull/bear and the 3-way risk debate each still get one full pass — no perspective is dropped, just the second iteration)
- `report_style="balanced"`: length budgets on the write-ups, but the summary tables and full source coverage are kept

**Fast mode fetches exactly the same data as a default run.** An earlier version also trimmed news article caps, narrowed the Reddit scope and dropped GDELT; all of that was reverted, because input size is not what costs wall-clock time (output generation is) and starving the inputs made the two modes incomparable on quality.

`--fast` also skips the interactive "Research Depth" prompt (it's pinned to match the profile) so an accidental Medium/Deep answer can't override the trim.

See `tradingagents/default_config.get_fast_config()` for the exact values.

### Reproducible runs

Re-running the same ticker and analysis date replays the **same inputs**. News, social and exchange-filing fetches are snapshotted to disk per (ticker, date), because live feeds move underneath you: two runs 11 minutes apart with the market closed differed by 22 of 63 news headlines, which is enough to change the verdict on its own.

```bash
tradingagents analyze --refresh    # ignore the snapshot and pull fresh data
```

A different analysis date is always a fresh fetch, so daily use is unaffected. Sampling is also pinned (`llm_temperature`, `llm_seed`) across every provider rather than just OpenRouter. Note this narrows run-to-run variance — it does not eliminate it, since no major provider guarantees bitwise-reproducible output even at a fixed seed.

## Python Usage

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

_, decision = ta.propagate("RELIANCE.NS", "2026-01-15")   # bare "RELIANCE" also resolves
print(decision)
```

Override any config value before constructing the graph:

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "anthropic"
config["deep_think_llm"] = "claude-sonnet-4-6"
config["quick_think_llm"] = "claude-haiku-4-5"
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("TCS.NS", "2026-01-15")
```

Or start from the fast platform profile instead (see [Fast mode](#fast-mode) above):

```python
from tradingagents.default_config import get_fast_config

ta = TradingAgentsGraph(debug=True, config=get_fast_config())
_, decision = ta.propagate("TCS.NS", "2026-01-15")
```

See `tradingagents/default_config.py` for the full set of options — news lookback windows, vendor fallback chains, debate/risk round counts, checkpoint settings, and more.

## Persistence

- **Decision log** (always on): each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, the framework fetches the realised return and injects a reflection plus recent cross-ticker lessons into the Portfolio Manager's prompt. Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.
- **Checkpoint resume** (opt-in, `--checkpoint`): LangGraph state is saved after each node so an interrupted run resumes instead of restarting. Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db`.

## Attribution

Built on [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents). If you use this work, please cite the original paper:

```bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138},
}
```
