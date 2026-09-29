# .env.template declares every key docker-compose.yml reads

- **Date:** 2026-09-29
- **Status:** Accepted

## Context

`scripts/render_env.sh` regenerates `.env` **wholesale** from `.env.template`:
it resolves `@bws` sentinels against Bitwarden, writes a temp file and moves it
over `.env`. There is no merge step. Any key absent from the template is
therefore absent from the rendered `.env`.

`docker-compose.yml` reads 35 environment keys. `.env.template` declared 16.
Six of the remaining keys were present in the template but **commented out**
(`POLL_INTERVAL_SECONDS`, `FORCE_ANALYTICS`, `COMPETITIONS` among them), which
reads as "optional" but behaves as "absent".

This gap is invisible, which is what makes it dangerous:

- Every compose reference for the undeclared keys has a `:-` default
  (`${ATHLETE_WEIGHT:-}`, `${HITL_ENABLED:-true}`, ...), so nothing fails.
- The six keys with **no** compose default — `GOOGLE_API_KEY`, `GARMIN_EMAIL`,
  `GARMIN_PASSWORD`, `LOGSEQ_SSH_HOST`, `LOGSEQ_SSH_USER`,
  `LOGSEQ_GRAPH_PATH` — were all already declared, so the loud failure mode
  was never reachable.

The result: a Bitwarden cutover would silently drop configuration and the
container would start cleanly on compose defaults, with the change surfacing
only as altered coaching behaviour.

Inspection of the production host showed the live blast radius was small --
`.env` there holds 16 keys, of which only `COMPETITIONS` (set to `[]`) was
undeclared. The other 18 were never in the host `.env` at all and already run
on compose defaults. So this is a latent hazard being closed before
auto-render is enabled, not an incident.

## Decision

`.env.template` declares every key `docker-compose.yml` reads, with literal
values for the non-secret ones and the existing `@bws` sentinels for the six
real secrets. Commented-out keys are activated rather than left as
documentation.

Values are taken verbatim from the compose defaults (`ATHLETE_AGE=53`,
`TARGET_GOAL=base_building`, `HITL_ENABLED=true`, ...), so rendering changes
no effective configuration.

`IMAGE` is deliberately excluded: it selects the container image tag for local
development overrides and is compose-level plumbing, not application
configuration.

`tests/test_no_secrets_committed.py::test_template_declares_every_key_compose_reads`
enforces the invariant by parsing `docker-compose.yml` for `${VAR}` references
and diffing against the template.

## Consequences

**Positive**

- Rendering `.env` from the template is now provably non-destructive.
  Verified against the production key list: zero keys lost, 19 added, all at
  their existing effective values.
- The template becomes the single source of truth for `.env`, which is the
  precondition for turning on auto-render.
- Adding a new `${VAR}` to compose without declaring it now fails CI.

**Negative / accepted**

- The template is longer and carries values that duplicate compose defaults.
  Drift between the two is possible; the test catches *missing* keys but not
  *divergent* values. Compose defaults remain the fallback, so divergence
  degrades to the old behaviour rather than breaking.
- Athlete profile values are declared empty. That matches the current host
  `.env`, which does not set them; the athlete profile is carried in
  `coach_config.yaml`.

## Verification

Mutation-tested: re-commenting `COMPETITIONS` fails the new test. A mock
render was diffed against the exact key list read from the production host —
`comm -23` reported no lost keys.
