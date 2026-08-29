"""Environment-driven configuration for the HTTP layer.

Deliberately separate from ``tradingagents.default_config``: that one
configures the *analysis engine* (LLM provider, vendors, report style) and is
shared with the CLI. This one configures the *service* (ports, database,
queue, limits) and is meaningless to a CLI or notebook caller.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TRADINGAGENTS_API_",
        extra="ignore",
    )

    app_name: str = "TradingAgents API"
    app_version: str = "0.1.0"
    debug: bool = False

    # Populated in the next step (queue + persistence). Optional for now so the
    # app boots and /health works before Postgres and Redis exist.
    database_url: str | None = None
    redis_url: str | None = None

    # --- Cost controls -------------------------------------------------
    # On-demand analysis for the general public means every request spends
    # real LLM money, and a single client in a loop can run up a serious bill
    # overnight. These exist from the first commit rather than being added
    # after the first surprise invoice.
    max_runs_per_ip_per_day: int = 10
    max_runs_global_per_day: int = 500
    # Hard stop. When the global counter trips, queueing is refused outright
    # rather than degraded, because a partial run still costs a full one.
    kill_switch_enabled: bool = False

    # A run takes ~220s (fast) to ~800s (detailed), so it can never be an HTTP
    # request. Clients poll or stream instead; this bounds how long a job may
    # occupy a worker before being reaped.
    run_timeout_seconds: int = 1800

    # How many runs api.worker executes at once, in one process. claim_next_run's
    # conditional UPDATE already guarantees two lanes can't claim the same row, so
    # this is the only knob needed for concurrency -- default 1 keeps today's
    # strictly-serial behavior until someone opts in.
    worker_concurrency: int = 1

    # RFC 8292 VAPID "sub" claim: a contact URI the push service can show if
    # it needs to reach the sender, checked only for format (mailto: or
    # https://), never verified as deliverable. Change this to a real
    # address before this ever serves anyone but you.
    vapid_subject: str = "mailto:noreply@tradingagents.local"

    # Signs and verifies the JWT NextAuth issues (api/auth.py). No default,
    # deliberately: pydantic-settings raises at Settings() construction if
    # this is unset, which happens at app startup (api/main.py's
    # create_app -> get_settings()) -- so a missing secret fails closed at
    # boot, not open on the first request. Must match NEXTAUTH_SECRET on
    # the frontend exactly; they are the same value, not a keypair.
    jwt_secret: str

    allowed_origins: list[str] = ["http://localhost:3000"]
    allowed_methods: list[str] = ["GET", "POST", "OPTIONS"]
    allowed_headers: list[str] = ["Authorization", "Content-Type"]


@lru_cache
def get_settings() -> Settings:
    """Cached so a single Settings instance is shared, and so tests can clear
    it with ``get_settings.cache_clear()`` after patching the environment."""
    return Settings()
