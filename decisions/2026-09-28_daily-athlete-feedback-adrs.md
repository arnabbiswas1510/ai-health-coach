# 2026-09-28 — Daily Athlete Feedback as Recency-Weighted ADRs

**Status:** Accepted
**Date:** 2026-09-28
**Supersedes:** none

## Context

The coaching loop was one-directional. `services/garmin/run_coach_feedback.py`
generates a post-run note *from* the coach *to* the athlete, but the athlete had
no structured way to talk back. The only inbound channel was the floating chat
panel, which routes every message through `_run_weekly_replan()` — a full
LangGraph planning pass with a 300-second timeout. That is far too heavy for
"knee twinged at km 4" or "skipped today, work ran late", and its output is a
regenerated weekly plan rather than a durable record.

Consequently the daily WOTD was designed purely from physiological telemetry
(sleep, HRV, training readiness, run baseline). Subjective signals that only the
athlete knows — pain, life logistics, motivation, how a prescribed session
actually felt — never reached `_call_ai_for_workout()`.

A second, related gap: the generated workout was never surfaced anywhere. Only
`wotd_last_id.txt` and `wotd_trigger.log` were persisted, so the workout itself
was visible exclusively inside Garmin Connect. Asking the athlete to comment on
a workout they cannot see in the dashboard is poor ergonomics.

## Decision

Introduce athlete-authored daily feedback, captured as ADRs and consumed by WOTD
generation.

### 1. Storage — server volume, not the repository

Feedback ADRs are written to `data/<athlete>/feedback_decisions/YYYY-MM-DD_<slug>.md`,
which is the `./data:/app/data` bind mount. They are **never committed or pushed**.

Rationale:

- The production DietPi host has no git available to the container, and the
  deploy pipeline runs `git fetch --all && git reset --hard origin/main`.
- `data/` is gitignored with zero tracked files, so a hard reset leaves these
  files untouched. Committing them would instead put personal health notes into
  a shared repository and create merge conflicts on every deploy.
- This preserves a clean split: `decisions/` holds *code* ADRs (versioned,
  reviewed); `data/<athlete>/feedback_decisions/` holds *training* ADRs
  (personal, high-volume, server-local).

Accepted tradeoff: no version history and no off-box backup. Partially mitigated
by mirroring each note into the Logseq daily journal.

### 2. Classification — one fast LLM call at submit time

`record_feedback()` makes a single `AgentRole.WORKOUT` call that converts free
text into `title`, `category`, `severity`, `insight`, `coaching_directive` and
`supersedes`. Processing at submit time (rather than deferring to the daemon)
lets the athlete see immediately how their note was understood.

If the call fails, `_default_classification()` stores the note verbatim under
`category: other`. **Feedback is never lost to an LLM outage.**

### 3. Supersession — true ADR semantics

A newer note may retire an older one ("knee is fine now" supersedes "knee pain").
Two guards constrain the model:

- Supersession is rejected across categories.
- It is limited to `SUPERSEDING_CATEGORIES` (injury, fatigue, motivation,
  performance). A second `missed-workout` note is a *distinct event*, not a
  correction of the first, so those never supersede each other.

Hallucinated ids that match no active record are discarded.

### 4. Recency weighting — mirrors the existing run baseline

`load_weighted_feedback()` returns active entries from the last 21 days, newest
first, capped at 10, each weighted `0.85 ** days_ago`. The decay factor matches
`_weighted_run_baseline()` so subjective and objective signals age at the same
rate.

### 5. Authority — advisory but bounded (Rule 12)

Feedback is injected into the WOTD prompt and governed by a new Rule 12. It MAY
reduce duration or intensity, change format, or override a high readiness score
when severity is `high`. It may **NEVER** raise HR targets, alter the
`walk_break_hr` trigger, push `warmup_min` above 5, or exceed the duration cap.

These invariants are the athlete's knee-health and zone-compliance guarantees;
they must not be negotiable by free text, which is also a prompt-injection
boundary. The constraint is additionally stated in the classifier prompt so the
generated directive is in-bounds before it ever reaches the workout prompt.

### 6. Timing — auto-detected, never asked

Feedback is inherently retrospective (the WOTD is generated ~06:20, the athlete
reacts afterwards), but a note written before generation should shape that same
day's workout. `detect_timing()` infers `post-run`, `workout-issued-not-yet-run`
or `pre-workout` from `last_run.json` and `wotd_today.json`. `daemon.py` now
writes `last_run.json` when it detects a completed run.

### 7. WOTD visibility — strictly gated on the Garmin push

`_save_wotd_snapshot()` writes `data/<athlete>/wotd_today.json` **only after**
`_push_wotd()` returns a Garmin workout id, and never in dry-run mode.
`GET /wotd/today` additionally re-checks the date and the presence of
`garmin_workout_id`.

This ordering is deliberate and load-bearing: **the athlete trains from Garmin
Connect.** A dashboard showing a workout that failed to upload would cause the
two to disagree and risk training against a session not on the watch. The UI is
a mirror that may lag Garmin, never lead it. A snapshot write failure is logged
but never fails an already-successful push.

## Consequences

**Positive**

- Subjective signals now reach workout design; missed-session patterns can
  shorten future workouts rather than being invisible.
- The athlete sees today's workout and responds to it in one place.
- Notes survive redeploys and are mirrored to Logseq.
- Safety invariants are explicit and test-pinned.

**Negative**

- One extra LLM call per submission.
- Feedback ADRs have no version history or off-box backup.
- Prompt length grows with up to 10 entries (bounded by the cap and window).

## Files changed

- `services/feedback/feedback_adr.py` (new) — ADR model, persistence,
  classification, supersession, weighting, timing detection
- `services/feedback/__init__.py` (new) — public surface
- `services/garmin/wotd_generator.py` — feedback injection, Rule 12,
  `_save_wotd_snapshot()` gated on the Garmin push
- `services/chat_api/main.py` — `POST /feedback`, `GET /feedback/recent`,
  `DELETE /feedback/{id}`, `GET /wotd/today`
- `daemon.py` — writes `last_run.json` for timing detection
- `index.html` — "Today's Workout" and "Daily Feedback" cards
- `docker-compose.yml` — hot-reload mount for `services/feedback` to match the
  existing `services/garmin` mount
- `tests/test_feedback_adr.py`, `tests/test_chat_api_feedback.py`,
  `tests/garmin/test_wotd_snapshot_and_feedback.py` (new)
