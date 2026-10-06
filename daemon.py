#!/usr/bin/env python3
import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from garminconnect import Garmin

from services.logseq import (
    build_props,
    flush_pending_syncs,
    load_pending_syncs,
    queue_pending_sync,
    save_pending_syncs,
    write_props_dict,
)

# Aliases for backward compatibility within daemon.py
_load_pending_syncs = load_pending_syncs
_save_pending_syncs = save_pending_syncs
_queue_pending_sync = queue_pending_sync
_flush_pending_syncs = flush_pending_syncs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daemon")




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
            dur = float(latest_activity.get("duration") or latest_activity.get("movingDuration") or 0)
            dist = float(latest_activity.get("distance") or 0)
            spd = float(latest_activity.get("averageSpeed") or 0)
            is_completed_run = is_run and dur >= 60.0 and dist >= 500.0 and spd > 0.0

            if activity_id and activity_id != last_processed_id:
                # Mark processed immediately to prevent re-trigger on error
                last_id_file.write_text(activity_id, encoding="utf-8")
                if is_completed_run:
                    logger.info(
                        "New completed run detected (id=%s, dist=%.2f km, dur=%.1f min) — generating post-run coaching feedback.",
                        activity_id, dist / 1000.0, dur / 60.0,
                    )
                    # Marker consumed by services.feedback.detect_timing() so a
                    # note written later today is tagged as a post-run report
                    # rather than a pre-workout heads-up.
                    try:
                        start_local = str(latest_activity.get("startTimeLocal") or "")
                        run_date = start_local[:10] or date.today().isoformat()
                        (user_data_dir / "last_run.json").write_text(
                            json.dumps(
                                {
                                    "activity_id": activity_id,
                                    "date": run_date,
                                    "start_time_local": start_local,
                                    "activity_type": activity_type,
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    except Exception as marker_exc:
                        logger.warning("Could not write last_run.json marker: %s", marker_exc)

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
                elif is_run:
                    logger.info(
                        "Run activity detected (id=%s) but not completed (dist=%.2f km, dur=%.1f s, spd=%.2f m/s) — skipping feedback.",
                        activity_id, dist / 1000.0, dur, spd,
                    )
                else:
                    logger.info(
                        "New non-run activity detected (id=%s, type=%s) — no feedback generated.",
                        activity_id, activity_type,
                    )
    except Exception as e:
        logger.warning("Could not check for new activities: %s", e)

    # ── Shared state paths (used by sleep-triggered block and run backfill) ───
    pending_sync_path = user_data_dir / "pending_logseq_syncs.json"

    # ── Time-Gated & Sleep-Triggered Workout of the Day (WOTD) ────────────────
    # Rules:
    # 1. If today's sleep data arrives early (< 06:20 AM), generate and push WOTD immediately.
    # 2. If at or after 06:20 AM and today's WOTD hasn't been pushed yet, force WOTD generation.
    #    If today's sleep metrics are still missing, use yesterday's sleep data as fallback.
    # 3. Only mark last_pushed_wotd_date.txt AFTER WOTD is successfully generated and pushed.
    from datetime import datetime as _dt_cls
    from datetime import time as _time_cls
    from datetime import timedelta as _td_cls

    last_sleep_file = user_data_dir / "last_processed_sleep_date.txt"
    last_wotd_file = user_data_dir / "last_pushed_wotd_date.txt"

    now_dt = _dt_cls.now().astimezone()
    today_iso = now_dt.date().isoformat()
    yesterday_iso = (now_dt.date() - _td_cls(days=1)).isoformat()

    last_sleep_date = last_sleep_file.read_text(encoding="utf-8").strip() if last_sleep_file.exists() else ""
    last_wotd_date = last_wotd_file.read_text(encoding="utf-8").strip() if last_wotd_file.exists() else ""

    now_time = now_dt.time()
    cutoff_time = _time_cls(6, 20)  # 06:20 AM cutoff

    sleep_data = {}
    sleep_seconds = 0

    try:
        sleep_data = client.get_sleep_data(today_iso) or {}
        daily_sleep = sleep_data.get("dailySleepDTO") or {}
        sleep_seconds = int(daily_sleep.get("sleepTimeSeconds") or 0)
    except Exception as e:
        logger.warning("Could not fetch sleep data for %s: %s", today_iso, e)

    # Logseq sleep sync (handled independently when sleep data is ready)
    if sleep_seconds > 0 and last_sleep_date != today_iso:
        sleep_hours = round(sleep_seconds / 3600, 1)
        last_sleep_file.write_text(today_iso, encoding="utf-8")
        _sync_sleep_to_logseq(
            client=client,
            user_data_dir=user_data_dir,
            sleep_data=sleep_data,
            sleep_hours=sleep_hours,
            pending_sync_path=pending_sync_path,
            today_iso=today_iso,
        )

    # WOTD Generation & Push logic
    if last_wotd_date != today_iso:
        should_generate = False
        fallback_sleep_data = None

        if sleep_seconds > 0:
            logger.info("Sleep data for %s ready (%.1fh) — generating WOTD.", today_iso, round(sleep_seconds / 3600, 1))
            should_generate = True
        elif now_time >= cutoff_time:
            logger.info(
                "Time cutoff reached (%s >= 06:20 AM) without today's sleep data — forcing WOTD generation using fallback data.",
                now_time.strftime("%H:%M"),
            )
            should_generate = True
            try:
                fallback_sleep_data = client.get_sleep_data(yesterday_iso) or {}
            except Exception as fb_err:
                logger.warning("Could not fetch yesterday's sleep data (%s) for fallback: %s", yesterday_iso, fb_err)
        else:
            logger.info(
                "Sleep data for %s not yet available and before cutoff (%s < 06:20 AM). Will check again next poll.",
                today_iso, now_time.strftime("%H:%M"),
            )

        if should_generate:
            try:
                from services.garmin.wotd_generator import generate_workout_of_the_day
                generate_workout_of_the_day(
                    client=client,
                    config=config,
                    user_data_dir=user_data_dir,
                    sleep_data=sleep_data,
                    fallback_sleep_data=fallback_sleep_data,
                )
                last_wotd_file.write_text(today_iso, encoding="utf-8")
                logger.info("WOTD: successfully pushed and recorded for %s.", today_iso)
            except Exception as wotd_exc:
                logger.error("WOTD generation/push failed for %s (will retry next poll): %s", today_iso, wotd_exc, exc_info=True)
    else:
        logger.info("WOTD already pushed for %s — skipping.", today_iso)

    # ── Daily run check + pending flush ──────────────────────────────────────
    # Pending flush runs EVERY poll so queued coach feedback / sleep lands as soon
    # as Logseq is open. Completed runs receive only coach feedback in Logseq.
    run_backfill_file = user_data_dir / "last_run_backfill_date.txt"
    last_run_backfill = run_backfill_file.read_text(encoding="utf-8").strip() if run_backfill_file.exists() else ""

    # Always flush pending syncs (stops at first failure if Logseq still closed)
    _flush_pending_syncs(pending_sync_path)

    if last_run_backfill != today_iso:
        logger.info(
            "Daily run check for %s: Logseq receives coach feedback on completed runs (raw metrics/suggestions omitted).",
            today_iso,
        )
        run_backfill_file.write_text(today_iso, encoding="utf-8")
    else:
        logger.debug("Daily run check already done for %s. Skipping.", today_iso)
    # ── End Daily Run Check ───────────────────────────────────────────────────


def _withings_sync_due(today: date | None = None) -> bool:
    """Return True when the Withings sync should run, and record the attempt.

    Withings issues a new refresh token on every refresh and withings-sync
    refreshes unconditionally, so an hourly poll rotates the credential ~24
    times a day. Scale measurements arrive a few times a day at most, so that
    churn buys nothing -- and it makes any external mirror of the credential
    expensive to keep current. Gate on a date marker so the token rotates
    roughly once a day.

    The marker is written on every *attempt*, not on success, so a persistently
    failing sync cannot spin once an hour.
    """
    tokens_dir = os.getenv("GARMINCONNECT_TOKENS", "/app/tokens")
    marker = Path(tokens_dir) / ".withings_last_sync"
    stamp = (today or date.today()).isoformat()

    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == stamp:
            return False
    except OSError:
        pass  # an unreadable marker just means we try again

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(stamp, encoding="utf-8")
    except OSError as exc:
        # Without a marker we would retry hourly; log it rather than silently
        # reverting to the old behaviour.
        logger.warning("Could not record Withings sync marker at %s: %s", marker, exc)

    return True


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

        # Withings rotates the refresh token on every sync, so running this
        # hourly burns credentials for no benefit -- scale measurements appear
        # at most a few times a day. Gate it so the token rotates about once a
        # day, which also keeps the Bitwarden mirror cheap.
        if not _withings_sync_due():
            logger.debug("Withings-Garmin sync already ran today — skipping.")
            return

        # A missing credential is recoverable without operator interaction if
        # Bitwarden holds a copy (see services/withings/credential_store.py).
        from services.withings import credential_store

        credential_store.seed_from_vault(tokens_dir)

        # withings-sync keeps its OAuth credential at <config>/.withings_user.json.
        # When that file is absent it falls back to prompting for the token on
        # stdin, which in a detached container raises EOFError and dumps a full
        # traceback on every poll. Check first so the operator gets one
        # actionable line instead, and so we skip the Garmin login we cannot use.
        withings_token = os.path.join(tokens_dir, ".withings_user.json")
        if not os.path.exists(withings_token):
            logger.warning(
                "Withings OAuth token not found at %s — skipping Withings-Garmin sync. "
                "Authorize once (interactively, on the host) to create it: "
                "docker compose run --rm "
                "--entrypoint 'withings-sync -c /app/tokens' ai-health-coach",
                withings_token,
            )
            return

        # A credential for the wrong family profile would upload someone else's
        # weight into this athlete's Garmin history, which Garmin offers no
        # clean way to undo. Refuse before the upload, not after.
        mismatch = credential_store.userid_mismatch(tokens_dir)
        if mismatch:
            logger.error("Aborting Withings-Garmin sync: %s", mismatch)
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
            # The sync just rotated the refresh token. Mirror it immediately:
            # a snapshot taken later would hold a superseded credential.
            credential_store.push_to_vault(tokens_dir)
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
