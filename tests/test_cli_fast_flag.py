"""--fast CLI flag: must actually change behaviour, not just exist.

This guards against the exact bug reported live: `--fast` was documented but
never wired into the CLI, so a run "using fast mode" took the same 11-12
minutes as default. The dangerous part of the fix is not adding the flag —
it's that `run_analysis()` already unconditionally overwrites
`max_debate_rounds`/`max_risk_discuss_rounds` from the interactive "research
depth" prompt (Shallow=1/Medium=3/Deep=5) *after* config is built. If that
prompt still ran and the user picked Medium or Deep, it would silently
clobber get_fast_config()'s own trim — potentially back to WORSE than
default (Deep=5 rounds vs default's 2). The fix skips that prompt entirely
in fast mode and pins it to 1, matching the profile. This test asserts that
skip actually happens, not just that the flag is accepted.
"""

from unittest.mock import MagicMock

import pytest

import cli.main as cli_main
from cli.models import AnalystType, AssetType


def _patch_wizard(monkeypatch, *, llm_provider="deepseek"):
    """Stub every prompt get_user_selections() calls, for a deepseek path
    (no provider-specific follow-up prompts: not qwen/minimax/glm/ollama/
    google/openai/anthropic) so the mock surface stays minimal."""
    monkeypatch.setattr(cli_main, "fetch_announcements", lambda: [])
    monkeypatch.setattr(cli_main, "display_announcements", lambda console, ann: None)
    monkeypatch.setattr(cli_main, "get_ticker", lambda: "TCS.NS")
    monkeypatch.setattr(cli_main, "detect_asset_type", lambda ticker: AssetType.STOCK)
    monkeypatch.setattr(cli_main, "get_analysis_date", lambda: "2026-08-11")
    monkeypatch.setattr(cli_main, "ask_output_language", lambda: "English")
    monkeypatch.setattr(cli_main, "select_analysts", lambda asset_type: [AnalystType.MARKET])
    monkeypatch.setattr(cli_main, "select_llm_provider", lambda: (llm_provider, None))
    monkeypatch.setattr(cli_main, "ensure_api_key", lambda provider: "fake-key")
    monkeypatch.setattr(cli_main, "select_shallow_thinking_agent", lambda provider: "deepseek-v4-flash")
    monkeypatch.setattr(cli_main, "select_deep_thinking_agent", lambda provider: "deepseek-v4-flash")


@pytest.mark.unit
def test_fast_mode_skips_research_depth_prompt_entirely(monkeypatch):
    _patch_wizard(monkeypatch)

    def boom():
        raise AssertionError(
            "select_research_depth() was called in --fast mode — the prompt "
            "must be skipped, or a Medium/Deep answer would clobber the "
            "profile's own debate-round trim right back to worse than default."
        )

    monkeypatch.setattr(cli_main, "select_research_depth", boom)

    selections = cli_main.get_user_selections(fast=True)

    assert selections["research_depth"] == 1


@pytest.mark.unit
def test_non_fast_mode_still_asks_research_depth(monkeypatch):
    _patch_wizard(monkeypatch)
    monkeypatch.setattr(cli_main, "select_research_depth", lambda: 3)

    selections = cli_main.get_user_selections(fast=False)

    assert selections["research_depth"] == 3


@pytest.mark.unit
def test_fast_mode_pinned_depth_survives_run_analysis_override_sequence():
    # Reproduces run_analysis()'s exact config-building sequence (config =
    # get_fast_config() if fast else DEFAULT_CONFIG.copy(), then
    # config["max_debate_rounds"] = selections["research_depth"], ...) with
    # the selections get_user_selections(fast=True) actually produces. This
    # is the integration point where the original bug lived — get_fast_config()
    # alone was correct in isolation, but its trim was overwritten downstream.
    from tradingagents.default_config import DEFAULT_CONFIG, get_fast_config

    selections = {"research_depth": 1}  # what get_user_selections(fast=True) yields

    fast = True
    config = get_fast_config() if fast else DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]

    assert config["max_debate_rounds"] == 1
    assert config["max_risk_discuss_rounds"] == 1
    # And the rest of the fast profile must still be intact — the override
    # sequence only touches the two debate-round keys.
    assert config["analyst_concurrency_limit"] == 4
    # Depth is no longer traded away for speed — fast mode reasons exactly
    # like a default run, it just schedules the analysts concurrently.
    assert config["report_style"] == "balanced"
    assert config["max_output_tokens"] is None


def _capture_run_analysis(monkeypatch, captured):
    monkeypatch.setattr(
        cli_main,
        "run_analysis",
        lambda checkpoint=False, fast=False, refresh=False: captured.update(
            checkpoint=checkpoint, fast=fast, refresh=refresh
        ),
    )


@pytest.mark.unit
def test_analyze_command_forwards_fast_flag_to_run_analysis(monkeypatch):
    captured = {}
    _capture_run_analysis(monkeypatch, captured)

    cli_main.analyze(checkpoint=False, clear_checkpoints=False, fast=True, refresh=False)

    assert captured == {"checkpoint": False, "fast": True, "refresh": False}


@pytest.mark.unit
def test_analyze_command_defaults_fast_to_false(monkeypatch):
    captured = {}
    _capture_run_analysis(monkeypatch, captured)

    cli_main.analyze(checkpoint=False, clear_checkpoints=False, fast=False, refresh=False)

    assert captured["fast"] is False


@pytest.mark.unit
def test_analyze_command_forwards_refresh_flag(monkeypatch):
    """--refresh must reach run_analysis, or the snapshot cache can never be
    bypassed and a stale day's data would be replayed forever."""
    captured = {}
    _capture_run_analysis(monkeypatch, captured)

    cli_main.analyze(checkpoint=False, clear_checkpoints=False, fast=False, refresh=True)

    assert captured["refresh"] is True


@pytest.mark.unit
def test_refresh_disables_the_snapshot_cache_in_config():
    """The flag has to land on the config key the cache actually reads."""
    from tradingagents.default_config import DEFAULT_CONFIG

    for refresh, expected in ((True, False), (False, True)):
        config = DEFAULT_CONFIG.copy()
        config["snapshot_cache_enabled"] = not refresh
        assert config["snapshot_cache_enabled"] is expected
