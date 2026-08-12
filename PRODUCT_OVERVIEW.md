# What the platform is

Equity research for Indian stocks (NSE/BSE), aimed at retail investors doing
their own homework.

A user enters a ticker. A team of AI agents researches it, argues about it,
and hands back a recommendation with the full reasoning attached. One run
takes about 4 minutes and produces roughly 11,000 words.

The point of difference: most tools give you a number or a rating. This gives
you an **argument** — you see the case for buying, the case against, and who
won.

---

## The agents

Twelve agents in five teams. Each team hands its work to the next.

### 1. Analysts — four specialists, working simultaneously

| Agent | Looks at |
|---|---|
| **Market Analyst** | Price action, moving averages, RSI, MACD, volume |
| **Fundamentals Analyst** | Income statement, balance sheet, cash flow, valuation |
| **News Analyst** | News coverage and official exchange filings |
| **Sentiment Analyst** | StockTwits, Reddit, retail chatter |

Each writes an independent report. They do not see each other's work — that
comes next.

### 2. Research — the debate

- **Bull Researcher** reads all four reports and argues the case to buy.
- **Bear Researcher** reads the same reports *and the bull's argument*, then
  argues against.
- **Research Manager** judges the exchange, says which side won and why, and
  writes an investment plan.

This is the heart of the product. The bear responds to the bull's specific
claims rather than arguing into thin air.

### 3. Trading

- **Trader** turns the plan into something executable: buy / hold / sell, at
  what price, with what stop-loss, and how much to size.

### 4. Risk Management — a second debate, three ways

- **Aggressive Analyst** pushes for the higher-return, higher-risk stance.
- **Conservative Analyst** pushes for capital preservation.
- **Neutral Analyst** argues the middle and calls out where the other two
  overreach.

They critique the trader's plan, not the stock directly.

### 5. Portfolio

- **Portfolio Manager** weighs the risk debate and issues the final call.

---

## What a user gets

**A rating** — one of Buy / Overweight / Hold / Underweight / Sell.

**A trade** — action, entry price, stop-loss, position size. Any of these may
be deliberately absent; the system leaves a field blank rather than inventing
a number.

**The full reasoning** — ten documents: four analyst reports, the bull case,
the bear case, the research plan, the trader's plan, the risk debate, and the
final decision.

---

## Things that shape the experience

**It takes about 4 minutes.** Long enough that the wait is a real design
problem. A detailed run takes closer to 14.

**The agents can disagree with themselves.** Run the same stock twice and the
rating can come back different, because the evidence genuinely is balanced.
The system detects this and says so rather than hiding it.

**Not investment advice.** It is a research tool. The framing throughout is
"here is the evidence and both sides of the argument", not "buy this". That
matters both for the product and for Indian regulation.

**Everything is Indian-market specific** — ₹ amounts, NSE/BSE tickers, Indian
news sources, SEBI filings, Indian retail forums.
