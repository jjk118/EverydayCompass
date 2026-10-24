import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts" / "whats_on_wakeup.py"
spec = importlib.util.spec_from_file_location("whats_on_wakeup_tested", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class WakeupTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 25, 5, 15, tzinfo=m.SGT)
        self.target = m.latest_window(self.now)
        self.feed = {"updated_at": "2026-10-25T04:20:00+08:00", "events": [{"title": "Current"}],
                     "sources": [{"status": "ok"}], "all_sources_failed": False}

    def test_daily_target_is_0415_singapore(self):
        self.assertEqual(self.target.isoformat(), "2026-10-25T04:15:00+08:00")

    def test_target_before_0415_is_previous_day(self):
        early = self.now.replace(hour=2)
        self.assertEqual(m.latest_window(early).isoformat(), "2026-10-24T04:15:00+08:00")

    def test_utc_conversion(self):
        self.assertEqual(self.target.astimezone(timezone.utc).strftime("%H:%M"), "20:15")

    def test_fresh_feed_skips_backup(self):
        self.assertEqual(m.recovery_decision(self.feed, [], self.target, self.now), "fresh")

    def test_partial_source_block_does_not_repeat_refresh(self):
        self.feed["sources"].append({"status": "fallback", "error": "HTTP 403"})
        self.assertEqual(m.recovery_decision(self.feed, [], self.target, self.now), "fresh")

    def test_yesterdays_feed_dispatches_recovery(self):
        self.feed["updated_at"] = "2026-10-24T04:20:00+08:00"
        self.assertEqual(m.recovery_decision(self.feed, [], self.target, self.now), "dispatch")

    def test_failed_run_without_new_feed_dispatches(self):
        self.feed["updated_at"] = "2026-10-24T04:20:00+08:00"
        runs = [{"head_branch": "main", "status": "completed", "conclusion": "failure"}]
        self.assertEqual(m.recovery_decision(self.feed, runs, self.target, self.now), "dispatch")

    def test_active_main_prevents_duplicate(self):
        self.assertEqual(m.recovery_decision({}, [{"head_branch": "main", "status": "queued"}],
                                             self.target, self.now), "active")

    def test_queued_more_than_30_minutes_can_be_recovered(self):
        run = {"head_branch": "main", "status": "queued", "created_at": "2026-10-25T04:15:00+08:00"}
        self.assertEqual(m.recovery_decision({}, [run], self.target, self.now), "dispatch")

    def test_other_branch_does_not_block(self):
        self.assertEqual(m.recovery_decision({}, [{"head_branch": "feature", "status": "in_progress"}],
                                             self.target, self.now), "dispatch")

    def test_complete_source_failure_retries(self):
        self.feed["all_sources_failed"] = True
        self.assertEqual(m.recovery_decision(self.feed, [], self.target, self.now), "dispatch")

    def test_bad_or_future_feed_time_is_not_fresh(self):
        for value in ("broken", "2026-10-25T04:20:00", "2026-10-26T04:20:00+08:00"):
            self.feed["updated_at"] = value
            self.assertFalse(m.feed_fresh(self.feed, self.target, self.now))

    def test_review_alert_after_saved_feed_does_not_loop(self):
        runs = [{"head_branch": "main", "status": "completed", "conclusion": "failure"}]
        self.assertEqual(m.recovery_decision(self.feed, runs, self.target, self.now), "fresh")

if __name__ == "__main__":
    unittest.main()
