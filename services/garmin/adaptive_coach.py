import logging
from datetime import datetime, timedelta
from typing import Any

from .models import Activity, GarminData

logger = logging.getLogger(__name__)

class AdaptiveRunningCoach:
    def __init__(self, garmin_data: GarminData, goal: str = "base_building", age: int = 53, weight_goal: str | None = None, height: float | None = None):
        self.garmin_data = garmin_data
        self.goal = goal
        self.age = age
        self.max_hr = 220 - age  # Estimate max HR: 167 for age 53

        profile = garmin_data.user_profile if garmin_data else None
        self.weight_goal = weight_goal or (profile.weight_goal if profile else None) or "maintain_lower_healthy_range"
        self.height = height or (profile.height if profile else None)

        # Zone 2 is 60% to 72% of max HR, or 100-117 bpm (longevity/cardio focus)
        self.zone2_low = int(self.max_hr * 0.60)
        self.zone2_high = int(self.max_hr * 0.72)

        self.running_activities = self._extract_running_activities()
        self.baselines = self._calculate_baselines()

    def _extract_running_activities(self) -> list[Activity]:
        if not self.garmin_data or not self.garmin_data.recent_activities:
            return []

        runs = [
            act
            for act in self.garmin_data.recent_activities
            if act.activity_type and "run" in act.activity_type.lower()
        ]

        # Sort by start_time ascending
        runs.sort(key=lambda x: x.start_time or "")
        return runs

    def _calculate_baselines(self) -> dict[str, Any]:  # noqa: C901
        runs = self.running_activities[-30:]  # Last 30 runs
        if not runs:
            return {
                "avg_distance_km": 5.0,  # sensible defaults
                "avg_duration_min": 35.0,
                "avg_pace_min_km": 7.0,
                "avg_hr": 130,
                "total_runs_count": 0,
                "weekly_mileage_estimate_km": 15.0
            }

        total_dist_meters = 0.0
        total_dur_secs = 0
        total_hr = 0
        hr_count = 0

        for run in runs:
            sumry = run.summary
            if not sumry:
                continue

            # Garmin distance can be in meters or kilometers depending on parsing.
            dist_val = sumry.distance or 0.0
            if dist_val > 100:
                dist_val_km = dist_val / 1000.0
            else:
                dist_val_km = dist_val

            total_dist_meters += dist_val_km * 1000.0
            total_dur_secs += sumry.duration or 0

            if sumry.average_hr:
                total_hr += sumry.average_hr
                hr_count += 1

        avg_dist_km = (total_dist_meters / len(runs)) / 1000.0 if runs else 5.0
        avg_dur_min = (total_dur_secs / len(runs)) / 60.0 if runs else 35.0

        avg_pace_min_km = 7.0
        if avg_dist_km > 0:
            avg_pace_min_km = avg_dur_min / avg_dist_km

        avg_hr = int(total_hr / hr_count) if hr_count > 0 else 130

        # Estimate current weekly mileage
        last_7_days = datetime.now() - timedelta(days=7)
        weekly_dist_m = 0.0
        for run in runs:
            if not run.start_time:
                continue
            try:
                run_date = datetime.fromisoformat(run.start_time.replace("Z", "+00:00"))
                if run_date.date() >= last_7_days.date():
                    dist_val = run.summary.distance or 0.0
                    if dist_val > 100:
                        weekly_dist_m += dist_val
                    else:
                        weekly_dist_m += dist_val * 1000.0
            except Exception:
                pass

        return {
            "avg_distance_km": round(avg_dist_km, 2),
            "avg_duration_min": round(avg_dur_min, 1),
            "avg_pace_min_km": round(avg_pace_min_km, 2),
            "avg_hr": avg_hr,
            "total_runs_count": len(runs),
            "weekly_mileage_estimate_km": round(weekly_dist_m / 1000.0, 2)
        }

    def suggest_next_run(self, missed_runs_count: int = 0, accumulated_debt_km: float = 0.0) -> dict[str, Any]:  # noqa: C901
        """Dynamically adjusts and suggests the next run.

        Redistributes missed mileage and resets debt intelligently for next week/month.
        Limits mileage debt accumulation to a maximum of 4 missed runs (1 month of debt).
        Rely heavily on the actual 30-run average to suggest the next run.
        """
        base_dist = self.baselines["avg_distance_km"]
        base_pace = self.baselines["avg_pace_min_km"]

        # Target heart rate bounds for longevity (Zone 2 running: 60-72% HR max)
        target_hr_min = self.zone2_low
        target_hr_max = self.zone2_high

        # Calculate new debt based on missed runs count
        # Each missed run represents one average run's distance of debt
        new_debt = missed_runs_count * base_dist
        total_debt = accumulated_debt_km + new_debt

        # Cap the accumulated debt to 4 average runs' worth of distance (~1 month of debt)
        max_debt = 4 * base_dist
        total_debt = min(total_debt, max_debt)

        remaining_debt = total_debt

        if missed_runs_count >= 4:
            # If the athlete missed a whole week (4+ runs), reset the debt to prevent injury
            # and scale back the next run to 85% of average distance to ease back in safely.
            logger.info("Athlete missed %d runs. Resetting mileage debt and scaling back volume for safety.", missed_runs_count)
            adjusted_dist = base_dist * 0.85
            remaining_debt = 0.0
            focus = "Safe Return (Reduced Volume)"
            notes = (
                f"You missed a significant block of runs ({missed_runs_count} runs). "
                f"To prevent injury and support longevity, your mileage debt has been reset to 0, "
                f"and we have scaled back your target distance to 85% of your 30-run average ({base_dist:.1f}km)."
            )
        elif missed_runs_count > 0:
            # If they missed a few runs, redistribute 10% of the mileage debt to the next run,
            # but cap the run distance to 1.10x the 30-run average to prevent unsafe volume spikes.
            redistributed_dist = 0.10 * total_debt
            proposed_dist = base_dist + redistributed_dist

            max_allowed_dist = base_dist * 1.10
            if proposed_dist > max_allowed_dist:
                adjusted_dist = max_allowed_dist
                # Deduct the portion we actually added
                added_dist = max_allowed_dist - base_dist
                remaining_debt = max(0.0, total_debt - added_dist)
            else:
                adjusted_dist = proposed_dist
                remaining_debt = max(0.0, total_debt - redistributed_dist)

            focus = "Adaptive Aerobic Run"
            notes = (
                f"You missed {missed_runs_count} run(s). We have adapted your training by "
                f"redistributing a small portion of the mileage debt ({redistributed_dist:.1f}km) "
                f"to this run, capped at 110% of your average for safe progression. "
                f"Remaining debt to be resolved/cleared next week: {remaining_debt:.1f}km."
            )
        # No missed runs. If base building, do a small, safe 5% progression.
        elif self.goal == "base_building":
            adjusted_dist = base_dist * 1.05
            focus = "Base Building Progression"
            notes = (
                f"Consistent execution! Gradual progression to 105% of your 30-run average "
                f"({base_dist:.1f}km) to build aerobic capacity and cardiovascular fitness."
            )
        else:
            adjusted_dist = base_dist
            focus = "Aerobic Maintenance Run"
            notes = "Consistent aerobic maintenance. Keep breathing light and comfortable."

        # Target duration based on average pace
        target_duration = adjusted_dist * base_pace

        # Pace formatting
        pace_min = int(base_pace)
        pace_sec = int((base_pace - pace_min) * 60)
        pace_str = f"{pace_min}:{pace_sec:02d} /km"

        # Build segments for Garmin Connect Workout
        # 5 mins warmup, steady run, 5 mins cooldown
        warmup_duration_secs = 300
        cooldown_duration_secs = 300
        run_duration_secs = int(target_duration * 60)

        workout_name = f"Coach: {focus.split(' ')[0]} {adjusted_dist:.1f}k"

        # Append Weight Management Check to suggestion notes
        if self.height:
            current_weight = None
            if self.garmin_data:
                profile = self.garmin_data.user_profile
                if profile and profile.weight:
                    current_weight = profile.weight
                elif self.garmin_data.body_metrics and self.garmin_data.body_metrics.weight:
                    weight_entries = self.garmin_data.body_metrics.weight.get("data", [])
                    if weight_entries:
                        current_weight = weight_entries[-1].get("weight")
                    if not current_weight:
                        current_weight = self.garmin_data.body_metrics.weight.get("average")

            height_m = self.height / 100.0
            min_weight = 18.5 * (height_m ** 2)
            lower_target_weight_max = 22.0 * (height_m ** 2)

            weight_analysis_note = "\n\n### Weight Management Check\n"
            if current_weight:
                current_bmi = current_weight / (height_m ** 2)
                weight_analysis_note += f"- **Current Weight**: {current_weight:.1f} kg ({current_weight * 2.20462:.1f} lbs)\n"
                weight_analysis_note += f"- **BMI**: {current_bmi:.1f} (Target Range: 18.5 - 22.0)\n"

                if current_bmi < 18.5:
                    weight_analysis_note += "- **Status**: Underweight. Priority: Avoid further weight loss. Focus on recovery and muscle preservation.\n"
                elif current_bmi > 22.0:
                    excess = current_weight - lower_target_weight_max
                    weight_analysis_note += f"- **Status**: Above lower-side target. Priority: Emphasize Zone 2 aerobic running and walk-run intervals to safely optimize fat oxidation and protect joints from impact. Target reduction: {excess:.1f} kg ({excess * 2.20462:.1f} lbs).\n"
                else:
                    weight_analysis_note += "- **Status**: Within target lower-healthy-range. Priority: Maintain consistency and balance training volume with caloric intake to avoid under-recovery.\n"
            else:
                weight_analysis_note += f"- **Target weight range (BMI 18.5 - 22.0)**: {min_weight:.1f} kg - {lower_target_weight_max:.1f} kg\n- Waiting for Garmin Connect weight scale data sync.\n"

            notes += weight_analysis_note

        return {
            "workout_name": workout_name,
            "focus": focus,
            "distance_km": round(adjusted_dist, 2),
            "duration_min": round(target_duration, 1),
            "target_pace_str": pace_str,
            "target_hr_range": f"{target_hr_min}-{target_hr_max} bpm",
            "notes": notes,
            "new_accumulated_debt_km": round(remaining_debt, 2),
            "structured_segments": {
                "name": workout_name,
                "warmup_secs": warmup_duration_secs,
                "cooldown_secs": cooldown_duration_secs,
                "run_secs": run_duration_secs,
                "target_hr_min": target_hr_min,
                "target_hr_max": target_hr_max,
                "target_pace_min": pace_min,
                "target_pace_sec": pace_sec
            }
        }
