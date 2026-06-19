"""Tests for schedule_workout_for_today — guards against the watch sync regression.

The key behaviour:
  - upload_workout_to_library() uploads, returns workout_id (no date assigned)
  - schedule_workout_for_today(workout_id) calls schedule_workout(id, TODAY)
  - CLI calls both in sequence so the workout auto-syncs to the watch
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from services.garmin.calendar_syncer import GarminCalendarSyncer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_syncer() -> tuple[GarminCalendarSyncer, MagicMock]:
    client = MagicMock()
    gc = MagicMock()
    client.client = gc
    gc.get_workouts.return_value = []
    gc.get_scheduled_workouts.return_value = []
    gc.upload_running_workout.return_value = {"workoutId": 12345}
    gc.schedule_workout.return_value = {"scheduleId": 99}
    return GarminCalendarSyncer(client), gc


def _suggestion(name: str = "Coach: Zone 2 Run") -> dict:
    return {
        "workout_name": name,
        "distance_km": 6.0,
        "duration_min": 50,
        "structured_segments": {
            "warmup_secs": 300,
            "run_secs": 2700,
            "cooldown_secs": 300,
            "target_hr_min": 147,
            "target_hr_max": 154,
        },
    }


# ---------------------------------------------------------------------------
# schedule_workout_for_today
# ---------------------------------------------------------------------------

class TestScheduleWorkoutForToday:
    """Guard: workout is always scheduled for today so it auto-syncs to watch."""

    def test_calls_schedule_workout_with_todays_date(self):
        """Core contract: schedule_workout must be called with today's ISO date."""
        syncer, gc = _make_syncer()
        today = date.today().isoformat()

        syncer.schedule_workout_for_today("12345")

        gc.schedule_workout.assert_called_once_with("12345", today)

    def test_returns_todays_iso_date_string(self):
        syncer, gc = _make_syncer()
        today = date.today().isoformat()
        result = syncer.schedule_workout_for_today("12345")
        assert result == today

    def test_raises_on_api_failure(self):
        """If schedule_workout API fails, the exception must propagate so the
        caller knows the watch won't receive the workout."""
        syncer, gc = _make_syncer()
        gc.schedule_workout.side_effect = Exception("API 500")
        with pytest.raises(Exception, match="API 500"):
            syncer.schedule_workout_for_today("12345")

    def test_date_is_always_today_not_yesterday_or_tomorrow(self):
        """Regression: the scheduled date must match today, not be off by any days."""
        syncer, gc = _make_syncer()
        fixed_today = date(2025, 1, 15)

        with patch("services.garmin.calendar_syncer.date") as mock_date:
            mock_date.today.return_value = fixed_today
            # Allow normal date construction (used elsewhere)
            mock_date.side_effect = lambda *a, **k: date(*a, **k)
            # Call the method — it uses `from datetime import date` locally
            # so we need to patch at the module level inside calendar_syncer

        # Since the local import makes the above patch tricky, verify via
        # a simpler contract: the returned date always equals date.today()
        result = syncer.schedule_workout_for_today("99")
        assert result == date.today().isoformat(), (
            "schedule_workout_for_today must use today's date, not a fixed or cached one"
        )
        gc.schedule_workout.assert_called_once_with("99", date.today().isoformat())


# ---------------------------------------------------------------------------
# Full flow: upload_workout_to_library → schedule_workout_for_today
# ---------------------------------------------------------------------------

class TestUploadThenScheduleToday:
    """Guard: the two-step flow produces exactly one upload and one schedule call."""

    def test_upload_then_schedule_calls_both_apis(self):
        syncer, gc = _make_syncer()
        today = date.today().isoformat()

        workout_id = syncer.upload_workout_to_library(_suggestion())
        syncer.schedule_workout_for_today(workout_id)

        gc.upload_running_workout.assert_called_once()
        gc.schedule_workout.assert_called_once_with("12345", today)

    def test_schedule_uses_workout_id_from_upload(self):
        """The ID returned by upload must be the same ID passed to schedule."""
        syncer, gc = _make_syncer()
        gc.upload_running_workout.return_value = {"workoutId": 77777}

        workout_id = syncer.upload_workout_to_library(_suggestion())
        assert workout_id == "77777"

        syncer.schedule_workout_for_today(workout_id)
        gc.schedule_workout.assert_called_once_with("77777", date.today().isoformat())

    def test_no_schedule_call_during_library_upload(self):
        """upload_workout_to_library must NOT schedule — that's schedule_workout_for_today's job."""
        syncer, gc = _make_syncer()
        syncer.upload_workout_to_library(_suggestion())
        gc.schedule_workout.assert_not_called()

    def test_upload_failure_prevents_schedule(self):
        """If upload fails, schedule should never be called."""
        syncer, gc = _make_syncer()
        gc.upload_running_workout.side_effect = Exception("Upload failed")

        with pytest.raises(Exception):
            workout_id = syncer.upload_workout_to_library(_suggestion())
            syncer.schedule_workout_for_today(workout_id)

        gc.schedule_workout.assert_not_called()

    def test_old_coach_workouts_cleared_before_upload(self):
        """Regression: stale Coach: workouts must be deleted before each new upload
        so the watch library stays clean (single-entry guarantee)."""
        old_workouts = [
            {"workoutId": 1, "workoutName": "Coach: Old Run"},
            {"workoutId": 2, "workoutName": "Coach: Even Older Run"},
        ]
        client = MagicMock()
        gc = MagicMock()
        client.client = gc
        gc.get_workouts.side_effect = lambda s, l: old_workouts[s:s+l]
        gc.get_scheduled_workouts.return_value = []
        gc.upload_running_workout.return_value = {"workoutId": 99999}

        syncer = GarminCalendarSyncer(client)
        syncer.upload_workout_to_library(_suggestion())

        # Both old workouts must have been deleted
        gc.delete_workout.assert_any_call("1")
        gc.delete_workout.assert_any_call("2")
        assert gc.delete_workout.call_count == 2
