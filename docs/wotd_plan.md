# Workout of the Day — Implementation Plan

## What This Feature Does

Every morning, after you wake up and your watch syncs overnight sleep data to Garmin
Connect, the system automatically:

1. Detects that last night's sleep data has arrived (already partially working in daemon)
2. Pulls your last N runs with exponentially-weighted recency
3. Asks the AI to design **exactly one workout for today** based on sleep, fitness, goal,
   and weekday/weekend time constraint
4. Deletes any previously scheduled workout from Garmin Connect
5. Pushes exactly one new workout to Garmin Connect as today's scheduled workout

---

## Architecture: How It Fits Into the Existing System

```
daemon.py (polling loop, every 60 min)
    └── check_and_run()
            ├── [EXISTING] Trigger 1: new activity uploaded -> full 28-day plan pipeline (no change)
            └── [EXISTING] Trigger 2: sleep data arrives   -> was running full pipeline
                                                            -> CHANGE: runs WOTD generator instead
```

Currently when sleep data arrives, the daemon calls the full CLI pipeline
(cli/garmin_ai_coach_cli.py) which generates a 28-day plan. This is too heavy
for a daily wake-up trigger and produces multiple scheduled workouts, causing
watch errors.

The change: when the sleep trigger fires, call a new lightweight wotd_generator.py
instead. The full pipeline still runs on Trigger 1 (completed workout).

---

## Trigger Logic (daemon.py — existing sleep trigger, lines 199-228)

The sleep trigger already does the right thing. No change to the trigger condition.
Only what gets called changes:

```python
# BEFORE: sets should_run = True, which runs full CLI pipeline
# AFTER:
if sleep_seconds > 0:
    last_sleep_file.write_text(today_iso)
    from services.garmin.wotd_generator import generate_workout_of_the_day
    try:
        generate_workout_of_the_day(client, config, user_data_dir, sleep_data)
    except Exception as e:
        logger.error("WOTD generation failed: %s", e)
    # should_run stays False — full plan pipeline does NOT run on sleep trigger
```

---

## New File: services/garmin/wotd_generator.py

### 1. Weighted run baseline (replaces flat last-10 average)

```python
decay_factor = 0.85
weight_i = decay_factor ^ (N - 1 - i)   # i=0 is oldest, i=N-1 is most recent
```

Last run carries ~6x the weight of the oldest run in a 10-run window.
Output: one row — dist_km, pace_min_km, avg_hr, duration_min.
Cheaper on tokens and more accurate than a raw activity list.

### 2. Sleep quality classification

From the sleep data the daemon already fetches:
- sleep_hours from dailySleepDTO.sleepTimeSeconds
- sleep_score from dailySleepDTO.sleepScores.overall.value (0-100)

Classification:
- >= 7.5h + score >= 70: "well_rested"
- >= 6h  + score >= 50: "adequate"
- >= 5h  + score >= 40: "tired"
- anything below:       "very_tired"

### 3. Weekday / weekend constraint

```python
from datetime import date
is_weekday = date.today().weekday() < 5
max_duration_min = config.wotd.weekday_max_duration_min  # 60 on weekdays
                 or config.wotd.weekend_max_duration_min  # 105 on weekends
```

### 4. AI prompt (single GPT-4o-mini call)

```
Athlete profile:
  Goal: Lose weight to 160 lbs. Currently {weight_kg} kg.
  Age: 53
  Zone 2 HR: {zone2_low}-{zone2_high} bpm

Last night's sleep:
  Duration: {sleep_hours}h
  Sleep score: {sleep_score}/100
  Recovery: {recovery_status}

Recent fitness baseline (exponentially-weighted last {n} runs):
  Avg distance: {dist} km
  Avg pace: {pace} min/km
  Avg HR: {hr} bpm
  Avg duration: {duration} min

Today:
  Day type: {"Weekday" | "Weekend"}
  Max total duration (incl. warmup + cooldown): {max_duration_min} minutes

Design ONE workout. Rules:
1. Must fit in {max_duration_min} min total
2. If recovery = tired/very_tired: reduce intensity and/or distance
3. Use walk-run intervals to stay in Zone 2 if pace alone won't keep HR down
4. Optimise for weight loss (caloric burn + aerobic base)

Return JSON:
{
  "workout_name": "...",
  "workout_type": "simple|structured|long",
  "description": "...",
  "duration_min": 45,
  "distance_km": 6.0,
  "target_hr_low": 120,
  "target_hr_high": 140,
  "coach_note": "Why this workout today",
  "steps": [
    {"type": "warmup",   "duration_min": 5,  "hr_low": 110, "hr_high": 125},
    {"type": "run",      "duration_min": 35, "hr_low": 120, "hr_high": 140},
    {"type": "cooldown", "duration_min": 5,  "hr_low": 100, "hr_high": 115}
  ]
}
```

### 5. Delete yesterday's workout

The workout ID pushed yesterday is saved in user_data_dir/wotd_last_id.txt.
On each run:
1. Read the file
2. Call client.delete_workout(id) via the Garmin API
3. 404 = already deleted, safe to proceed
4. Any other error = abort push with warning (prevents double-workout on watch)
5. Delete the file on success

### 6. Push today's workout

Reuse GarminCalendarSyncer to convert the AI JSON into a ParsedWorkout and
schedule it for date.today(). Save the returned workout ID to wotd_last_id.txt.

---

## Files Changed

### [NEW] services/garmin/wotd_generator.py
Full new module — generate_workout_of_the_day() as the main entry point.

### [MODIFY] daemon.py
Change the sleep trigger block (lines ~215-224) to call wotd_generator
instead of setting should_run = True. About 8 lines changed.

### [MODIFY] coach_config.yaml
Add workout_of_the_day block:

```yaml
workout_of_the_day:
  enabled: true
  target_weight_lbs: 160
  weekday_max_duration_min: 60
  weekend_max_duration_min: 105
  recent_runs_count: 10
  decay_factor: 0.85
  push_to_garmin: true     # set false for dry-run
```

---

## Data Flow Diagram

```
Wake up -> watch syncs -> sleep data arrives in Garmin Connect
                                  |
                     daemon polls (every 60 min)
                                  |
                    sleep trigger fires (sleep_seconds > 0)
                                  |
             +--------------------------------------------+
             |          wotd_generator.py                 |
             |                                            |
             |  1. fetch last 10 runs (weighted avg)      |
             |  2. classify recovery from sleep data      |
             |  3. check weekday vs weekend               |
             |  4. build AI prompt with all context       |
             |  5. call GPT -> receive workout JSON       |
             |  6. delete yesterday's workout from GC     |
             |  7. push today's workout to GC             |
             |  8. save new workout ID to wotd_last_id    |
             +--------------------------------------------+
                                  |
             Garmin Connect: 1 workout on today's calendar
                                  |
                   Watch syncs -> Workout of the Day appears
```

---

## What Does NOT Change

- Full 28-day plan pipeline (fires on new completed run — unchanged)
- calendar_syncer.py — reused as-is for the Garmin push step
- adaptive_coach.py — not involved in WOTD (AI generates directly)
- Logseq journal sync — continues independently each morning
- Withings scale sync — unchanged

---

## Safety: Only One Workout on Watch

> [!CAUTION]
> Garmin watch errors when multiple workouts are scheduled. The delete-before-push
> order is the critical safety mechanism.
>
> Rule: if delete returns anything other than 404, ABORT the push.
> Only proceed with the push if yesterday's workout is confirmed deleted.

Additional guard: the WOTD feature pushes to today only. The full plan pipeline
(trigger 1) is not changed, but sync_calendar in coach_config.yaml is currently
set to false — this should remain false so the plan pipeline does not also push
to the calendar.

---

## Implementation Order

1. Add workout_of_the_day block to coach_config.yaml
2. Create services/garmin/wotd_generator.py
3. Modify daemon.py sleep trigger to call wotd_generator (not full pipeline)
4. Test with push_to_garmin: false for 2-3 days (logs only, no push)
5. Verify workout JSON looks correct, then enable push_to_garmin: true

**Estimated effort:** 3-4 hours implementation + 2-3 days dry-run validation.
