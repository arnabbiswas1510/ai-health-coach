#!/usr/bin/env python3

import argparse
import asyncio
import getpass
import json
import logging
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

# Ensure project root is in python path
sys.path.append(str(Path(__file__).parent.parent))

from core.config import reload_config
from services.ai.ai_settings import ai_settings
from services.ai.langgraph.workflows.planning_workflow import (
    run_complete_analysis_and_planning,
)
from services.ai.utils.plan_storage import FilePlanStorage
from services.garmin import (
    AdaptiveRunningCoach,
    ExtractionConfig,
    GarminCalendarSyncer,
    PlanParser,
    TriathlonCoachDataExtractor,
)
from services.outside.client import OutsideApiGraphQlClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def parse_height_to_cm(height_val: Any) -> float | None:
    if height_val is None:
        return None
    if isinstance(height_val, (int, float)):
        return float(height_val)

    val_str = str(height_val).strip()
    if not val_str:
        return None

    try:
        return float(val_str)
    except ValueError:
        pass

    # Match feet and inches (e.g. 5'9", 5-9, 5 feet 9 inches, 5 ft 9)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(?:feet|foot|ft|'|-)\s*(\d+(?:\.\d+)?)\s*(?:inches|inch|in|\")?$", val_str, re.IGNORECASE)
    if m:
        feet = float(m.group(1))
        inches = float(m.group(2))
        total_inches = feet * 12.0 + inches
        return total_inches * 2.54

    # Match feet only (e.g. 5', 5 feet, 5 ft)
    m_feet = re.match(r"^(\d+(?:\.\d+)?)\s*(?:feet|foot|ft|')$", val_str, re.IGNORECASE)
    if m_feet:
        feet = float(m_feet.group(1))
        return feet * 12.0 * 2.54

    # Match centimeters (e.g. 175cm, 175.26 cm)
    m_cm = re.match(r"^(\d+(?:\.\d+)?)\s*(?:cm|centimeters)?$", val_str, re.IGNORECASE)
    if m_cm:
        try:
            return float(m_cm.group(1))
        except ValueError:
            pass

    return None


class ConfigParser:

    def __init__(self, config_path: Path | None):
        self.config_path = config_path
        self.config = self._load_config()
        self.prioritize_config = config_path is not None

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path or not self.config_path.exists():
            return {}

        content = self.config_path.read_text(encoding="utf-8")

        if self.config_path.suffix in [".yaml", ".yml"]:
            return yaml.safe_load(content) or {}
        elif self.config_path.suffix == ".json":
            return json.loads(content) or {}
        else:
            raise ValueError(f"Unsupported config format: {self.config_path.suffix}")

    def _get_val(self, env_key: str, config_path_keys: tuple[str, ...], default: Any) -> Any:
        config_val: Any = self.config
        for k in config_path_keys:
            if isinstance(config_val, dict):
                config_val = config_val.get(k)
            else:
                config_val = None
                break

        env_val = os.getenv(env_key)

        if self.prioritize_config:
            if config_val is not None:
                return config_val
            if env_val is not None:
                return env_val
        else:
            if env_val is not None:
                return env_val
            if config_val is not None:
                return config_val

        return default

    def get_athlete_info(self) -> tuple[str, str]:
        email = self._get_val("GARMIN_EMAIL", ("athlete", "email"), None)
        if not email:
            raise ValueError("Athlete email is required via GARMIN_EMAIL env var or config file")
        name = self._get_val("ATHLETE_NAME", ("athlete", "name"), "Athlete")
        return name, email

    def get_contexts(self) -> tuple[str, str]:
        analysis_context = os.getenv("CONTEXT_ANALYSIS") or os.getenv("ANALYSIS_CONTEXT")
        if self.prioritize_config:
            analysis_context = self.config.get("context", {}).get("analysis") or analysis_context
        else:
            analysis_context = analysis_context or self.config.get("context", {}).get("analysis")

        planning_context = os.getenv("CONTEXT_PLANNING") or os.getenv("PLANNING_CONTEXT")
        if self.prioritize_config:
            planning_context = self.config.get("context", {}).get("planning") or planning_context
        else:
            planning_context = planning_context or self.config.get("context", {}).get("planning")

        return (analysis_context or "").strip(), (planning_context or "").strip()

    def get_extraction_config(self) -> dict[str, Any]:
        def _to_int(val: Any) -> int | None:
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    pass
            return None

        def _to_bool(val: Any) -> bool | None:
            if val is not None:
                if isinstance(val, bool):
                    return val
                return val.lower() in ("true", "1", "yes")
            return None

        act_days = self._get_val("ACTIVITIES_DAYS", ("extraction", "activities_days"), None)
        met_days = self._get_val("METRICS_DAYS", ("extraction", "metrics_days"), None)
        ai_mode = self._get_val("AI_MODE", ("extraction", "ai_mode"), "development")
        plotting = self._get_val("ENABLE_PLOTTING", ("extraction", "enable_plotting"), None)
        hitl = self._get_val("HITL_ENABLED", ("extraction", "hitl_enabled"), None)
        skip = self._get_val("SKIP_SYNTHESIS", ("extraction", "skip_synthesis"), None)

        return {
            "activities_days": _to_int(act_days) if act_days is not None else 7,
            "metrics_days": _to_int(met_days) if met_days is not None else 14,
            "ai_mode": ai_mode,
            "enable_plotting": _to_bool(plotting) if plotting is not None else False,
            "hitl_enabled": _to_bool(hitl) if hitl is not None else True,
            "skip_synthesis": _to_bool(skip) if skip is not None else False,
        }

    def get_competitions(self) -> list[dict[str, Any]]:
        competitions = []
        env_comps = os.getenv("COMPETITIONS")
        config_comps = self.config.get("competitions")

        if self.prioritize_config:
            comps_source = config_comps or env_comps
        else:
            comps_source = env_comps or config_comps

        if isinstance(comps_source, str):
            try:
                competitions = json.loads(comps_source)
            except Exception as e:
                logger.error("Failed to parse COMPETITIONS environment variable: %s", e)
        elif isinstance(comps_source, list):
            competitions = comps_source

        return [
            {
                "name": comp.get("name", ""),
                "date": comp.get("date", ""),
                "race_type": comp.get("race_type", ""),
                "priority": comp.get("priority", "B"),
                "target_time": comp.get("target_time", ""),
            }
            for comp in competitions
        ]

    def get_output_directory(self) -> Path:
        out_dir = self._get_val("OUTPUT_DIR", ("output", "directory"), "./data")
        return Path(out_dir)

    def get_password(self) -> str:
        pwd = self._get_val("GARMIN_PASSWORD", ("credentials", "password"), "")
        if not pwd:
            pwd = getpass.getpass("Enter Garmin Connect password: ")
        return pwd

    def get_athlete_age(self) -> int:
        def _to_int(val: Any) -> int | None:
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    pass
            return None
        age = self._get_val("ATHLETE_AGE", ("athlete", "age"), 53)
        val = _to_int(age)
        return val if val is not None else 53

    def get_target_goal(self) -> str:
        return self._get_val("TARGET_GOAL", ("athlete", "target_goal"), "base_building")

    def get_sync_calendar(self) -> bool:
        def _to_bool(val: Any) -> bool:
            if isinstance(val, bool):
                return val
            if val is not None:
                return val.lower() in ("true", "1", "yes")
            return False
        sync = self._get_val("SYNC_CALENDAR", ("athlete", "sync_calendar"), False)
        return _to_bool(sync)

    def get_missed_runs_count(self) -> int:
        def _to_int(val: Any) -> int | None:
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    pass
            return None
        count = self._get_val("MISSED_RUNS_COUNT", ("athlete", "missed_runs_count"), 0)
        val = _to_int(count)
        return val if val is not None else 0

    def get_accumulated_debt_km(self) -> float:
        def _to_float(val: Any) -> float | None:
            if val is not None:
                try:
                    return float(val)
                except ValueError:
                    pass
            return None
        debt = self._get_val("ACCUMULATED_DEBT_KM", ("athlete", "accumulated_debt_km"), 0.0)
        val = _to_float(debt)
        return val if val is not None else 0.0

    def get_athlete_height(self) -> float | None:
        height_val = self._get_val("ATHLETE_HEIGHT", ("athlete", "height"), None)
        return parse_height_to_cm(height_val)

    def get_athlete_weight(self) -> float | None:
        def _to_float(val: Any) -> float | None:
            if val is not None:
                try:
                    return float(val)
                except ValueError:
                    pass
            return None
        weight_val = self._get_val("ATHLETE_WEIGHT", ("athlete", "weight"), None)
        return _to_float(weight_val)

    def get_weight_goal(self) -> str | None:
        return self._get_val("WEIGHT_GOAL", ("athlete", "weight_goal"), None)

    def get_zone2_bounds(self) -> tuple[int | None, int | None]:
        def _to_int(val: Any) -> int | None:
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    pass
            return None
        min_val = self._get_val("ZONE2_MIN", ("athlete", "zone2_min"), None)
        max_val = self._get_val("ZONE2_MAX", ("athlete", "zone2_max"), None)
        return _to_int(min_val), _to_int(max_val)


def fetch_outside_competitions_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    client = OutsideApiGraphQlClient()

    if isinstance(outside_cfg := config.get("outside"), dict) and any(
        isinstance(value, list) for value in outside_cfg.values()
    ):
        return client.get_competitions(outside_cfg)

    aggregate: list[dict[str, Any]] = []

    if isinstance(legacy_bikereg := config.get("bikereg", []), list) and legacy_bikereg:
        aggregate.extend(client.get_competitions(legacy_bikereg))

    if legacy_all := {
        key: entries
        for key in ("runreg", "trireg", "skireg")
        if isinstance(entries := config.get(key, []), list) and entries
    }:
        aggregate.extend(client.get_competitions(legacy_all))

    return aggregate


def _save_html_outputs(output_dir: Path, result: dict[str, Any]) -> list[str]:
    files_generated: list[str] = []

    for filename, key in [
        ("analysis.html", "analysis_html"),
        ("planning.html", "planning_html"),
    ]:
        if content := result.get(key):
            if isinstance(content, dict):
                content = content.get("content", "")

            if isinstance(content, str):
                # Robustly extract clean HTML by discarding any leading/trailing markdown blocks or text
                content_lower = content.lower()
                start_idx = content_lower.find("<!doctype html>")
                if start_idx == -1:
                    start_idx = content_lower.find("<html")
                if start_idx != -1:
                    content = content[start_idx:]
                    content_lower = content_lower[start_idx:]

                end_idx = content_lower.rfind("</html>")
                if end_idx != -1:
                    content = content[:end_idx + 7]

                content = content.strip()
                if filename == "analysis.html":
                    try:
                        from services.ai.langgraph.workflows.planning_workflow import _inject_iframe_helpers
                        content = _inject_iframe_helpers(content, is_planning=False)
                    except Exception as e:
                        logger.warning("Failed to inject iframe helpers to analysis.html: %s", e)

            output_path = output_dir / filename
            output_path.write_text(content, encoding="utf-8")
            files_generated.append(filename)
            logger.info("Saved: %s", output_path)

    return files_generated


def _save_expert_outputs(output_dir: Path, result: dict[str, Any]) -> list[str]:
    files_generated: list[str] = []

    for filename, key in [
        ("metrics_expert.json", "metrics_outputs"),
        ("activity_expert.json", "activity_outputs"),
        ("physiology_expert.json", "physiology_outputs"),
    ]:
        if output := result.get(key):
            output_path = output_dir / filename
            output_path.write_text(
                json.dumps(output.model_dump(mode="json"), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            files_generated.append(filename)
            logger.info("Saved: %s", output_path)

    return files_generated


def _save_plan_outputs(output_dir: Path, result: dict[str, Any]) -> list[str]:
    files_generated: list[str] = []

    storage = FilePlanStorage()
    user_id = result.get("user_id", "cli_user")

    for filename, key in [
        ("season_plan.md", "season_plan"),
        ("weekly_plan.md", "weekly_plan"),
    ]:
        if plan_dict := result.get(key):
            output = plan_dict.get("output", plan_dict) if isinstance(plan_dict, dict) else plan_dict
            if isinstance(output, str):
                output_path = output_dir / filename
                output_path.write_text(output, encoding="utf-8")
                files_generated.append(filename)
                logger.info("Saved: %s", output_path)
                storage.save_plan(user_id, key, output)

    return files_generated


def get_weight_analysis_context(height_cm: float, weight_kg: float | None, age: int, weight_goal: str) -> str:
    height_m = height_cm / 100.0
    min_bmi = 18.5
    max_bmi = 24.9

    min_weight = min_bmi * (height_m ** 2)
    max_weight = max_bmi * (height_m ** 2)

    # Target BMI range preferably on the lower side: 18.5 - 22.0
    lower_target_bmi_max = 22.0
    lower_target_weight_max = lower_target_bmi_max * (height_m ** 2)

    # Convert height to feet and inches for friendly display
    feet = int(height_cm / 2.54 / 12)
    inches = round((height_cm / 2.54) % 12)
    if inches == 12:
        feet += 1
        inches = 0
    height_ft_in = f"{feet}'{inches}\""

    # 4.5-Month Weight Loss Plan (Accountability Partner Tracker)
    # Start: June 13, 2026 at 179.8 lbs. Target: 160.0 lbs in 137 days (4.5 months).
    start_date = datetime(2026, 6, 13).date()
    start_weight_lbs = 179.8
    target_weight_lbs = 160.0
    target_days = 137
    daily_rate = (start_weight_lbs - target_weight_lbs) / target_days  # ~0.1445 lbs/day
    
    today_date = datetime.now().date()
    days_elapsed = max(0, (today_date - start_date).days)
    projected_weight_lbs = max(target_weight_lbs, start_weight_lbs - (days_elapsed * daily_rate))

    msg = f"""
## Athlete Physical Dimensions & Weight Goals
- **Height**: {height_cm:.1f} cm ({height_ft_in}) [Golden source of truth: Garmin Connect]
- **Age**: {age} years old
- **Healthy BMI Range (18.5 - 24.9)**: {min_weight:.1f} kg - {max_weight:.1f} kg ({min_weight * 2.20462:.1f} lbs - {max_weight * 2.20462:.1f} lbs)
- **Target Weight Range (preferably on the lower side, BMI 18.5 - 22.0)**: {min_weight:.1f} kg - {lower_target_weight_max:.1f} kg ({min_weight * 2.20462:.1f} lbs - {lower_target_weight_max * 2.20462:.1f} lbs)
- **Weight Management Goal**: {weight_goal}

### ⚖️ 4.5-Month Weight Loss Accountability Tracker
- **Plan Start Date**: 2026-06-13 (Start Weight: {start_weight_lbs:.1f} lbs)
- **Target Horizon**: 4.5 months (Projected completion: 2026-10-28, Target Weight: {target_weight_lbs:.1f} lbs)
- **Days Elapsed**: {days_elapsed} days
- **Today's Projected Weight Target**: {projected_weight_lbs:.1f} lbs
"""
    if weight_kg:
        current_weight_lbs = weight_kg * 2.20462
        current_bmi = weight_kg / (height_m ** 2)
        deviation_lbs = current_weight_lbs - projected_weight_lbs
        
        msg += f"- **Actual Current Weight**: {current_weight_lbs:.1f} lbs ({weight_kg:.1f} kg) [Source: Garmin Connect]\n"
        msg += f"- **Current BMI**: {current_bmi:.1f}\n"
        
        if deviation_lbs > 0.1:
            msg += f"- **Accountability Status**: 🚨 BEHIND PLAN BY {deviation_lbs:.1f} lbs\n"
            msg += f"- **Accountability Coaching Alert**: You are currently above your projected weight loss path. Coach demands review of calorie compliance, strict Zone 2 consistency (no pacing overshoots!), and limiting processed carbohydrates.\n"
        else:
            msg += f"- **Accountability Status**: 🎉 ON TRACK (Ahead of plan by {abs(deviation_lbs):.1f} lbs)\n"
            msg += f"- **Accountability Coaching Alert**: Excellent discipline! You are executing your calorie deficit and Zone 2 aerobic base building perfectly. Keep it up and maintain consistency.\n"

        if current_bmi < min_bmi:
            msg += "- **Status**: Underweight (BMI < 18.5). WARNING: Athlete is below the healthy range. Do NOT restrict calories or promote weight loss. Focus on muscle mass preservation, adequate recovery, and caloric sufficiency.\n"
        elif current_bmi > lower_target_weight_max:
            excess_weight = weight_kg - lower_target_weight_max
            msg += f"- **Status**: Above target lower-healthy-range. Goal: Focus on gradual, safe weight loss ({excess_weight:.1f} kg / {excess_weight * 2.20462:.1f} lbs to reach target range upper limit). Emphasize aerobic fat oxidation workouts (Zone 2 running, walk-run intervals) and maintain a modest calorie deficit while ensuring adequate protein intake.\n"
        else:
            msg += "- **Status**: Within target lower-healthy-range. Goal: Maintain current weight. Emphasize consistency in aerobic conditioning, balance training volume with caloric intake to avoid under-recovery.\n"
    else:
        msg += "- **Actual Current Weight**: Not available (awaiting Garmin scale sync or manual entry).\n"
        msg += "- **Status**: Pending current weight data. Maintain training routines focused on general aerobic base building.\n"

    msg += f"""
- **Age {age} Training & Weight Considerations**:
  - Focus on safe progression to avoid joint and tendon injury.
  - Sarcopenia prevention: Ensure training plan allows room for strength training and includes recovery intervals.
  - Weight loss must be gradual (max 0.5 kg or 1 lb per week) to preserve lean muscle mass.
"""
    return msg


async def run_analysis_from_config(config_path: Path | None, output_dir_override: Path | None = None) -> None:  # noqa: C901
    config_parser = ConfigParser(config_path)
    athlete_name, email = config_parser.get_athlete_info()
    analysis_context, planning_context = config_parser.get_contexts()
    extraction_settings = config_parser.get_extraction_config()

    competitions = config_parser.get_competitions()
    outside_competitions = fetch_outside_competitions_from_config(config_parser.config)
    if outside_competitions:
        competitions.extend(outside_competitions)

    output_dir = output_dir_override or config_parser.get_output_directory()

    password = config_parser.get_password()

    os.environ["AI_MODE"] = extraction_settings.get("ai_mode", "development")

    # Reload config and settings to pick up the new AI_MODE
    reload_config()
    ai_settings.reload()

    logger.info("AI Mode: %s", os.environ["AI_MODE"])

    try:
        logger.info("Extracting Garmin Connect data...")
        extractor = TriathlonCoachDataExtractor(email, password)

        # Dynamically fetch name from Garmin Connect profile
        fetched_name = None
        try:
            fetched_name = extractor.garmin.client.get_full_name() or extractor.garmin.client.display_name
        except Exception as e:
            logger.warning("Could not retrieve profile name from Garmin Connect: %s", e)
            try:
                fetched_name = extractor.garmin.client.display_name
            except Exception:
                pass

        if fetched_name and isinstance(fetched_name, str):
            clean_name = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in fetched_name).strip()
            clean_name = clean_name.replace(" ", "_")
            if clean_name:
                logger.info("Dynamically retrieved athlete name: %s", clean_name)
                athlete_name = clean_name

        # Sanitize final athlete name to be safe for directory names and ID usage
        athlete_name = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in athlete_name).strip()
        athlete_name = athlete_name.replace(" ", "_")

        # Update output directory to be user-specific
        output_dir = output_dir / athlete_name
        logger.info("Starting analysis for %s", athlete_name)
        logger.info("Output directory: %s", output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        extraction_config = ExtractionConfig(
            activities_range=extraction_settings["activities_days"],
            metrics_range=extraction_settings["metrics_days"],
            include_detailed_activities=True,
            include_metrics=True,
        )

        garmin_data = extractor.extract_data(extraction_config)
        logger.info("Data extraction completed")

        # Resolve golden height and weight sources of truth
        config_height = config_parser.get_athlete_height()
        config_weight = config_parser.get_athlete_weight()
        weight_goal = config_parser.get_weight_goal() or "maintain_lower_healthy_range"

        if garmin_data.user_profile is None:
            from services.garmin.models import UserProfile
            garmin_data.user_profile = UserProfile()

        # Height: golden source is garmin_data.user_profile.height
        resolved_height = None
        if garmin_data.user_profile.height and garmin_data.user_profile.height > 0:
            resolved_height = garmin_data.user_profile.height
            logger.info("Using Garmin Connect profile height: %.1f cm", resolved_height)
        elif config_height is not None:
            resolved_height = config_height
            logger.info("Using configured athlete height: %.1f cm", resolved_height)
        else:
            resolved_height = 175.26  # default 5'9"
            logger.info("Using default athlete height: %.1f cm (5'9\")", resolved_height)

        garmin_data.user_profile.height = resolved_height

        # Weight: golden source is Garmin scale metrics
        latest_weight = None
        if garmin_data.body_metrics and garmin_data.body_metrics.weight:
            weight_entries = garmin_data.body_metrics.weight.get("data", [])
            if weight_entries:
                # get the weight of the last entry (most recent)
                latest_weight = weight_entries[-1].get("weight")
            if not latest_weight:
                latest_weight = garmin_data.body_metrics.weight.get("average")

        resolved_weight = None
        if latest_weight is not None and latest_weight > 0:
            resolved_weight = latest_weight
            logger.info("Using Garmin scale weight: %.1f kg", resolved_weight)
        elif garmin_data.user_profile.weight and garmin_data.user_profile.weight > 0:
            resolved_weight = garmin_data.user_profile.weight
            logger.info("Using Garmin Connect profile weight: %.1f kg", resolved_weight)
        elif config_weight is not None:
            resolved_weight = config_weight
            logger.info("Using configured athlete weight: %.1f kg", resolved_weight)
        else:
            logger.info("Athlete weight is not available in Garmin Connect or config.")

        garmin_data.user_profile.weight = resolved_weight
        garmin_data.user_profile.weight_goal = weight_goal

        # Generate the scientific weight analysis context
        weight_context = get_weight_analysis_context(
            height_cm=resolved_height,
            weight_kg=resolved_weight,
            age=config_parser.get_athlete_age(),
            weight_goal=weight_goal
        )

        # -------------------------------------------------------------
        # Adaptive Running Coach Integration
        # -------------------------------------------------------------
        age = config_parser.get_athlete_age()
        goal = config_parser.get_target_goal()
        missed_runs = config_parser.get_missed_runs_count()
        accumulated_debt = config_parser.get_accumulated_debt_km()
        sync_calendar = config_parser.get_sync_calendar()

        zone2_min, zone2_max = config_parser.get_zone2_bounds()
        coach = AdaptiveRunningCoach(garmin_data, goal=goal, age=age, weight_goal=weight_goal, height=resolved_height, zone2_min=zone2_min, zone2_max=zone2_max)
        suggestion = coach.suggest_next_run(missed_runs_count=missed_runs, accumulated_debt_km=accumulated_debt)

        logger.info("Suggested Run distance: %s km", suggestion["distance_km"])
        logger.info("Suggested Run duration: %s min", suggestion["duration_min"])
        logger.info("Suggested Pace: %s", suggestion["target_pace_str"])
        logger.info("Suggested HR range: %s", suggestion["target_hr_range"])
        logger.info("Coach Notes: %s", suggestion["notes"])

        suggested_run_json = output_dir / "suggested_run.json"
        suggested_run_json.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
        logger.info("Saved suggested run JSON to %s", suggested_run_json)

        suggested_run_md = output_dir / "suggested_run.md"
        md_content = f"""# Suggested Next Run

**Focus**: {suggestion["focus"]}
- **Distance**: {suggestion["distance_km"]} km
- **Duration**: {suggestion["duration_min"]} minutes
- **Target Pace**: {suggestion["target_pace_str"]}
- **Target HR**: {suggestion["target_hr_range"]}
- **New Accumulated Debt**: {suggestion["new_accumulated_debt_km"]} km

## Coach Notes
{suggestion["notes"]}

## Structured Workout Segments
- **Warmup**: {suggestion["structured_segments"]["warmup_secs"] // 60} minutes walk/easy jog
- **Steady Run**: {suggestion["structured_segments"]["run_secs"] // 60} minutes at Zone 2 HR ({suggestion["structured_segments"]["target_hr_min"]}-{suggestion["structured_segments"]["target_hr_max"]} bpm)
- **Cooldown**: {suggestion["structured_segments"]["cooldown_secs"] // 60} minutes walk
"""
        suggested_run_md.write_text(md_content, encoding="utf-8")
        logger.info("Saved suggested run MD report to %s", suggested_run_md)

        if sync_calendar:
            logger.info("Calendar sync enabled — will sync suggested next run after analysis")

        now = datetime.now()
        plotting_enabled = extraction_settings.get("enable_plotting", False)
        hitl_enabled = extraction_settings.get("hitl_enabled", True)
        skip_synthesis = extraction_settings.get("skip_synthesis", False)

        logger.info("Plotting enabled: %s", plotting_enabled)
        logger.info("HITL enabled: %s", hitl_enabled)
        logger.info("Skip synthesis: %s", skip_synthesis)

        # Append persistent user feedback history to planning_context if available
        feedback_path = output_dir / "feedback_history.json"
        if feedback_path.exists():
            try:
                feedback_data = json.loads(feedback_path.read_text(encoding="utf-8"))
                if isinstance(feedback_data, list) and feedback_data:
                    logger.info("Found persistent user feedback history, appending to planning context")
                    lines = ["## Recent athlete feedback & coaching history:"]
                    for turn in feedback_data[-6:]:
                        role = "Athlete" if turn.get("role") == "user" else "Coach"
                        lines.append(f"- **{role}**: {turn.get('content')}")
                    planning_context = planning_context + "\n\n" + "\n".join(lines)
            except Exception as e:
                logger.warning("Could not load/append user feedback history: %s", e)

        current_date = {"date": now.strftime("%Y-%m-%d"), "day_name": now.strftime("%A")}
        week_dates = [
            {"date": (now + timedelta(days=offset)).strftime("%Y-%m-%d"),
             "day_name": (now + timedelta(days=offset)).strftime("%A")}
            for offset in range(14)
        ]

        logger.info("Running AI analysis and planning...")

        result = await run_complete_analysis_and_planning(
            user_id=athlete_name,
            athlete_name=athlete_name,
            garmin_data=asdict(garmin_data),
            analysis_context=analysis_context,
            planning_context=planning_context,
            weight_context=weight_context,
            competitions=competitions,
            current_date=current_date,
            week_dates=week_dates,
            plotting_enabled=plotting_enabled,
            hitl_enabled=hitl_enabled,
            skip_synthesis=skip_synthesis,
        )

        logger.info("Saving results...")

        files_generated: list[str] = []
        files_generated.extend(_save_html_outputs(output_dir, result))
        files_generated.extend(_save_expert_outputs(output_dir, result))
        files_generated.extend(_save_plan_outputs(output_dir, result))

        # -----------------------------------------------------------------
        # Garmin Calendar Sync: push the single suggested next workout to the watch
        # -----------------------------------------------------------------
        if sync_calendar:
            logger.info("Syncing suggested next run to Garmin calendar...")
            try:
                syncer = GarminCalendarSyncer(extractor.garmin)
                # Clear future workouts for the next 7 days to keep the calendar clean
                syncer._clear_future_scheduled_workouts(days_ahead=7)
                
                date_str = now.strftime("%Y-%m-%d")
                if suggestion["distance_km"] > 0:
                    workout_id = syncer.sync_workout_to_calendar(suggestion, date_str)
                    logger.info("✅ Successfully synced suggested run to Garmin calendar: %s (workout ID: %s)", date_str, workout_id)
                    # Save a record of what was synced
                    (output_dir / "calendar_sync.json").write_text(
                        json.dumps([
                            {
                                "date": date_str,
                                "name": suggestion["workout_name"],
                                "type": "run",
                                "duration_mins": round(suggestion["duration_min"]),
                            }
                        ], indent=2),
                        encoding="utf-8",
                    )
                    logger.info("Saved calendar_sync.json to %s", output_dir)
                else:
                    logger.info("Today is suggested as a Rest Day. Skipping workout upload.")
                    (output_dir / "calendar_sync.json").write_text(json.dumps([]), encoding="utf-8")
            except Exception:
                logger.exception("Calendar sync failed — analysis results are still saved")

        cost_total = float(
            result.get("cost_summary", {}).get("total_cost_usd", 0.0) or
            result.get("execution_metadata", {}).get("total_cost_usd", 0.0) or
            sum(cost.get("total_cost", 0) for cost in result.get("costs", []))
        )
        total_tokens = int(
            result.get("cost_summary", {}).get("total_tokens", 0) or
            result.get("execution_metadata", {}).get("total_tokens", 0)
        )

        (output_dir / "summary.json").write_text(
            json.dumps({
                "athlete": athlete_name,
                "analysis_date": datetime.now().isoformat(),
                "competitions": competitions,
                "total_cost_usd": cost_total,
                "total_tokens": total_tokens,
                "execution_id": result.get("execution_id", ""),
                "trace_id": result.get("execution_metadata", {}).get("trace_id", ""),
                "root_run_id": result.get("execution_metadata", {}).get("root_run_id", ""),
                "files_generated": files_generated,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        # Copy generated files to parent directory (root data dir) so that root URLs work
        import shutil
        for filename in [
            "suggested_run.json",
            "suggested_run.md",
            "analysis.html",
            "planning.html",
            "metrics_expert.json",
            "activity_expert.json",
            "physiology_expert.json",
            "season_plan.md",
            "weekly_plan.md",
            "calendar_sync.json",
            "summary.json"
        ]:
            src_file = output_dir / filename
            dst_file = output_dir.parent / filename
            if src_file.exists():
                try:
                    shutil.copy2(src_file, dst_file)
                    logger.info("Copied %s to root output directory %s", filename, dst_file)
                except Exception as e:
                    logger.warning("Failed to copy %s to root: %s", filename, e)

        # Copy the dashboard index.html if it exists in the root workspace
        root_index = Path("index.html")
        if root_index.exists():
            try:
                shutil.copy2(root_index, output_dir.parent / "index.html")
                logger.info("Copied dashboard index.html to root output directory")
            except Exception as e:
                logger.warning("Failed to copy dashboard index.html to root: %s", e)

        # Inject chat panel into planning.html (both user dir and root)
        try:
            from services.ai.langgraph.workflows.planning_workflow import _inject_chat_panel
            for plan_path in [output_dir / "planning.html", output_dir.parent / "planning.html"]:
                if plan_path.exists():
                    original = plan_path.read_text(encoding="utf-8")
                    injected = _inject_chat_panel(original)
                    if injected != original:
                        plan_path.write_text(injected, encoding="utf-8")
                        logger.info("Injected chat panel into %s", plan_path)
        except Exception as e:
            logger.warning("Could not inject chat panel: %s", e)

        logger.info("✅ Analysis completed successfully!")
        if outside_competitions:
            logger.info("✅  Added %d Outside competitions from config", len(outside_competitions))
        logger.info("📁 Results saved to: %s", output_dir)
        logger.info("💰 Total cost: $%.2f (%d tokens)", cost_total, total_tokens)
    except Exception as e:
        logger.error("❌ Analysis failed: %s", e)
        raise


def create_config_template(output_path: Path) -> None:
    template_path = Path(__file__).parent / "coach_config_template.yaml"

    if template_path.exists():
        output_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("✅ Config template created: %s", output_path)
        logger.info("Edit this file with your settings and run analysis with --config")
    else:
        logger.error("❌ Template file not found")


def main():
    parser = argparse.ArgumentParser(
        description="Garmin AI Coach CLI - AI Triathlon Coach",
        epilog="Example: python garmin_ai_coach_cli.py --config my_config.yaml",
    )

    parser.add_argument("--config", type=Path, help="Path to configuration file (YAML or JSON)")
    parser.add_argument("--init-config", type=Path, help="Create a configuration template file")
    parser.add_argument("--output-dir", type=Path, help="Override output directory from config")

    args = parser.parse_args()

    if args.init_config:
        create_config_template(args.init_config)
        return

    config_path = args.config
    if not config_path:
        default_config = Path("coach_config.yaml")
        if default_config.exists():
            config_path = default_config
            logger.info("Using default config file: %s", config_path)
        else:
            logger.info("No config file specified or found. Using environment variables.")

    try:
        asyncio.run(run_analysis_from_config(config_path, args.output_dir))
    except KeyboardInterrupt:
        logger.info("❌ Analysis cancelled by user")
    except Exception as e:
        logger.error("❌ Analysis failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
