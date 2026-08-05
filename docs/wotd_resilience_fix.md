# WOTD Resilience & State-Management Fix

## Executive Summary
This document details the root cause analysis for missed Workout of the Day (WOTD) pushes in `daemon.py` and describes the 6:20 AM time-gated fallback architecture to ensure automatic retries and guaranteed daily workouts.

---

## 🔍 Root Cause Analysis (RCA)

### 1. Premature State Mutation (The Core Issue)
In [daemon.py:364](file:///home/pom/workspace/ai-health-coach/daemon.py#L364), the daemon writes `today_iso` into `last_processed_sleep_date.txt` **before** calling `generate_workout_of_the_day()`:

```python
# ① Mark as processed FIRST — prevents re-trigger if WOTD or Logseq errors
last_sleep_file.write_text(today_iso, encoding="utf-8")

# ② Generate and push WOTD to Garmin
generate_workout_of_the_day(...)
```

* **Failure Mode**: If `generate_workout_of_the_day()` fails on its first attempt (e.g. LLM API rate limit, 500 network error, Garmin API delay, or LTHR calculation error), the exception is logged, but the date is already written to disk.
* **Result**: On all subsequent hourly daemon polls today, `last_sleep_date == today_iso` evaluates to `True`. The daemon logs `"Sleep already processed for YYYY-MM-DD — WOTD skipped."` and **never retries WOTD generation for the rest of the day**.

### 2. Coupled Sleep Sync & WOTD Pushing
Logseq sleep logging and WOTD generation are currently tied to a single file (`last_processed_sleep_date.txt`). 
* While Logseq writes have a retry queue (`pending_logseq_syncs.json`), WOTD pushing has no separate status tracking.
* If Logseq succeeds but WOTD fails (or vice versa), the system considers the entire morning sleep routine finished.

---

## 🛠️ Implemented Architectural Fix

### 1. 6:20 AM Cutoff Time Gate
* **Before 06:20 AM**: If today's sleep data is ready (`sleepTimeSeconds > 0`), generate and push today's WOTD immediately using today's live sleep metrics.
* **At or after 06:20 AM**: If today's WOTD has not been pushed yet, force WOTD generation using yesterday's sleep metrics as fallback.

### 2. Separate WOTD Pushing from Sleep Data Processing
Created dedicated marker file `last_pushed_wotd_date.txt` to track WOTD completion independently from `last_processed_sleep_date.txt`.

### 3. Update Marker Only AFTER Successful Push
Update `last_pushed_wotd_date.txt` **only when `generate_workout_of_the_day()` completes without throwing an exception**.

### 4. Automatic Hourly Retry Loop
If sleep data for today is present (`sleep_seconds > 0`) or local time >= 06:20 AM, but `last_pushed_wotd_date.txt` is not today's date, the daemon automatically retries generating and pushing today's WOTD on every hourly poll until it succeeds.
