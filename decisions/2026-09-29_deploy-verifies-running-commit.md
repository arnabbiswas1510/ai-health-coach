# A deploy must prove production is running the code it just published

- **Date:** 2026-09-29
- **Status:** Accepted
- **Supersedes:** nothing
- **Related:** `2026-09-29_production-consumes-published-image.md`

## Context

`2026-09-29_production-consumes-published-image.md` fixed the delivery half of
the deploy: production now pulls `ghcr.io/arnabbiswas1510/ai-health-coach` and
no longer builds its own `ai-health-coach:local`, and source bind-mounts no
longer shadow the image's code.

The first deploy after that fix shipped real code for the first time in roughly
five weeks. It immediately exposed a latent defect: `startup.sh` contained an
unterminated string literal (an escaped quote `\"` where a line-continuation
`\\"` was intended). bash parses a function body in full at definition time, so
the entrypoint aborted on every boot and the container entered a restart loop.

**The deploy reported success anyway.** The workflow ended with:

```bash
docker compose up -d --remove-orphans
docker inspect ai-health-coach --format '...'
exit 0
```

`docker compose up -d` returns as soon as the container is *created*, not once
it is healthy, and `docker inspect` only printed state — nothing consumed it.
The unconditional `exit 0` meant a crash-looping production container produced
a green workflow run.

This is the same class of failure as the stale-image bug: the pipeline reported
success for an outcome it never verified. Fixing delivery without fixing
verification just moved the blind spot one step later.

Two distinct failure modes need to be caught:

1. **The container does not stay up.** A bad entrypoint, a missing dependency,
   or invalid configuration.
2. **The container is up but running the wrong code.** Precisely the stale-image
   bug — a green deploy that changed nothing. Container state alone cannot
   detect this, because a stale container is perfectly healthy.

## Decision

The deploy asserts both properties and fails the workflow if either does not
hold.

### 1. The container must reach a stable running state

Poll `docker inspect --format '{{.State.Status}}'` for up to 60s. `restarting`
or `exited` is fatal immediately. `running` is confirmed twice, five seconds
apart, so a container that starts and then dies is not mistaken for a healthy
one. On failure the deploy prints the last 40 log lines and exits 1.

### 2. The container must report the commit that was just published

CI passes `--build-arg GIT_COMMIT=${{ github.sha }}`; the Dockerfile promotes it
to `ENV GIT_COMMIT`; the chat API exposes `GET /version` returning
`{"git_commit": ...}`. The deploy curls it and compares against the SHA it
deployed. A mismatch is fatal.

Two states are warnings rather than errors, to avoid failing deploys for
reasons unrelated to the change being shipped:

- **`/version` does not respond.** The chat API is not the daemon; production's
  core function is the daemon, which the state check already covers.
- **`/version` reports `unknown`.** The image predates the `GIT_COMMIT` build
  arg. This self-clears on the first deploy of an image built after this change.

## Consequences

**A broken deploy now fails loudly.** The outage that motivated this would have
been caught by check 1: the container was `restarting`, so the workflow would
have failed with the syntax error in its logs instead of reporting success.

**Stale images are detectable at runtime.** Check 2 closes the gap the previous
ADR left open. That ADR made production *consume* the published image; this one
makes production *prove* it did. `/version` is also a manual diagnostic —
`curl localhost:8001/version` answers "what is actually running?" directly.

**The image carries build provenance.** `GIT_COMMIT` is baked in, so the
running container can be traced to a commit without consulting registry
metadata.

**A deploy can now fail on infrastructure, not just code.** If the box is slow
and the container takes more than 60s to stabilise, the deploy fails. This is
the intended trade: a false failure is recoverable by re-running, while a false
success silently leaves production broken, which is what happened here.

**`/version` is unauthenticated.** It exposes only a commit SHA of a public
repository, so this leaks nothing. It must not be extended to report
configuration or secret state.

## Alternatives considered

**A compose `healthcheck` with `--wait`.** Cleaner in principle, but it only
covers liveness (check 1), not identity (check 2), and it would require
defining a meaningful health probe for the daemon, which has no server socket.
Rejected as insufficient on its own; it remains a reasonable future addition
alongside the commit check.

**Comparing image digests before and after the pull.** Detects a stale image
without a new endpoint, but proves only that the *image* changed, not that the
*running container* was recreated from it. It also yields no operator-facing
diagnostic. Rejected as weaker for the same effort.

**Failing the deploy when `/version` is unreachable.** Rejected: it couples the
daemon's deploy outcome to the chat API's availability, which would fail deploys
for an unrelated subsystem. Container state is the authoritative liveness signal.
