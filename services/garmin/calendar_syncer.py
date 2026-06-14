"""GarminCalendarSyncer: creates Garmin Connect workout objects and schedules workouts on the calendar.

Supports all three run types:
  - structured:  warmup + repeat-group intervals + cooldown
  - simple:      warmup + steady HR-zone run + cooldown
  - long:        warmup + long easy run + cooldown (no HR target)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .client import GarminConnectClient

if TYPE_CHECKING:
    from .plan_parser import ParsedWorkout

logger = logging.getLogger(__name__)

# HR target dict builder
def _HR_TARGET_TYPE():
    return {
        "workoutTargetTypeId": 4,  # TargetType.HEART_RATE
        "workoutTargetTypeKey": "heart.rate.zone",
        "displayOrder": 4,
    }


_NO_TARGET = {
    "workoutTargetTypeId": 1,  # TargetType.NO_TARGET
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}


class GarminCalendarSyncer:
    def __init__(self, client: GarminConnectClient):
        self.client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_plan_to_calendar(
        self,
        workouts: list[ParsedWorkout],
        clear_existing: bool = True,
        days_ahead: int = 35,
    ) -> list[str]:
        """Push a list of ParsedWorkout objects to Garmin Connect calendar.

        Args:
            workouts:       List from PlanParser.parse_weekly_plan()
            clear_existing: If True, unschedule all Garmin-scheduled workouts
                            for the next `days_ahead` days before pushing.
            days_ahead:     How many days forward to clear.

        Returns:
            List of workout_id strings for all pushed workouts.
        """
        if clear_existing:
            self._clear_future_scheduled_workouts(days_ahead=days_ahead)

        workout_ids: list[str] = []
        for pw in workouts:
            if pw.workout_type == "rest":
                logger.debug("Skipping rest day: %s", pw.date_str)
                continue
            try:
                workout_id = self._push_workout(pw)
                workout_ids.append(workout_id)
                logger.info(
                    "Scheduled %s workout '%s' on %s (id=%s)",
                    pw.workout_type, pw.workout_name, pw.date_str, workout_id,
                )
            except Exception:
                logger.exception("Failed to push workout for %s", pw.date_str)

        logger.info("Synced %d workouts to Garmin calendar", len(workout_ids))
        return workout_ids

    def sync_workout_to_calendar(self, workout_data: dict[str, Any], date_str: str) -> str:
        """Legacy single-workout sync (used by AdaptiveRunningCoach path).

        Creates a structured running workout and schedules it on the given date.
        Returns the workout ID string.
        """
        from garminconnect.workout import (
            RunningWorkout,
            WorkoutSegment,
            create_cooldown_step,
            create_interval_step,
            create_warmup_step,
        )

        logger.info("Building legacy Garmin workout: %s for %s", workout_data.get("workout_name", "Run"), date_str)
        segments = workout_data["structured_segments"]

        warmup = create_warmup_step(float(segments["warmup_secs"]), step_order=1)

        run_step = create_interval_step(
            float(segments["run_secs"]),
            step_order=2,
            target_type=_HR_TARGET_TYPE(),
        )
        run_step.targetValueOne = float(segments["target_hr_min"])
        run_step.targetValueTwo = float(segments["target_hr_max"])

        cooldown = create_cooldown_step(float(segments["cooldown_secs"]), step_order=3)

        total_duration = segments["warmup_secs"] + segments["run_secs"] + segments["cooldown_secs"]
        workout = RunningWorkout(
            workoutName=workout_data.get("workout_name", "Suggested Run"),
            estimatedDurationInSecs=int(total_duration),
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType={"sportTypeId": 1, "sportTypeKey": "running"},
                    workoutSteps=[warmup, run_step, cooldown],
                )
            ],
        )

        upload_result = self.client.client.upload_running_workout(workout)
        workout_id = str(upload_result["workoutId"])
        self.client.client.schedule_workout(workout_id, date_str)
        logger.info("Legacy workout synced: id=%s on %s", workout_id, date_str)
        return workout_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _push_workout(self, pw: ParsedWorkout) -> str:
        """Build and schedule a single workout. Returns workout_id string."""
        from garminconnect.workout import RunningWorkout, WorkoutSegment

        if pw.workout_type == "structured":
            steps = self._build_structured_steps(pw)
        elif pw.workout_type == "long":
            steps = self._build_long_steps(pw)
        else:
            steps = self._build_simple_steps(pw)

        workout = RunningWorkout(
            workoutName=pw.workout_name[:64],
            estimatedDurationInSecs=pw.estimated_duration_secs,
            description=pw.description[:500] if pw.description else None,
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType={"sportTypeId": 1, "sportTypeKey": "running"},
                    workoutSteps=steps,
                )
            ],
        )

        upload_result = self.client.client.upload_running_workout(workout)
        workout_id = str(upload_result["workoutId"])
        self.client.client.schedule_workout(workout_id, pw.date_str)
        return workout_id

    def _build_simple_steps(self, pw: ParsedWorkout) -> list:
        """Warmup → steady HR-zone run → cooldown."""
        from garminconnect.workout import (
            create_cooldown_step,
            create_interval_step,
            create_warmup_step,
        )
        if pw.target_hr_min and pw.target_hr_max:
            run_step = create_interval_step(pw.run_secs, step_order=2, target_type=_HR_TARGET_TYPE())
            run_step.targetValueOne = float(pw.target_hr_min)
            run_step.targetValueTwo = float(pw.target_hr_max)
        else:
            run_step = create_interval_step(pw.run_secs, step_order=2, target_type=_NO_TARGET)

        return [
            create_warmup_step(pw.warmup_secs, step_order=1),
            run_step,
            create_cooldown_step(pw.cooldown_secs, step_order=3),
        ]

    def _build_long_steps(self, pw: ParsedWorkout) -> list:
        """Warmup → long easy run (no HR target) → cooldown."""
        from garminconnect.workout import (
            create_cooldown_step,
            create_interval_step,
            create_warmup_step,
        )
        return [
            create_warmup_step(pw.warmup_secs, step_order=1),
            create_interval_step(pw.run_secs, step_order=2, target_type=_NO_TARGET),
            create_cooldown_step(pw.cooldown_secs, step_order=3),
        ]

    def _build_structured_steps(self, pw: ParsedWorkout) -> list:
        """Warmup → repeat group(s) → cooldown."""
        from garminconnect.workout import (
            create_cooldown_step,
            create_interval_step,
            create_recovery_step,
            create_repeat_group,
            create_warmup_step,
        )

        steps: list = [create_warmup_step(pw.warmup_secs, step_order=1)]
        step_order = 2

        for interval in pw.intervals:
            work = create_interval_step(
                interval["work_secs"], step_order=1, target_type=_HR_TARGET_TYPE()
            )
            work.targetValueOne = float(interval["hr_min"])
            work.targetValueTwo = float(interval["hr_max"])

            recovery = create_recovery_step(
                interval["recovery_secs"], step_order=2, target_type=_NO_TARGET
            )
            repeat = create_repeat_group(
                iterations=interval["iterations"],
                workout_steps=[work, recovery],
                step_order=step_order,
            )
            steps.append(repeat)
            step_order += 1

        steps.append(create_cooldown_step(pw.cooldown_secs, step_order=step_order))
        return steps

    def _clear_future_scheduled_workouts(self, days_ahead: int = 35) -> None:  # noqa: C901
        """Unschedule all Garmin-scheduled workouts for today + the next N days and delete their templates."""
        today = datetime.now().date()
        end_date = today + timedelta(days=days_ahead)

        # Gather unique (year, month) pairs to query
        months_to_check: set[tuple[int, int]] = set()
        cursor = today
        while cursor <= end_date:
            months_to_check.add((cursor.year, cursor.month))
            # Jump to first of next month
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)

        # Collect scheduled entries (schedule_id, workout_id) in date range
        to_clear: list[tuple[int, int | None]] = []
        for year, month in sorted(months_to_check):
            try:
                result = self.client.client.get_scheduled_workouts(year, month)
                entries = result if isinstance(result, list) else result.get("calendarItems", [])
                for entry in entries:
                    entry_date_str = entry.get("date", "")
                    try:
                        entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if today <= entry_date <= end_date:
                        if entry.get("itemType") == "workout" or entry.get("workoutId") is not None:
                            sched_id = entry.get("id") or entry.get("scheduleId")
                            workout_id = entry.get("workoutId")
                            if sched_id:
                                to_clear.append((int(sched_id), int(workout_id) if workout_id else None))
            except Exception:
                logger.warning("Could not fetch scheduled workouts for %d/%d", year, month, exc_info=True)

        logger.info("Clearing %d scheduled workouts before pushing new plan", len(to_clear))
        for sched_id, workout_id in to_clear:
            try:
                self.client.client.unschedule_workout(sched_id)
                logger.debug("Unscheduled workout calendar entry %s", sched_id)
            except Exception:
                logger.warning("Could not unschedule entry %s", sched_id, exc_info=True)

            if workout_id:
                try:
                    self.client.client.delete_workout(workout_id)
                    logger.debug("Deleted workout template %s from library", workout_id)
                except Exception:
                    logger.warning("Could not delete workout template %s from library", workout_id, exc_info=True)

