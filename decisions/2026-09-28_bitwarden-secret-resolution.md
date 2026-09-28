# 2026-09-28 — Secrets resolved from Bitwarden at deploy time (`@bws` sentinel)

**Status:** Accepted

## Context

This app lives on the same production host as `ai-trading-bot`, where the
Bitwarden CLI is already installed and a working deploy-time secret resolution
pattern already exists. The coach app still documented realistic secret-looking
values in `.env.example` and had no first-class mechanism to keep committed env
templates secret-free while still making production deployment repeatable.

## Decision

Real secrets live in **Bitwarden Secrets Manager** (project `ai-health-coach`),
keyed by their exact environment-variable names.

1. **`.env.template` carries `KEY=@bws`** for every secret. `@bws` means
   "resolve this from Bitwarden by this key name at render time." Non-secret
   config remains literal in the template.
2. **`scripts/render_env.py`** resolves every sentinel from the JSON returned by
   `bws secret list -o json`. It is fail-closed: if any required key is absent
   or empty, it exits non-zero without producing a usable `.env`.
3. **`scripts/render_env.sh`** is the host entry point. It sources
   `BWS_ACCESS_TOKEN` from `~/.config/garmin-ai-coach/bws.env`, fetches secrets
   once from Bitwarden, renders `.env` atomically, chmods it `600`, and leaves
   the existing `.env` untouched on any error.
4. **Tests** enforce the contract by asserting the committed template uses the
   `@bws` sentinel for every secret-bearing key.

## Consequences

- Secret rotation becomes a Bitwarden operation instead of a repo edit.
- The production host needs Bitwarden reachability only when `.env` is rendered,
  not on every container restart.
- The deploy workflow ships the resolver tooling and scrubbed template, but does
  not auto-render `.env`; rendering remains an explicit operator step.
