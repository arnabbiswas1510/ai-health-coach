#!/usr/bin/env python3
import logging
import os
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from garminconnect import Garmin

from services.logseq import write_daily_properties

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daemon")

def check_and_run():  # noqa: C901
    project_dir = Path(__file__).parent.resolve()
    config_path = project_dir / "coach_config.yaml"
    tokens_dir = project_dir / "tokens"
    data_dir = project_dir / "data"

    # 1. Parse athlete email from environment variable or config
    email = os.getenv("GARMIN_EMAIL")
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Could not load config at %s: %s", config_path, e)

    if not email:
        email = config.get("athlete", {}).get("email")

    if not email:
        logger.error("Athlete email is missing. Please set GARMIN_EMAIL env var or provide coach_config.yaml")
        return

    # 2. Login to Garmin Connect (utilizing cached tokens)
    logger.info("Checking Garmin Connect for updates...")
    sanitized_email = email.replace("@", "_").replace(".", "_")
    user_tokens_dir = tokens_dir / sanitized_email
    user_tokens_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Login via tokenstore without password (requires one initial login with password)
        client = Garmin(email=email, password="", prompt_mfa=None)
        client.login(tokenstore=str(user_tokens_dir))
    except Exception as e:
        logger.error("Failed to log in using cached tokens: %s", e)
        logger.error("Please run the coach container once interactively to log in/refresh tokens.")
        return

    # Retrieve latest athlete name dynamically from Garmin Connect profile
    display_name = None
    try:
        display_name = client.get_full_name() or client.display_name
    except Exception as e:
        logger.warning("Could not retrieve profile name from Garmin Connect: %s", e)
        try:
            display_name = client.display_name
        except Exception:
            pass

    if display_name and isinstance(display_name, str):
        display_name = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in display_name).strip()
        display_name = display_name.replace(" ", "_")
    else:
        display_name = None

    if not display_name:
        display_name = os.getenv("ATHLETE_NAME") or config.get("athlete", {}).get("name", "Athlete")

    user_data_dir = data_dir / display_name
    user_data_dir.mkdir(parents=True, exist_ok=True)
    last_id_file = user_data_dir / "last_processed_id.txt"

    # 3. Retrieve latest activity
    try:
        activities = client.get_activities(0, 1)
    except Exception as e:
        logger.error("Failed to fetch activities: %s", e)
        return

    if not activities:
        logger.info("No activities found on your account.")
        return

    latest_activity = activities[0]
    activity_id = str(latest_activity.get("activityId"))
    activity_name = latest_activity.get("activityName", "Activity")
    start_time = latest_activity.get("startTimeLocal", "")

    logger.info("Latest activity: ID=%s (%s, start=%s)", activity_id, activity_name, start_time)

    # 4. Compare with last processed ID
    last_processed_id = ""
    if last_id_file.exists():
        last_processed_id = last_id_file.read_text(encoding="utf-8").strip()

    should_run = False
    run_reason = ""

    if activity_id != last_processed_id:
        # Trigger 1: new workout uploaded
        should_run = True
        run_reason = f"New activity detected (ID: {activity_id} != {last_processed_id})"

    if not should_run:
        # Trigger 2: new overnight sleep data available
        # Garmin uploads sleep data in the morning after you sync your watch.
        # We check once per day whether yesterday's sleep record has arrived.
        last_sleep_file = user_data_dir / "last_processed_sleep_date.txt"
        yesterday = (date.today().toordinal() - 1)
        yesterday_iso = date.fromordinal(yesterday).isoformat()
        last_sleep_date = ""
        if last_sleep_file.exists():
            last_sleep_date = last_sleep_file.read_text(encoding="utf-8").strip()

        if last_sleep_date != yesterday_iso:
            logger.info("Checking Garmin Connect for last night's sleep data (%s)...", yesterday_iso)
            try:
                sleep_data = client.get_sleep_data(yesterday_iso) or {}
                daily_sleep = (sleep_data.get("dailySleepDTO") or {})
                sleep_seconds = daily_sleep.get("sleepTimeSeconds") or 0
                if sleep_seconds and int(sleep_seconds) > 0:
                    sleep_hours = round(int(sleep_seconds) / 3600, 1)
                    should_run = True
                    run_reason = (
                        f"New sleep data for {yesterday_iso} received "
                        f"({sleep_hours}h) — re-calculating next workout based on recovery"
                    )
                    # Mark this date as processed regardless of pipeline outcome
                    # (prevents repeated triggers on the same day's sleep)
                    last_sleep_file.write_text(yesterday_iso, encoding="utf-8")
                else:
                    logger.info("Sleep data for %s not yet available. Will check again next poll.", yesterday_iso)
            except Exception as e:
                logger.warning("Could not fetch sleep data for %s: %s", yesterday_iso, e)

    if not should_run:
        logger.info("No new runs or sleep data detected for %s. Plan is up to date.", display_name)

    # ── Daily Logseq Sync ─────────────────────────────────────────────────────
    # Runs once per day regardless of whether the full pipeline triggered.
    # Reads yesterday's sleep from Garmin + today's suggested_run.json.
    logseq_sync_file = user_data_dir / "last_logseq_sync_date.txt"
    today_iso = date.today().isoformat()
    last_logseq_date = logseq_sync_file.read_text(encoding="utf-8").strip() if logseq_sync_file.exists() else ""

    if last_logseq_date != today_iso:
        logger.info("Running daily Logseq journal sync for %s...", today_iso)
        try:
            import json

            # Sleep fields — from yesterday's Garmin sleep data (already fetched above)
            _sleep_hours   = None
            _bed_time      = None
            _wake_time     = None
            _sleep_quality = None
            try:
                sleep_raw  = client.get_sleep_data(yesterday_iso) or {}
                daily_dto  = sleep_raw.get("dailySleepDTO") or {}
                secs       = daily_dto.get("sleepTimeSeconds") or 0
                if secs:
                    _sleep_hours = round(int(secs) / 3600, 2)
                # bed / wake times stored as epoch ms in sleepStartTimestampGMT / sleepEndTimestampGMT
                # but Garmin also exposes them as local HH:MM strings in the DTO
                _bed_time  = daily_dto.get("sleepStartTimestampLocal")  # may be None
                _wake_time = daily_dto.get("sleepEndTimestampLocal")    # may be None
                # Fallback: parse from epoch ms
                if not _bed_time:
                    gmt_ms = daily_dto.get("sleepStartTimestampGMT")
                    if gmt_ms:
                        import datetime as _dt
                        _bed_time = _dt.datetime.fromtimestamp(int(gmt_ms) / 1000).strftime("%H:%M")
                if not _wake_time:
                    gmt_ms = daily_dto.get("sleepEndTimestampGMT")
                    if gmt_ms:
                        import datetime as _dt
                        _wake_time = _dt.datetime.fromtimestamp(int(gmt_ms) / 1000).strftime("%H:%M")
                scores = daily_dto.get("sleepScores") or {}
                overall = scores.get("overall") or {}
                _sleep_quality = overall.get("value")
            except Exception as e:
                logger.warning("Logseq sync: could not fetch sleep data: %s", e)

            # Run fields — from persisted suggested_run.json
            _run_distance = None
            _run_speed_ms = None
            _run_avg_hr   = None
            suggested_run_path = user_data_dir / "suggested_run.json"
            if suggested_run_path.exists():
                try:
                    sr = json.loads(suggested_run_path.read_text(encoding="utf-8"))
                    _run_distance = sr.get("distance_km")
                    # suggested_run stores pace as min/km string; convert to m/s for the client
                    pace_str = sr.get("target_pace_str", "")  # e.g. "5:45"
                    if pace_str and ":" in pace_str:
                        parts = pace_str.split(":")
                        pace_sec = int(parts[0]) * 60 + int(parts[1])
                        if pace_sec > 0:
                            _run_speed_ms = 1000.0 / pace_sec  # m/s
                except Exception as e:
                    logger.warning("Logseq sync: could not read suggested_run.json: %s", e)

            synced = write_daily_properties(
                sleep_duration_hours=_sleep_hours,
                sleep_bed_time=_bed_time,
                sleep_wake_time=_wake_time,
                sleep_quality=_sleep_quality,
                run_distance_km=_run_distance,
                run_avg_speed_ms=_run_speed_ms,
                run_avg_heart_rate=_run_avg_hr,
            )
            if synced:
                logseq_sync_file.write_text(today_iso, encoding="utf-8")
                logger.info("Logseq journal sync complete for %s.", today_iso)
            else:
                logger.warning("Logseq journal sync wrote 0 properties — Logseq may not be running.")
        except Exception as e:
            logger.exception("Logseq journal sync failed — daemon continues: %s", e)
    else:
        logger.info("Logseq journal already synced today (%s). Skipping.", today_iso)
    # ── End Daily Logseq Sync ─────────────────────────────────────────────────

    if not should_run:
        return

    # 5. Trigger detected — run the CLI analysis
    logger.info("%s: %s", display_name, run_reason)
    logger.info("Running coach analysis workflow...")

    # Run the python CLI script directly inside the container
    cmd = ["python", "cli/garmin_ai_coach_cli.py"]
    if config_path.exists():
        cmd.extend(["--config", str(config_path)])

    try:
        res = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True, check=False)
        if res.returncode == 0:
            logger.info("Coach analysis completed successfully!")
            # Update the activity sentinel so we don't re-trigger on the same activity
            last_id_file.write_text(activity_id, encoding="utf-8")
            logger.info("Updated last processed ID to %s", activity_id)
        else:
            logger.error("Coach analysis execution failed:")
            logger.error(res.stderr)
    except Exception as e:
        logger.error("Failed to run coach command: %s", e)

def main():
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
    logger.info("Garmin AI Coach daemon started. Polling interval: %s seconds.", poll_interval)

    # Run once immediately on start
    try:
        check_and_run()
    except Exception as e:
        logger.exception("Unhandled error in check_and_run: %s", e)

    # Enter loop
    while True:
        try:
            time.sleep(poll_interval)
            check_and_run()
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user.")
            break
        except Exception as e:
            logger.exception("Unhandled error in daemon loop: %s", e)

if __name__ == "__main__":
    main()
