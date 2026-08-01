#!/usr/bin/env python3
import logging
import os
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


def _sync_sleep_to_logseq(
    client,
    user_data_dir,
    sleep_data: dict,
    sleep_hours: float,
    pending_sync_path,
    today_iso: str,
) -> None:
    """Write sleep + weight to today's Logseq journal page.

    WOTD is intentionally NOT included — only actual completed runs
    (written by the daily run backfill) and sleep/weight appear in Logseq.
    If SSH is unavailable the props are queued to pending_logseq_syncs.json.
    """
    import datetime as _dt
    import json as _json

    daily_dto = sleep_data.get("dailySleepDTO") or {}

    # Bed time / wake time — prefer local timestamp, fall back to GMT
    def _garmin_ts_to_hhmm(local_key: str, gmt_key: str) -> str | None:
        val = daily_dto.get(local_key)
        if val:
            return str(val)
        gmt_ms = daily_dto.get(gmt_key)
        if gmt_ms:
            return _dt.datetime.fromtimestamp(int(gmt_ms) / 1000).strftime("%H:%M")
        return None

    bed_time = _garmin_ts_to_hhmm("sleepStartTimestampLocal", "sleepStartTimestampGMT")
    wake_time = _garmin_ts_to_hhmm("sleepEndTimestampLocal", "sleepEndTimestampGMT")
    sleep_quality = ((daily_dto.get("sleepScores") or {}).get("overall") or {}).get("value")

    # Weight — only log if changed by >= 1.0 lb since last logged
    weight_lbs = None
    last_weight_file = user_data_dir / "last_logged_weight.json"
    try:
        start_w = (_dt.date.today() - _dt.timedelta(days=14)).isoformat()
        body_data = (
            client.get_body_composition(start_w, today_iso)
            if hasattr(client, "get_body_composition")
            else (client.client.get_body_composition(start_w, today_iso) if hasattr(client, "client") else {})
        )
        weight_list = (body_data.get("dateWeightList") or []) if isinstance(body_data, dict) else []
        valid_w = [w for w in weight_list if w.get("weight") and float(w["weight"]) > 0]
        if valid_w:
            latest_w = sorted(valid_w, key=lambda x: (x.get("calendarDate", ""), x.get("samplePk", 0)))[-1]
            cur_lbs = round(float(latest_w["weight"]) / 453.59237, 1)
            last_logged_lbs = None
            if last_weight_file.exists():
                try:
                    last_logged_lbs = _json.loads(last_weight_file.read_text(encoding="utf-8")).get("weight_lbs")
                except Exception:
                    pass
            delta = round(cur_lbs - last_logged_lbs, 1) if last_logged_lbs is not None else None
            if last_logged_lbs is None or (delta is not None and abs(delta) >= 1.0):
                weight_lbs = cur_lbs
                direction = "initial log" if last_logged_lbs is None else f"delta: {'+' if delta > 0 else ''}{delta:.1f} lbs"
                logger.info("Logseq weight sync: logging %.1f lbs (%s)", cur_lbs, direction)
                last_weight_file.write_text(_json.dumps({
                    "weight_lbs": cur_lbs,
                    "logged_date": latest_w.get("calendarDate"),
                    "updated_at": _dt.datetime.now().isoformat(),
                }, indent=2), encoding="utf-8")
            else:
                logger.info(
                    "Logseq weight sync: %.1f lbs change below 1.0 lb threshold (last: %.1f lbs, delta: %+.1f) — skipping.",
                    cur_lbs, last_logged_lbs, delta,
                )
    except Exception as e:
        logger.warning("Logseq sync: could not fetch weight data: %s", e)

    props = build_props(
        sleep_duration_hours=sleep_hours,
        sleep_bed_time=bed_time,
        sleep_wake_time=wake_time,
        sleep_quality=sleep_quality,
        body_weight_lbs=weight_lbs,
        # ← wotd_* args intentionally omitted
    )

    if props:
        from datetime import date as _date
        synced = write_props_dict(props, date=_date.today())
        if synced:
            logger.info("Logseq: synced sleep+weight to journal for %s", today_iso)
        else:
            _queue_pending_sync(pending_sync_path, today_iso, props)
            logger.warning("Logseq: SSH unavailable — queued sleep+weight for %s", today_iso)
    else:
        logger.warning("Logseq: no sleep/weight properties built for %s (unexpected)", today_iso)

    # ── Yesterday's step count → yesterday's journal page ────────────────────
    # Garmin finalises the previous day's step total overnight. Sleep arriving
    # in the morning is our trigger to capture it and write it to the correct
    # past journal page so it never needs backfilling.
    try:
        yesterday = (_dt.date.today() - _dt.timedelta(days=1))
        yesterday_iso = yesterday.isoformat()
        stats = client.get_stats(yesterday_iso) or {}
        total_steps = stats.get("totalSteps") or stats.get("totalSteps", None)
        if total_steps and int(total_steps) > 0:
            step_props = build_props(body_steps=int(total_steps))
            if step_props:
                synced = write_props_dict(step_props, date=yesterday)
                if synced:
                    logger.info(
                        "Logseq: synced %d steps to journal for %s",
                        int(total_steps), yesterday_iso,
                    )
                else:
                    _queue_pending_sync(pending_sync_path, yesterday_iso, step_props)
                    logger.warning(
                        "Logseq: SSH unavailable — queued steps for %s", yesterday_iso,
                    )
        else:
            logger.info("Logseq: no step data available for %s", yesterday_iso)
    except Exception as e:
        logger.warning("Logseq: could not fetch/write steps for yesterday: %s", e)


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

    # ── Trigger 1: New completed run → lightweight post-run feedback ──────────────
    # Check if a new activity has been uploaded since the last poll.
    # Generates 3-4 sentences of coaching feedback via a single AI call.
    last_id_file = user_data_dir / "last_processed_activity_id.txt"
    last_processed_id = last_id_file.read_text(encoding="utf-8").strip() if last_id_file.exists() else ""

    try:
        latest_activities = client.get_activities(0, 1) or []
        if latest_activities:
            latest_activity = latest_activities[0]
            activity_id = str(latest_activity.get("activityId", ""))
            activity_type = (latest_activity.get("activityType") or {}).get("typeKey", "")
            is_run = "run" in activity_type.lower()

            if activity_id and activity_id != last_processed_id:
                # Mark processed immediately to prevent re-trigger on error
                last_id_file.write_text(activity_id, encoding="utf-8")
                if is_run:
                    logger.info(
                        "New run detected (id=%s) — generating post-run coaching feedback.",
                        activity_id,
                    )
                    try:
                        from services.garmin.run_coach_feedback import generate_run_feedback
                        generate_run_feedback(
                            client=client,
                            activity=latest_activity,
                            config=config,
                            user_data_dir=user_data_dir,
                        )
                    except Exception as fb_exc:
                        logger.error("Post-run feedback failed: %s", fb_exc, exc_info=True)

                    # Advance zone calibration counter (recalibration fires every 10 runs
                    # at the next WOTD generation via maybe_recalibrate in wotd_generator.py)
                    try:
                        from services.garmin.zone_calibrator import increment_run_counter
                        n = increment_run_counter(user_data_dir)
                        logger.info("ZoneCal: run counter advanced to %d/%d.", n, 10)
                    except Exception as cal_exc:
                        logger.warning("ZoneCal: could not advance run counter: %s", cal_exc)
                else:
                    logger.info(
                        "New non-run activity detected (id=%s, type=%s) — no feedback generated.",
                        activity_id, activity_type,
                    )
    except Exception as e:
        logger.warning("Could not check for new activities: %s", e)

    # ── Shared state paths (used by sleep-triggered block and run backfill) ───
    pending_sync_path = user_data_dir / "pending_logseq_syncs.json"

    # ── Sleep-triggered Workout of the Day ────────────────────────────────────
    # Check once per day whether last night's sleep data has arrived.
    # When it has, generate and push today's WOTD via AI (wotd_generator.py).
    last_sleep_file = user_data_dir / "last_processed_sleep_date.txt"
    today_iso = date.today().isoformat()
    last_sleep_date = ""
    if last_sleep_file.exists():
        last_sleep_date = last_sleep_file.read_text(encoding="utf-8").strip()

    if last_sleep_date != today_iso:
        logger.info("Checking Garmin Connect for last night's sleep data (%s)...", today_iso)
        try:
            sleep_data = client.get_sleep_data(today_iso) or {}
            daily_sleep = sleep_data.get("dailySleepDTO") or {}
            sleep_seconds = int(daily_sleep.get("sleepTimeSeconds") or 0)

            if sleep_seconds > 0:
                sleep_hours = round(sleep_seconds / 3600, 1)
                logger.info(
                    "Sleep data for %s received (%.1fh) — triggering WOTD + Logseq sleep sync.",
                    today_iso, sleep_hours,
                )

                # ① Mark as processed FIRST — prevents re-trigger if WOTD or Logseq errors
                last_sleep_file.write_text(today_iso, encoding="utf-8")

                # ② Generate and push WOTD to Garmin (never written to Logseq)
                try:
                    from services.garmin.wotd_generator import generate_workout_of_the_day
                    generate_workout_of_the_day(
                        client=client,
                        config=config,
                        user_data_dir=user_data_dir,
                        sleep_data=sleep_data,
                    )
                except Exception as wotd_exc:
                    logger.error("WOTD generation failed: %s", wotd_exc, exc_info=True)

                # ③ Write sleep + weight to Logseq (no WOTD props)
                _sync_sleep_to_logseq(
                    client=client,
                    user_data_dir=user_data_dir,
                    sleep_data=sleep_data,
                    sleep_hours=sleep_hours,
                    pending_sync_path=pending_sync_path,
                    today_iso=today_iso,
                )
            else:
                logger.info("Sleep data for %s not yet available. Will check again next poll.", today_iso)
        except Exception as e:
            logger.warning("Could not fetch sleep data for %s: %s", today_iso, e)
    else:
        logger.info("Sleep already processed for %s — WOTD skipped.", today_iso)

    # ── Daily run backfill + pending flush ───────────────────────────────────
    # Pending flush runs EVERY poll so queued items land as soon as Logseq opens.
    # Run backfill is once-per-day: writes last 15 completed runs to their correct
    # journal pages. Sleep/weight are handled by the sleep-triggered path above.
    run_backfill_file = user_data_dir / "last_run_backfill_date.txt"
    last_run_backfill = run_backfill_file.read_text(encoding="utf-8").strip() if run_backfill_file.exists() else ""

    # Always flush pending syncs (stops at first failure if Logseq still closed)
    _flush_pending_syncs(pending_sync_path)

    if last_run_backfill != today_iso:
        logger.info("Running daily run backfill to Logseq for %s...", today_iso)
        try:
            import datetime as _dt
            all_recent = client.get_activities(0, 15) or []
            today_date = _dt.date.today()
            for act in all_recent:
                type_key = (act.get("activityType") or {}).get("typeKey", "").lower()
                if type_key in ("running", "trail_running", "treadmill_running"):
                    st = act.get("startTimeLocal") or ""
                    if not st:
                        continue
                    act_date_str = st.split()[0]
                    try:
                        act_date = _dt.date.fromisoformat(act_date_str)
                    except ValueError:
                        continue

                    # Skip today and future dates — backfill is for past days only.
                    # This also filters out scheduled/planned WOTD calendar entries
                    # that appear in get_activities before the run is actually done.
                    if act_date >= today_date:
                        logger.debug(
                            "Logseq backfill: skipping activity on %s (today or future)",
                            act_date_str,
                        )
                        continue

                    # Require actual run metrics — planned workouts have distance
                    # but no averageSpeed, so this guards against writing WOTD data.
                    spd = act.get("averageSpeed")
                    if not spd or float(spd) <= 0:
                        logger.debug(
                            "Logseq backfill: skipping activity on %s — no averageSpeed (planned/incomplete?)",
                            act_date_str,
                        )
                        continue

                    dist = round(act.get("distance", 0) / 1000.0, 2) if act.get("distance") else None
                    hr = int(act.get("averageHR")) if act.get("averageHR") else None

                    run_props = build_props(
                        run_distance_km=dist,
                        run_avg_speed_ms=spd,
                        run_avg_heart_rate=hr,
                    )
                    if run_props:
                        synced = write_props_dict(run_props, date=act_date)
                        if synced:
                            logger.info("Logseq: synced actual run for %s (%s km)", act_date_str, dist)
                        else:
                            _queue_pending_sync(pending_sync_path, act_date_str, run_props)
            run_backfill_file.write_text(today_iso, encoding="utf-8")
        except Exception as e:
            logger.warning("Logseq run backfill failed: %s", e)
    else:
        logger.info("Logseq run backfill already done for %s. Skipping.", today_iso)
    # ── End Daily Run Backfill ────────────────────────────────────────────────


def run_withings_sync():
    """Push Withings scale measurements to Garmin Connect.

    Calls withings-sync programmatically (not as a CLI subprocess) so we can
    inject our already-authenticated ``garminconnect.Garmin`` client.  This
    avoids a fresh SSO login — which would trigger Garmin's MFA wall in a
    non-interactive container environment.

    The flow:
      1. Authenticate to Garmin using the existing tokenstore (same tokens the
         main daemon uses — no password / MFA required).
      2. Patch ``withings_sync.garmin.GarminConnect.login`` so that when
         ``withings_sync.sync.sync()`` creates a ``GarminConnect`` and calls
         ``.login()``, our hook injects the pre-authenticated client instead of
         performing a fresh SSO login.
      3. Patch ``sys.argv`` temporarily so ``withings_sync.sync.get_args()``
         sees the right config and garmin-username arguments.
      4. Call ``sync()`` and restore all patches.
    """
    logger.info("Starting Withings-Garmin sync...")
    try:
        garmin_email = os.getenv("GARMIN_EMAIL", "")
        tokens_dir = os.getenv("GARMINCONNECT_TOKENS", "/app/tokens")

        if not garmin_email:
            logger.warning("GARMIN_EMAIL not set — skipping Withings-Garmin sync.")
            return

        # ── Step 1: authenticate to Garmin via the existing tokenstore ────────
        sanitized = garmin_email.replace("@", "_").replace(".", "_")
        user_tokens_dir = os.path.join(tokens_dir, sanitized)

        from garminconnect import Garmin as GarminClient
        gc_client = GarminClient(email=garmin_email, password="", prompt_mfa=None)
        gc_client.login(tokenstore=user_tokens_dir)
        logger.info("Garmin tokenstore login successful (no MFA required).")

        # ── Step 2: import withings_sync modules ──────────────────────────────
        import sys as _sys
        import withings_sync.sync as _ws_sync
        from withings_sync.garmin import GarminConnect as WGarminConnect

        # ── Step 3: patch sys.argv so get_args() sees our config ──────────────
        # Keep -c /app/tokens so withings-sync finds the Withings OAuth token at
        # /app/tokens/.withings_user.json (original config location).
        # garmin_username is set so the Garmin upload branch is entered.
        # The actual password is irrelevant — we intercept login() before it runs.
        _orig_argv = _sys.argv[:]
        _sys.argv = [
            "withings-sync",
            "-c", tokens_dir,           # keeps Withings token accessible
            "--garmin-username", garmin_email,
            "--garmin-password", "UNUSED_PLACEHOLDER",  # never used — we inject client
        ]
        try:
            _ws_sync.ARGS = _ws_sync.get_args()
        finally:
            _sys.argv = _orig_argv

        # ── Step 4: patch GarminConnect.login to inject pre-auth client ───────
        # Inside sync(), withings-sync does:
        #   garmin = GarminConnect(config_folder=...)
        #   garmin.login(username, password)   ← this would trigger MFA
        # We replace login() with a shim that injects our gc_client instead.
        _orig_login = WGarminConnect.login

        def _login_shim(self, email=None, password=None):
            self.client = gc_client  # inject pre-authenticated garminconnect client
            logger.info("withings-sync: using pre-authenticated Garmin client (no MFA).")

        WGarminConnect.login = _login_shim

        try:
            _ws_sync.sync()
            logger.info("Withings-Garmin sync completed successfully!")
        finally:
            WGarminConnect.login = _orig_login  # always restore



    except Exception as exc:
        logger.error("Withings-Garmin sync failed: %s", exc, exc_info=True)




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
