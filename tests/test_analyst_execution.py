import unittest

from tradingagents.graph.analyst_execution import (
    ANALYST_NODE_SPECS,
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
    get_message_stream_channels,
    sync_analyst_tracker_from_chunk,
)


class AnalystExecutionPlanTests(unittest.TestCase):
    def test_build_plan_preserves_selected_order(self):
        plan = build_analyst_execution_plan(["news", "market"], concurrency_limit=2)

        self.assertEqual([spec.key for spec in plan.specs], ["news", "market"])
        self.assertEqual(plan.concurrency_limit, 2)
        self.assertEqual(plan.specs[0].agent_node, "News Analyst")
        self.assertEqual(plan.specs[0].tool_node, "tools_news")
        self.assertEqual(plan.specs[0].clear_node, "Msg Clear News")

    def test_rejects_unknown_analyst_keys(self):
        with self.assertRaises(ValueError):
            build_analyst_execution_plan(["market", "macro"])

    def test_requires_positive_concurrency_limit(self):
        with self.assertRaises(ValueError):
            build_analyst_execution_plan(["market"], concurrency_limit=0)

    def test_get_initial_analyst_node_uses_plan_metadata(self):
        plan = build_analyst_execution_plan(["fundamentals", "news"])

        self.assertEqual(
            get_initial_analyst_node(plan),
            "Fundamentals Analyst",
        )

    def test_social_key_displays_as_sentiment_analyst(self):
        # The wire key stays "social" for saved-config back-compat, but the
        # user-visible agent_node label must match the v0.2.5 rename so the
        # wall-time summary and any future consumer of agent_node says
        # "Sentiment Analyst" rather than the legacy "Social Analyst".
        plan = build_analyst_execution_plan(["social"])
        spec = plan.specs[0]
        self.assertEqual(spec.key, "social")
        self.assertEqual(spec.agent_node, "Sentiment Analyst")
        self.assertEqual(spec.report_key, "sentiment_report")


class MessageStreamChannelTests(unittest.TestCase):
    def test_includes_shared_channel_and_every_per_analyst_channel(self):
        plan = build_analyst_execution_plan(
            ["market", "social", "news", "fundamentals"],
            concurrency_limit=4,
        )

        self.assertEqual(
            get_message_stream_channels(plan),
            [
                "messages",
                "market_messages",
                "sentiment_messages",
                "news_messages",
                "fundamentals_messages",
            ],
        )

    def test_covers_selected_analysts_only(self):
        plan = build_analyst_execution_plan(["news"])

        self.assertEqual(
            get_message_stream_channels(plan),
            ["messages", "news_messages"],
        )

    def test_sequential_plans_still_need_the_per_analyst_channels(self):
        # The messages_key split is unconditional in setup.py — sequential
        # analysts write to their own channel too. A consumer that reads only
        # "messages" sees nothing from them in EITHER mode.
        plan = build_analyst_execution_plan(["market"], concurrency_limit=1)

        self.assertIn("market_messages", get_message_stream_channels(plan))

    def test_every_known_analyst_channel_is_reachable(self):
        # Guards the failure mode directly: a new analyst added to
        # ANALYST_NODE_SPECS with a channel no consumer reads would go
        # silently unlogged, exactly as the four did after parallelisation.
        plan = build_analyst_execution_plan(list(ANALYST_NODE_SPECS))
        channels = set(get_message_stream_channels(plan))

        for key, spec in ANALYST_NODE_SPECS.items():
            self.assertIn(spec.messages_key, channels, f"{key} is unreachable")


class AnalystWallTimeTrackerTests(unittest.TestCase):
    def test_records_wall_time_when_analyst_completes(self):
        plan = build_analyst_execution_plan(["market", "news"])
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_started("market", started_at=10.0)
        tracker.mark_completed("market", completed_at=13.5)

        self.assertEqual(tracker.get_wall_times(), {"market": 3.5})

    def test_formats_summary_in_plan_order(self):
        plan = build_analyst_execution_plan(["news", "market"])
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_started("market", started_at=20.0)
        tracker.mark_completed("market", completed_at=22.25)
        tracker.mark_started("news", started_at=10.0)
        tracker.mark_completed("news", completed_at=14.0)

        self.assertEqual(
            tracker.format_summary(),
            "Analyst wall time: News 4.00s | Market 2.25s",
        )

    def test_syncs_wall_time_from_sequential_chunks(self):
        plan = build_analyst_execution_plan(["market", "news"])
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=10.0)
        self.assertEqual(tracker.get_wall_times(), {})

        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done"},
            now=13.0,
        )
        self.assertEqual(tracker.get_wall_times(), {"market": 3.0})

        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done", "news_report": "done"},
            now=18.0,
        )
        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 3.0, "news": 5.0},
        )

    def test_mark_launched_starts_only_the_first_analyst_when_sequential(self):
        plan = build_analyst_execution_plan(["market", "news"], concurrency_limit=1)
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_launched(started_at=0.0)
        tracker.mark_completed("market", completed_at=4.0)
        # news never started, so there is nothing to measure yet
        tracker.mark_completed("news", completed_at=4.0)

        self.assertEqual(tracker.get_wall_times(), {"market": 4.0})

    def test_mark_launched_starts_every_analyst_when_parallel(self):
        plan = build_analyst_execution_plan(
            ["market", "social", "news", "fundamentals"],
            concurrency_limit=4,
        )
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_launched(started_at=0.0)
        # Parallel analysts finish out of order; each must be timed from the
        # shared launch instant, not from when it happened to be observed.
        tracker.mark_completed("news", completed_at=9.0)
        tracker.mark_completed("social", completed_at=11.0)
        tracker.mark_completed("fundamentals", completed_at=12.0)
        tracker.mark_completed("market", completed_at=34.0)

        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 34.0, "social": 11.0, "news": 9.0, "fundamentals": 12.0},
        )

    def test_parallel_analysts_finishing_together_do_not_report_zero(self):
        # Regression: a real --fast run reported
        # "Market 34.22s | Sentiment 0.00s | News 0.00s | Fundamentals 11.20s".
        # Under parallelism several analysts' reports first become visible in
        # the SAME chunk. The sequential sync only ever marked one analyst
        # started, so the others were started and completed at the same
        # instant and measured 0.00s.
        plan = build_analyst_execution_plan(
            ["market", "social", "news", "fundamentals"],
            concurrency_limit=4,
        )
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=0.0)
        sync_analyst_tracker_from_chunk(
            tracker,
            {
                "market_report": "done",
                "sentiment_report": "done",
                "news_report": "done",
            },
            now=34.0,
        )
        sync_analyst_tracker_from_chunk(
            tracker,
            {
                "market_report": "done",
                "sentiment_report": "done",
                "news_report": "done",
                "fundamentals_report": "done",
            },
            now=45.0,
        )

        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 34.0, "social": 34.0, "news": 34.0, "fundamentals": 45.0},
        )

    def test_sequential_sync_still_serialises_starts(self):
        # The parallel branch must not leak into the sequential path: a
        # queued analyst has not started yet and must not accrue the time
        # spent waiting on the analyst ahead of it.
        plan = build_analyst_execution_plan(
            ["market", "news"],
            concurrency_limit=1,
        )
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=0.0)
        sync_analyst_tracker_from_chunk(tracker, {"market_report": "done"}, now=30.0)
        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done", "news_report": "done"},
            now=40.0,
        )

        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 30.0, "news": 10.0},
        )
