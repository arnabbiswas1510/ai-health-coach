# 2026-09-28 — HR zones unified in `services/garmin/hr_zones.py`

**Status:** Accepted

## Context

WOTD generation and post-run coaching feedback each computed the athlete's
Zone 2 independently, and they disagreed badly.

`run_coach_feedback._get_zone2()` claimed in its docstring to use "same logic as
wotd_generator". It did not:

1. It read LTHR only from `client.get_training_status()` with **no date
   argument**, looking for a top-level `lactateThresholdHeartRate`. The value
   actually lives in `get_user_profile() → userData.lactateThresholdHeartRate`,
   which it never consulted. So in practice it resolved `lthr = None`.
2. It then fell back to `220 - age` — a formula AGENTS.md explicitly forbids —
   producing **Z2 = 100–120 bpm** at age 53.
3. Even on the rare path where an LTHR *was* found, it applied hard-coded
   `0.80` / `0.89` percentages rather than the empirically calibrated constants,
   giving **141–157 bpm**.
4. It ignored `zone_calibrator` entirely, so auto-recalibration never reached
   the feedback path.

Meanwhile WOTD prescribes **132–154 bpm** with a walk break at **155 bpm**
(LTHR=177, calibrated 74.6% / 87.0% / 87.6%).

Net effect: a walk-run executed exactly as prescribed — sitting at 140 bpm — was
graded by the feedback agent as far above a Zone 2 it believed topped out at
120 bpm. The athlete was congratulated by one agent and corrected by the other
for the same run.

A third divergence existed inside WOTD itself: the prompt computed its
walk-break trigger as `z2_high + 1` (=154), ignoring the calibrated
`WALK_BREAK_PCT` (=155) that AGENTS.md documents as the non-negotiable Rule #10
value.

## Decision

Introduce **`services/garmin/hr_zones.py`** as the single source of truth.

- `resolve_lthr(client)` — `get_user_profile()` first, then a 14-day
  `get_training_status()` scan. Raises `ValueError` if neither yields a value.
  **There is no age-based fallback, by design.**
- `compute_zones(lthr, zone_cal, athlete_cfg)` — derives the full zone set from
  the calibrated percentages; manual `zone2_min` / `zone2_max` overrides win.
- `get_hr_zones(..., recalibrate: bool)` — combines both. `recalibrate=True`
  allows `zone_calibrator.maybe_recalibrate` to fire; `recalibrate=False` uses
  read-only `load_calibration`.

`wotd_generator` calls it with `recalibrate=True`; `run_coach_feedback` calls it
with `recalibrate=False`. The flag matters: `maybe_recalibrate` resets the run
counter as a side effect, so letting the feedback path call it would silently
consume the 10-run calibration cycle that WOTD owns.

WOTD now also passes its calibrated `walk_break_hr` into
`_call_ai_for_workout()` instead of recomputing `z2_high + 1`, so the prescribed
trigger matches the documented 87.6% rule.

The feedback prompt now states both the Z2 band and the walk-break trigger, and
tells the model that sub-floor HR during walk segments is intentional recovery
rather than a failure.

## Consequences

- Both agents quote identical numbers, always — enforced by
  `tests/garmin/test_hr_zones.py`, which asserts the two call sites return equal
  `HRZones` and that Z2 never collapses toward the old age-based range.
- If LTHR is unresolvable, post-run feedback now raises instead of inventing
  zones. `daemon.py` already wraps `generate_run_feedback` in `try/except`, so
  the run is simply skipped with a logged error — the correct fail-closed
  behaviour.
- WOTD prompts shift the walk-break trigger by one beat (154 → 155 at LTHR=177),
  bringing them in line with AGENTS.md Rule #10.
- `adaptive_coach.py` still carries its own 0.80/0.89 + age-fallback zone logic
  (covered by `tests/test_adaptive_coach.py`). It was left untouched here and is
  a candidate for the same consolidation.
