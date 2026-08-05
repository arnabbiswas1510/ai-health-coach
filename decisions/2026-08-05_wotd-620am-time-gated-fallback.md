# 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data

## Status

Accepted.

## Context

Workout of the Day (WOTD) generation in `daemon.py` was previously strictly sleep-triggered. The daemon polled Garmin Connect hourly for overnight sleep metrics (`sleepTimeSeconds > 0`).

Two main operational issues occurred with this design:
1. **Garmin Cloud Sync Delays**: When the athlete's watch had not synced sleep metrics to Garmin Connect cloud servers by early morning, `sleepTimeSeconds` returned `0`. The daemon logged `"Sleep data for YYYY-MM-DD not yet available"` and deferred generation, resulting in no workout being available on the athlete's watch when starting a morning run.
2. **Premature State Mutation**: In `daemon.py`, `last_processed_sleep_date.txt` was written *before* calling `generate_workout_of_the_day()`. Any transient error (LLM rate limits, network timeout, LTHR fetch failure) locked out subsequent retries for the remainder of the day.

## Decision

1. **Time-Gated Trigger (`06:20 AM`)**:
   - **Before 06:20 AM**: If today's sleep data is ready (`sleepTimeSeconds > 0`), generate WOTD immediately with today's live sleep metrics.
   - **At or after 06:20 AM**: If today's WOTD has not been pushed yet, force WOTD generation regardless of whether today's sleep data has synced.
2. **Fallback Sleep Data**:
   - If today's sleep metrics are missing/0, `_extract_sleep_summary(sleep_data, fallback_sleep_data)` queries yesterday's sleep data (`get_sleep_data(yesterday_iso)`) or returns an estimated baseline summary (`hours: 7.0, recovery: adequate (fallback)`).
3. **Decoupled Completion Tracking**:
   - Created `last_pushed_wotd_date.txt` to track WOTD completion independently from Logseq sleep sync (`last_processed_sleep_date.txt`).
   - `last_pushed_wotd_date.txt` is updated **only after** `generate_workout_of_the_day()` returns cleanly without error.

## Consequences

- Today's workout is guaranteed to be on the Garmin Connect calendar/watch by 6:20 AM every morning.
- Transient network or API errors automatically retry on the next daemon poll until WOTD succeeds.
- Yesterday's sleep data acts as a safe fallback for AI intensity calculations when today's watch sleep sync is delayed.
