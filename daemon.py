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

from services.logseq import build_props, write_props_dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daemon")


# ── Pending Logseq sync queue ─────────────────────────────────────────────────
# When Logseq is closed (e.g. on vacation) the write fails silently.
# We persist the formatted props + target date in a JSON file so they can be
# replayed to the correct past journal pages once Logseq is open again.

def _load_pending_syncs(path: Path) -> list[dict]:
    """Return the list of pending sync entries, or [] if none."""
    if not path.exists():
        return []
    try:
        import json as _json
        return _json.loads(path.read_text(encoding="utf-8")) or []
    except Exception as exc:
        logger.warning("Could not read pending sync queue %s: %s", path, exc)
        return []


def _save_pending_syncs(path: Path, entries: list[dict]) -> None:
    import json as _json
    try:
        path.write_text(_json.dumps(entries, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save pending sync queue %s: %s", path, exc)


def _queue_pending_sync(
    path: Path,
    date_iso: str,
    props: dict,
) -> None:
    """Add or update a pending sync entry for date_iso (deduplicates by date)."""
    entries = _load_pending_syncs(path)
    # Replace existing entry for the same date, or append
    existing = {e["date"]: i for i, e in enumerate(entries)}
    entry = {"date": date_iso, "properties": props}
    if date_iso in existing:
        entries[existing[date_iso]] = entry
    else:
        entries.append(entry)
    _save_pending_syncs(path, entries)
    logger.info(
        "Logseq: queued sync for %s (%d properties) — will retry when Logseq is open.",
        date_iso, len(props),
    )


def _flush_pending_syncs(path: Path) -> int:
    """Try to write all pending syncs to their correct journal pages.

    Processes entries oldest-first. Stops on the first failure (if Logseq is
    still closed, no point attempting the rest). Removes successful entries.
    Returns the number of entries still pending.
    """
    entries = _load_pending_syncs(path)
    if not entries:
        return 0

    logger.info("Logseq: attempting to flush %d pending sync(s)...", len(entries))
    still_pending: list[dict] = []
    logseq_reachable = True

    for entry in sorted(entries, key=lambda e: e["date"]):
        if not logseq_reachable:
            still_pending.append(entry)
            continue

        target_date = date.fromisoformat(entry["date"])
        ok = write_props_dict(entry["properties"], date=target_date)
        if ok:
            logger.info("Logseq: flushed pending sync for %s.", entry["date"])
        else:
            logger.warning(
                "Logseq: could not flush pending sync for %s — Logseq still unavailable.",
                entry["date"],
            )
            still_pending.append(entry)
            logseq_reachable = False  # stop trying further entries

    _save_pending_syncs(path, still_pending)
    flushed = len(entries) - len(still_pending)
    if flushed:
        logger.info("Logseq: flushed %d pending sync(s), %d still queued.", flushed, len(still_pending))
    return len(still_pending)

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
        today_iso = date.today().isoformat()
        last_sleep_date = ""
        if last_sleep_file.exists():
            last_sleep_date = last_sleep_file.read_text(encoding="utf-8").strip()

        if last_sleep_date != today_iso:
            logger.info("Checking Garmin Connect for last night's sleep data (%s)...", today_iso)
            try:
                sleep_data = client.get_sleep_data(today_iso) or {}
                daily_sleep = (sleep_data.get("dailySleepDTO") or {})
                sleep_seconds = daily_sleep.get("sleepTimeSeconds") or 0
                if sleep_seconds and int(sleep_seconds) > 0:
                    sleep_hours = round(int(sleep_seconds) / 3600, 1)
                    should_run = True
                    run_reason = (
                        f"New sleep data for {today_iso} received "
                        f"({sleep_hours}h) — re-calculating next workout based on recovery"
                    )
                    # Mark this date as processed regardless of pipeline outcome
                    # (prevents repeated triggers on the same day's sleep)
                    last_sleep_file.write_text(today_iso, encoding="utf-8")
                else:
                    logger.info("Sleep data for %s not yet available. Will check again next poll.", today_iso)
            except Exception as e:
                logger.warning("Could not fetch sleep data for %s: %s", today_iso, e)

    if not should_run:
        logger.info("No new runs or sleep data detected for %s. Plan is up to date.", display_name)

    # ── Daily Logseq Sync ─────────────────────────────────────────────────────
    # Runs once per day regardless of whether the full pipeline triggered.
    # Reads yesterday's sleep from Garmin + today's suggested_run.json.
    #
    # If Logseq is closed (e.g. vacation), the formatted props + target date are
    # saved to pending_logseq_syncs.json and replayed to the CORRECT past journal
    # page once Logseq comes back online.
    logseq_sync_file   = user_data_dir / "last_logseq_sync_date.txt"
    pending_sync_path  = user_data_dir / "pending_logseq_syncs.json"
    today_iso          = date.today().isoformat()
    last_logseq_date   = logseq_sync_file.read_text(encoding="utf-8").strip() if logseq_sync_file.exists() else ""

    # 1. Flush any pending syncs from previous days when Logseq was closed.
    #    Stops immediately if Logseq is still unreachable.
    _flush_pending_syncs(pending_sync_path)

    # 2. Run today's sync if not already done.
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
                sleep_raw  = client.get_sleep_data(today_iso) or {}
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
                    # target_pace_str is e.g. "6:01 /km" — strip any suffix after MM:SS
                    pace_str = sr.get("target_pace_str", "")
                    import re as _re
                    m = _re.match(r"(\d+):(\d+)", pace_str)
                    if m:
                        pace_sec = int(m.group(1)) * 60 + int(m.group(2))
                        if pace_sec > 0:
                            _run_speed_ms = 1000.0 / pace_sec  # m/s
                except Exception as e:
                    logger.warning("Logseq sync: could not read suggested_run.json: %s", e)

            # Build the formatted props dict BEFORE the write attempt so we can
            # persist it to the pending queue if Logseq happens to be closed.
            props_today = build_props(
                sleep_duration_hours=_sleep_hours,
                sleep_bed_time=_bed_time,
                sleep_wake_time=_wake_time,
                sleep_quality=_sleep_quality,
                run_distance_km=_run_distance,
                run_avg_speed_ms=_run_speed_ms,
                run_avg_heart_rate=_run_avg_hr,
            )

            if not props_today:
                logger.info("Logseq sync: no properties to write for %s.", today_iso)
            else:
                synced = write_props_dict(props_today, date=date.today())
                if synced:
                    logseq_sync_file.write_text(today_iso, encoding="utf-8")
                    logger.info("Logseq journal sync complete for %s.", today_iso)
                else:
                    # Logseq is closed — queue so it writes to the RIGHT date later.
                    _queue_pending_sync(pending_sync_path, today_iso, props_today)

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

def run_withings_sync():
    """Runs withings-sync command-line tool to push scale measurements to Garmin."""
    logger.info("Starting Withings-Garmin sync...")
    try:
        # withings-sync config folder is /app/tokens
        cmd = ["withings-sync", "-c", "/app/tokens"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            logger.info("Withings-Garmin sync completed successfully!")
            if res.stdout:
                logger.info(res.stdout)
        else:
            logger.error("Withings-Garmin sync execution failed:")
            if res.stderr:
                logger.error(res.stderr)
    except Exception as exc:
        logger.error("Failed to run withings-sync command: %s", exc)


def main():
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
    logger.info("Garmin AI Coach daemon started. Polling interval: %s seconds.", poll_interval)

    # Run once immediately on start
    try:
        run_withings_sync()
        check_and_run()
    except Exception as e:
        logger.exception("Unhandled error in check_and_run: %s", e)

    # Enter loop
    while True:
        try:
            time.sleep(poll_interval)
            run_withings_sync()
            check_and_run()
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user.")
            break
        except Exception as e:
            logger.exception("Unhandled error in daemon loop: %s", e)

if __name__ == "__main__":
    main()
