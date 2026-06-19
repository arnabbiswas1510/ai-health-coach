"""Tests for GarminCalendarSyncer — guards against workout accumulation on the watch.

The "exceeded maximum number of workouts" warning occurs when:
1. Dated/scheduled workouts pile up on the Garmin calendar (old date-based approach)
2. Multiple "Coach:" library entries accumulate (overwrite bug)

These tests verify that upload_workout_to_library() always clears BOTH before uploading.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from services.garmin.calendar_syncer import GarminCalendarSyncer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_syncer(
    library_workouts: list[dict] | None = None,
    scheduled_workouts: list[dict] | None = None,
) -> tuple[GarminCalendarSyncer, MagicMock]:
    """Build a GarminCalendarSyncer with a fully mocked Garmin client."""
    client = MagicMock()
    gc = MagicMock()
    client.client = gc

    # get_workouts returns pages: first call returns library_workouts, subsequent empty
    _lib = list(library_workouts or [])
    gc.get_workouts.side_effect = lambda start, limit: _lib[start : start + limit]

    # Scheduled workouts on the calendar
    _sched = list(scheduled_workouts or [])
    gc.get_scheduled_workouts.return_value = _sched

    # upload_running_workout returns a workoutId
    gc.upload_running_workout.return_value = {"workoutId": 99999}

    syncer = GarminCalendarSyncer(client)
    return syncer, gc


def _make_suggestion(name: str = "Coach: Zone 2 Run") -> dict:
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
# Core regression: upload_workout_to_library MUST clear both calendar + library
# ---------------------------------------------------------------------------

class TestUploadWorkoutToLibraryClearsEverything:
    """Guard: upload_workout_to_library clears scheduled calendar entries AND
    old library workouts before uploading — preventing watch workout overflow."""

    def test_clears_scheduled_calendar_workouts_before_upload(self):
        """Regression: old dated workouts must be unscheduled to prevent
        'exceeded maximum workouts' warning on the watch."""
        scheduled = [
            {"date": "2026-06-25", "itemType": "workout", "id": 1001, "workoutId": 2001},
            {"date": "2026-06-26", "itemType": "workout", "id": 1002, "workoutId": 2002},
        ]
        syncer, gc = _make_syncer(scheduled_workouts=scheduled)

        with patch.object(syncer, "_clear_future_scheduled_workouts", wraps=syncer._clear_future_scheduled_workouts):
            syncer.upload_workout_to_library(_make_suggestion())

        # Must have fetched the schedule
        gc.get_scheduled_workouts.assert_called()

    def test_clears_future_scheduled_workouts_called_before_library_cleanup(self):
        """Verify call ordering: scheduled clear THEN library clear THEN upload."""
        syncer, gc = _make_syncer()
        call_order = []

        original_clear_sched = syncer._clear_future_scheduled_workouts
        original_clear_lib = syncer._clear_coach_library_workouts
        original_upload = gc.upload_running_workout

        def track_sched(*a, **kw):
            call_order.append("clear_scheduled")
            return original_clear_sched(*a, **kw)

        def track_lib(*a, **kw):
            call_order.append("clear_library")
            return original_clear_lib(*a, **kw)

        gc.upload_running_workout.side_effect = lambda w: (
            call_order.append("upload") or {"workoutId": 99999}
        )

        syncer._clear_future_scheduled_workouts = track_sched
        syncer._clear_coach_library_workouts = track_lib

        syncer.upload_workout_to_library(_make_suggestion())

        assert call_order == ["clear_scheduled", "clear_library", "upload"], (
            f"Wrong call order: {call_order}. "
            "clear_scheduled must run before clear_library which must run before upload."
        )

    def test_no_schedule_workout_call_on_upload(self):
        """Workouts must NOT be scheduled on a date — they go to the library only."""
        syncer, gc = _make_syncer()
        syncer.upload_workout_to_library(_make_suggestion())
        gc.schedule_workout.assert_not_called()

    def test_upload_running_workout_called_exactly_once(self):
        """Exactly one workout template must be uploaded per pipeline run."""
        syncer, gc = _make_syncer()
        syncer.upload_workout_to_library(_make_suggestion())
        assert gc.upload_running_workout.call_count == 1

    def test_returns_workout_id_as_string(self):
        syncer, gc = _make_syncer()
        wid = syncer.upload_workout_to_library(_make_suggestion())
        assert wid == "99999"


# ---------------------------------------------------------------------------
# Library cleanup: _clear_coach_library_workouts
# ---------------------------------------------------------------------------

class TestClearCoachLibraryWorkouts:
    """Guard: all 'Coach:' workouts are deleted before upload."""

    def test_deletes_all_coach_prefixed_workouts(self):
        lib = [
            {"workoutId": 1, "workoutName": "Coach: Zone 2 Run"},
            {"workoutId": 2, "workoutName": "Coach: Tempo Run"},
            {"workoutId": 3, "workoutName": "My Custom Workout"},  # should NOT be deleted
        ]
        syncer, gc = _make_syncer(library_workouts=lib)
        deleted = syncer._clear_coach_library_workouts()

        assert deleted == 2
        gc.delete_workout.assert_any_call("1")
        gc.delete_workout.assert_any_call("2")
        # Custom workout must be preserved
        for c in gc.delete_workout.call_args_list:
            assert c != call("3"), "Non-Coach workout was incorrectly deleted"

    def test_does_not_delete_non_coach_workouts(self):
        lib = [{"workoutId": 10, "workoutName": "My 5K Plan"}]
        syncer, gc = _make_syncer(library_workouts=lib)
        deleted = syncer._clear_coach_library_workouts()
        assert deleted == 0
        gc.delete_workout.assert_not_called()

    def test_paginates_beyond_100_workouts(self):
        """If library has >100 workouts, all pages must be fetched and cleaned."""
        # 150 Coach workouts: IDs 1-150 across two pages (IDs start at 1, not 0)
        page1 = [{"workoutId": i, "workoutName": f"Coach: Run {i}"} for i in range(1, 101)]
        page2 = [{"workoutId": i, "workoutName": f"Coach: Run {i}"} for i in range(101, 151)]

        client = MagicMock()
        gc = MagicMock()
        client.client = gc

        def paginated_get(start, limit):
            all_workouts = page1 + page2
            return all_workouts[start : start + limit]

        gc.get_workouts.side_effect = paginated_get

        syncer = GarminCalendarSyncer(client)
        deleted = syncer._clear_coach_library_workouts()

        assert deleted == 150, f"Expected 150 deleted, got {deleted}"
        assert gc.get_workouts.call_count >= 2, "Must paginate; only one call means page 2 was missed"

    def test_returns_zero_when_library_empty(self):
        syncer, gc = _make_syncer(library_workouts=[])
        assert syncer._clear_coach_library_workouts() == 0

    def test_handles_get_workouts_exception_gracefully(self):
        """If the library API fails, upload should proceed (not crash)."""
        client = MagicMock()
        gc = MagicMock()
        client.client = gc
        gc.get_workouts.side_effect = Exception("API timeout")
        gc.upload_running_workout.return_value = {"workoutId": 99999}

        syncer = GarminCalendarSyncer(client)
        # Should not raise
        deleted = syncer._clear_coach_library_workouts()
        assert deleted == 0

    def test_continues_deleting_after_single_delete_failure(self):
        """If one delete call fails, the rest should still be attempted."""
        lib = [
            {"workoutId": 1, "workoutName": "Coach: Run A"},
            {"workoutId": 2, "workoutName": "Coach: Run B"},
            {"workoutId": 3, "workoutName": "Coach: Run C"},
        ]
        client = MagicMock()
        gc = MagicMock()
        client.client = gc
        gc.get_workouts.side_effect = lambda s, l: lib[s : s + l]
        gc.delete_workout.side_effect = [Exception("403 Forbidden"), None, None]

        syncer = GarminCalendarSyncer(client)
        deleted = syncer._clear_coach_library_workouts()

        # 2 of 3 should succeed despite one failure
        assert deleted == 2
        assert gc.delete_workout.call_count == 3


# ---------------------------------------------------------------------------
# Scheduled workout cleanup: _clear_future_scheduled_workouts
# ---------------------------------------------------------------------------

class TestClearFutureScheduledWorkouts:
    """Guard: old calendar-dated workouts are always cleared."""

    def test_unschedules_future_workout_entries(self):
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        scheduled = [
            {"date": future_date, "itemType": "workout", "id": 5001, "workoutId": 6001},
        ]
        syncer, gc = _make_syncer(scheduled_workouts=scheduled)
        syncer._clear_future_scheduled_workouts(days_ahead=14)
        gc.unschedule_workout.assert_called_with(5001)
        gc.delete_workout.assert_called_with(6001)

    def test_does_not_touch_past_scheduled_workouts(self):
        from datetime import datetime, timedelta
        past_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        scheduled = [
            {"date": past_date, "itemType": "workout", "id": 7001, "workoutId": 8001},
        ]
        syncer, gc = _make_syncer(scheduled_workouts=scheduled)
        syncer._clear_future_scheduled_workouts(days_ahead=14)
        gc.unschedule_workout.assert_not_called()
