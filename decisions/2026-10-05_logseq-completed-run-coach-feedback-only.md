# Logseq Completed Run Coach Feedback Only

**Date:** 2026-10-05  
**Status:** Accepted  

## Context

The user observed that run suggestions and raw run metrics (`run: distance:: ...`, `run: avg-speed:: ...`) were appearing on their Logseq daily journal pages, including days where they did not run. Furthermore, historical Logseq entries from earlier revisions showed coach feedback citing incorrect age-based heart rate ranges (100–120 bpm from `220 - age`) rather than the athlete's actual Garmin-calculated heart rate zones (LTHR-anchored Zone 2: 132–154 bpm, walk-break trigger ≥ 155 bpm).

### Root Causes Identified

1. **CLI startup write on `date.today()`:**
   In `cli/garmin_ai_coach_cli.py`, every time the CLI executed (including container restarts), it traversed `garmin_data.recent_activities` without verifying the activity date. It extracted `_run_distance`, `_run_speed_ms`, and `_run_avg_hr` from the most recent run and called `write_daily_properties(..., date=None)`, which defaulted to `date.today()`. Immediately afterward, the CLI generated a run suggestion (`coach.suggest_next_run()`). On rest days, today's Logseq journal received this uncompleted run block, which appeared as a suggested run written to Logseq.

2. **Daily run backfill in `daemon.py`:**
   In `daemon.py`, the daily backfill routine scanned the last 15 activities and constructed `run_props = build_props(run_distance_km=dist, run_avg_speed_ms=spd, run_avg_heart_rate=hr)`, writing raw `run:` blocks to past journals rather than coach feedback.

3. **Missing queueing & date misalignment in `run_coach_feedback.py`:**
   `run_coach_feedback.py` was hard-coded to `date.today()` rather than the actual activity date (`startTimeLocal`). When Logseq SSH direct-write was offline or unreachable, the feedback was dropped instead of being queued in `pending_logseq_syncs.json`.

4. **Biometric LTHR resolution robustness:**
   `services/garmin/hr_zones.py` previously queried only `get_user_profile()` and `get_training_status()`. While `220 - age` was forbidden, if those endpoints lacked an LTHR record, `resolve_lthr()` raised `ValueError`, causing `daemon.py` to skip post-run feedback entirely.

## Decisions

1. **Logseq Journal Contract for Runs:**
   - Logseq journals must **only** receive `coach: feedback:: <flowing text>` for actual completed runs.
   - Raw run metrics (`run: distance:: ...`, `avg-speed:: ...`, `avg-heart-rate:: ...`) and workout suggestions (`wotd: ...`, `suggested_run: ...`) are **never** written to Logseq journals.
   - Sleep metrics (`sleep: duration:: ...`, `quality:: ...`) and step counts (`body: steps:: ...`) remain in their respective morning triggers.

2. **Strict Completed Run Qualification:**
   - An activity triggers post-run coaching feedback if and only if it is an actual completed run:
     - `activityType` contains `"run"` (e.g. `running`, `trail_running`, `treadmill_running`)
     - `duration >= 60.0` seconds (filters out aborted clicks)
     - `distance >= 500.0` meters (filters out zero-distance calendar entries)
     - `averageSpeed > 0.0` m/s (filters out scheduled/unexecuted calendar workouts)

3. **Accurate Date Targeting & Offline Resilience:**
   - Target date is extracted directly from the activity's `startTimeLocal` (`YYYY-MM-DD`).
   - If Logseq SSH direct-write fails, feedback is queued to `pending_logseq_syncs.json` via `queue_pending_sync()`.
   - `queue_pending_sync()` merges properties for the same date cleanly so that sleep, steps, and coach feedback never overwrite one another.
   - `flush_pending_syncs()` replays all pending writes on every daemon poll as soon as Logseq is accessible.

4. **Garmin-Calculated HR Zones & Prompt Hardening:**
   - Coach feedback HR zones are strictly derived from `get_hr_zones(client, athlete_cfg, user_data_dir, recalibrate=False)`.
   - `resolve_lthr()` is augmented with live biometric endpoints:
     1. `get_user_profile() -> userData.lactateThresholdHeartRate`
     2. `get_lactate_threshold(latest=True) -> speed_and_heart_rate.heartRate`
     3. 15-day scan of `get_training_status()`
     4. `get_heart_rate_zones()` profile scan
   - The AI coaching prompt explicitly forbids age-based formulas (`220 - age`) and instructs the model to judge the run exclusively against the athlete's Garmin-calculated Zone 2 (132–154 bpm at LTHR 177) and walk-break trigger (≥ 155 bpm).

## Verification

- `tests/garmin/test_hr_zones.py`: All 13 tests passed, verifying LTHR resolution through user profile, lactate threshold endpoint, heart rate zones, and strict refusal of age formulas.
- `tests/test_logseq_connection.py`: All 7 tests passed, verifying queue merging, non-completed run filtering, run date targeting, and Logseq queueing on SSH failure.
- `tests/garmin/test_wotd_snapshot_and_feedback.py` and `tests/garmin/test_wotd_time_gate.py`: All 13 tests passed.
