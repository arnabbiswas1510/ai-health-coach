# Production consumes the published image instead of building on the host

- **Date:** 2026-09-29
- **Status:** Accepted
- **Supersedes (in part):** the `build: .` arrangement noted in `AGENTS.md`

## Context

`Publish Docker Image` (`.github/workflows/deploy.yml`) builds and pushes
`ghcr.io/arnabbiswas1510/ai-health-coach:latest` on every push to `main`.
`Deploy to Production Server` then runs `docker compose pull && docker compose
up -d` on the DietPi box. The intent has always been "push to main deploys the
new code".

That is not what happened. `docker-compose.yml` declared:

```yaml
build: .
image: ai-health-coach:local
```

so the published artifact was never consumed:

1. `docker compose pull` cannot pull `ai-health-coach:local` — it is not a
   registry reference. Compose warns that the service must be built from
   source and continues. The deploy job has no `script_stop`, so the warning
   is invisible in a green run.
2. `docker compose up -d` reuses an existing image and only builds when the
   image is *absent*. `ai-health-coach:local` existed, so nothing rebuilt.

The deploy therefore restarted the stack on a months-old image and reported
success. Separately, the scp step copies only `docker-compose.yml`,
`.env.template` and the two `render_env` scripts — no application source — so
even an explicit `--build` on the host would have built a stale tree. There is
no git on the production box, and the `git fetch --all && git reset --hard`
step that `AGENTS.md` describes does not exist in the workflow.

Compounding this, five bind mounts shadowed the image's own code:

```yaml
- ./daemon.py:/app/daemon.py
- ./force_wotd.py:/app/force_wotd.py
- ./services/garmin:/app/services/garmin
- ./services/feedback:/app/services/feedback
- ./services/logseq:/app/services/logseq
```

Labelled "hot-reload: local overrides image", these made sense when source was
hand-copied to the host. With an image-based deploy they are actively harmful:
they replace freshly deployed code with whatever the host last received. The
`services/feedback` mount was the acute case — the directory is new in the
daily-feedback ADR work, does not exist on the host, and Docker creates a
missing bind-mount source as an **empty directory**. That would have mounted
nothing over `/app/services/feedback`, breaking `import services.feedback` in
the bind-mounted `daemon.py` and `wotd_generator.py`.

## Decision

Production consumes the published image and never builds.

1. **`image: ${IMAGE:-ghcr.io/arnabbiswas1510/ai-health-coach:latest}`** — the
   default is the CI artifact. The `IMAGE` override keeps local development
   possible (`docker build -t ai-health-coach:dev . && IMAGE=ai-health-coach:dev
   docker compose up -d`) without giving production a way to drift.
2. **`build:` removed.** Keeping it would let a failed pull silently fall back
   to building whatever source happened to be on the host — the exact failure
   being fixed.
3. **All source bind mounts removed.** Application code ships in the image via
   the Dockerfile's `COPY . .`. Only genuine host state remains mounted:
   `/app/tokens`, `/app/data`, `/app/coach_config.yaml` and `/root/.ssh`.
4. **`docker compose pull` failure aborts the deploy.** Previously a failed
   pull fell through to `up -d` on the cached image and exited 0.
5. **`docker inspect` output now includes the image id**, so the deploy log
   records which artifact actually started.

## Consequences

**Positive**

- Pushing to `main` genuinely deploys the pushed code.
- The production box needs no source checkout and no git.
- Deploys are reproducible: the running container is a published, attested
  artifact rather than a host-local build of unknown provenance.
- A pull failure is loud instead of masquerading as a successful deploy.

**Negative / accepted**

- Hot-patching production by editing a file on the host no longer works. That
  capability was already illusory without git on the box, and it is what
  allowed production to drift from `main` undetected.
- The first deploy after this change pulls a full image rather than reusing
  layers. One-time cost.
- The stale `ai-health-coach:local` image lingers until pruned.

**Migration.** `/app/data` and `/app/tokens` remain mounted, so feedback ADRs,
Garmin tokens and generated HTML survive. The host's stale source tree becomes
inert; it can be deleted once the new container is verified.

## Verification

`tests/test_deploy_image_pipeline.py` pins every element above: the image is
the published one, no `build:` key exists, no bind mount targets anything other
than the four allow-listed paths, persistent state is still mounted, the
publish and consume references agree, and the deploy workflow aborts on pull
failure. The suite was mutation-tested against the previous configuration —
five tests fail on it, including one per offending bind mount.
