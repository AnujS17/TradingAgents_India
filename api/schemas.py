"""HTTP request/response models.

Distinct from ``tradingagents.agents.schemas`` on purpose. Those are the
*agents'* structured-output contracts — changing one changes what the LLM is
asked to produce. These are the *wire* contract. Coupling them would mean a
prompt tweak silently becomes a breaking API change.
"""

from datetime import date as Date
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisProfile(str, Enum):
    """Maps to the engine's config profiles.

    ``fast`` is get_fast_config(): analysts run concurrently, 1 debate round,
    balanced report length — and it fetches exactly the same data as
    ``detailed``. See tradingagents/default_config.py.
    """

    FAST = "fast"
    DETAILED = "detailed"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    ticker: str = Field(
        min_length=1,
        max_length=32,
        description="NSE/BSE symbol. A bare name like 'RELIANCE' is resolved "
        "to 'RELIANCE.NS' by the engine.",
        examples=["SIEMENS.NS", "RELIANCE"],
    )
    analysis_date: Date | None = Field(
        default=None,
        description="Defaults to today. Also the cache key: a repeat request "
        "for the same ticker and date returns the existing run instead of "
        "spending a new one.",
    )
    profile: AnalysisProfile = AnalysisProfile.FAST

    force: bool = Field(
        default=False,
        description="Run a fresh analysis even when one already exists for "
        "this ticker and date. The existing run is kept — results accumulate "
        "rather than being overwritten, so they can be compared.",
    )
    refresh_data: bool = Field(
        default=False,
        description="Also re-fetch news, filings and social data instead of "
        "replaying the day's snapshot. Implies force. Use when something has "
        "actually happened since the last run; leave false to re-reason over "
        "identical inputs.",
    )

    @model_validator(mode="after")
    def refresh_implies_force(self) -> "AnalysisRequest":
        # Re-fetching without re-running would just throw the new data away.
        if self.refresh_data:
            self.force = True
        return self

    @field_validator("ticker")
    @classmethod
    def normalise_ticker(cls, value: str) -> str:
        # Upper-cased and stripped here so "reliance " and "RELIANCE" hit the
        # same cache entry rather than paying for two identical runs.
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("ticker must not be blank")
        return cleaned


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class TradeLevels(BaseModel):
    """Execution levels from the trader stage.

    THE BOOK IS LONG-ONLY: ``stop_loss`` always sits BELOW ``entry_price``,
    for every action including Sell — where it guards the retained position
    rather than a short. Either field may be null; the engine drops a stop it
    cannot make coherent rather than emitting a misleading number.
    """

    action: str | None = Field(default=None, description="Buy / Hold / Sell")
    entry_price: float | None = None
    stop_loss: float | None = None
    position_sizing: str | None = None


class Verdict(BaseModel):
    rating: str | None = Field(
        default=None, description="Buy / Overweight / Hold / Underweight / Sell"
    )
    price_target: float | None = None
    time_horizon: str | None = None
    levels: TradeLevels = Field(default_factory=TradeLevels)


class Reports(BaseModel):
    """The full analysis text, stage by stage.

    This is the substance of the product: a research tool surfaces the
    evidence and both sides of the argument, not just a rating. Every field is
    optional because a caller may deselect analysts.
    """

    market: str | None = None
    sentiment: str | None = None
    news: str | None = None
    fundamentals: str | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    investment_plan: str | None = None
    trader_plan: str | None = None
    risk_debate: str | None = None
    final_decision: str | None = None


class NewsSource(BaseModel):
    """One article the News or Sentiment report was actually given.

    Recovered from the pre-fetched article text those reports already
    embed verbatim — never a claim about which sentence in the report
    cites it, just "this was in the grounding set."
    """

    title: str
    source: str
    published_date: str | None = None
    url: str | None = None
    snippet: str | None = None


class RunSummary(BaseModel):
    """Lightweight view — list endpoints and poll responses use this."""

    id: str
    ticker: str
    analysis_date: Date
    profile: AnalysisProfile
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    cached: bool = Field(
        default=False,
        description="True when served from an existing run rather than a new "
        "analysis. Repeat requests for the same ticker and date are free.",
    )

    model_config = {"from_attributes": True}


class RunDetail(RunSummary):
    verdict: Verdict | None = None
    reports: Reports | None = None
    news_sources: list[NewsSource] = Field(
        default_factory=list,
        description="Articles the News/Sentiment reports were grounded in. "
        "Always a list — empty means nothing parsed, not an error.",
    )
    run_count: int = Field(
        default=1,
        description="How many analyses exist for this ticker, date and "
        "profile. Greater than 1 means someone requested a fresh run.",
    )
    verdict_is_contested: bool = Field(
        default=False,
        description="True when repeat runs of this same question reached "
        "DIFFERENT ratings. The inputs are identical by construction (the "
        "day's data is snapshotted), so disagreement means the evidence is "
        "genuinely balanced — that is information for the reader, not a bug "
        "to hide.",
    )


class RunHistory(BaseModel):
    """Every analysis for one ticker/date/profile, newest first."""

    ticker: str
    analysis_date: Date
    profile: AnalysisProfile
    run_count: int
    ratings: list[str | None] = Field(
        description="Rating from each completed run, newest first."
    )
    verdict_is_contested: bool
    runs: list[RunSummary]


class RunEventOut(BaseModel):
    """One streamed token chunk, as read back for the SSE payload."""

    seq: int
    node_name: str
    text_delta: str


class RunAccepted(BaseModel):
    """202 body for a newly queued run."""

    id: str
    status: RunStatus
    poll_url: str
    estimated_seconds: int = Field(
        description="Rough guide for the client's progress UI, not a promise."
    )


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    queue: str
