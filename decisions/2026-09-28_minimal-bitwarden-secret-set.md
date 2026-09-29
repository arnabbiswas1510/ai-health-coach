# Scope secrets to one Bitwarden project, reduce the mandatory set to six, and actually run the renderer

- **Date:** 2026-09-28
- **Status:** Accepted
- **Supersedes:** nothing; refines `2026-09-28_bitwarden-secret-resolution.md`

## Context

`scripts/render_env.py` replaces every `@bws` sentinel in `.env.template` with the
Bitwarden secret of the same name. It fails closed: a sentinel that resolves to a
missing **or empty** value is reported in a `MISSING:` list and the process exits
with rc=3, leaving `.env` untouched.

That fail-closed behaviour is correct and worth keeping. But the template shipped
eleven sentinels while this deployment only uses six of them:

- Every `AI_MODE` maps the agent roles this app runs to `gemini-2.5-flash`, so
  `GOOGLE_API_KEY` is the only LLM credential in play. `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `OPENROUTER_API_KEY` and `DEEPSEEK_API_KEY` are unused.
- `LANGSMITH_API_KEY` is optional observability.

Because the resolver is all-or-nothing, those five unused sentinels were not
merely redundant — they were mandatory. Standing up the stack required inventing
five throwaway Bitwarden entries whose only purpose was to stop the renderer from
aborting. Empty-valued entries would not work, since an empty resolution already
counts as missing.

Two further problems compounded this:

1. `deploy_to_server.yml` copied `render_env.sh` to the server and ran
   `chmod +x` on it, but **never executed it**. `.env` therefore never refreshed
   on deploy, and a rotated secret would sit in Bitwarden indefinitely without
   reaching production.
2. Junk placeholder values are not inert. `ModelSelector` reroutes Google models
   through OpenRouter whenever `GOOGLE_API_KEY` is absent and
   `OPENROUTER_API_KEY` is present. A placeholder OpenRouter key would turn a
   missing-Google-key incident into a confusing authentication failure against a
   provider the operator never intended to use.

## Decision

**Blank the five unused sentinels in `.env.template`** rather than requiring junk
secrets. They become `KEY=`, matching the precedent `GEMINI_API_KEY=` already set
in the same file. The mandatory Bitwarden set is now exactly six:

`GOOGLE_API_KEY`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `LOGSEQ_SSH_HOST`,
`LOGSEQ_SSH_USER`, `LOGSEQ_GRAPH_PATH`.

**Split the secrets guard test in two.** `REQUIRED_BWS_KEYS` must carry the
sentinel; `OPTIONAL_BWS_KEYS` may be the sentinel *or* blank, but never a
literal. The security property the guard exists to defend — no real secret in a
tracked file — is unchanged, because blank is the absence of a value, not a
committed credential. A third test rejects any undeclared `@bws` line, so adding
a sentinel without creating the matching secret can no longer silently break a
deploy.

**Invoke `render_env.sh` from the deploy workflow**, before `docker compose up`,
but **gated behind an opt-in marker file** at
`~/.config/garmin-ai-coach/autorender.enabled`.

The sibling `ai-trading-bot` deployment deliberately does *not* auto-render, for
two stated reasons: rendering unattended on every push would overwrite a
hand-tuned host `.env` with template defaults before the operator can diff it,
and it would make a routine redeploy depend on Bitwarden reachability. Both
concerns are real here too — this coach's host `.env` has never been through a
Bitwarden cutover, so it is still hand-maintained and may hold keys absent from
the template.

The marker resolves the first concern and the fallback logic resolves the second,
giving four defined states:

| Marker | Host `.env` | Render | Outcome |
|---|---|---|---|
| absent | present | not run | keep the hand-maintained `.env`, `::notice::` explaining the cutover |
| absent | absent | not run | `::error::`, fail the job — nothing to start the stack with |
| present | any | succeeds | `.env` refreshed |
| present | present | fails | `::warning::`, continue on the previous `.env` |
| present | absent | fails | `::error::`, fail the job |

So the cutover stays manual and diffable exactly once; `touch`ing the marker
afterwards opts into automation, and Bitwarden being unreachable degrades rather
than taking the coach offline.

**Scope the secret lookup to a single Bitwarden project.** The script previously
ran a bare `bws secret list`, which returns every secret the machine account can
reach across *all* projects, and the resolver indexed them into a flat dict where
the last entry silently won. With secrets now organised under a project named
`ai-health-coach` — alongside sibling projects such as the trading bot — a
same-named key in another project could be rendered into this `.env` with no
indication anything was wrong.

`render_env.sh` now resolves `BWS_PROJECT_NAME` (default `ai-health-coach`) to an
id via `bws project list`, then calls `bws secret list <project-id>`.
`BWS_PROJECT_ID` short-circuits the lookup when the id is already known. The
resolver gained `build_secret_map()`, which filters by `projectId` and raises on
duplicate keys holding *conflicting* values; identical duplicates are harmless
and allowed. An unresolvable project name reports the projects the token can
actually see, because the overwhelmingly likely cause is a typo or a machine
account that was never granted access.

Note that `ai-trading-bot` still lists secrets unscoped. Both apps deploy to the
same host as the same user (`pom`), so their bootstrap files sit side by side in
`/home/pom/.config/` — separate machine accounts would therefore buy almost no
isolation, since anyone who can read one file can read the other. A **single
shared token is the right call**; what keeps the two apps' secrets apart is
project scoping, not token separation. Porting this scoping to `ai-trading-bot`
is the outstanding half of that. Today the two projects share no sentinel key
names, but the trading bot's template already invites `OPENAI_API_KEY=@bws`,
which this repo also declares — so the collision is latent, not hypothetical.

**Look for the bootstrap token in more than one place.** Because a single token
now serves several apps on the host, `render_env.sh` searches, in order:

1. `$BWS_ENV_FILE` — honoured *exclusively* if set; a missing file here is a hard
   error rather than a fallback, since silently authenticating with a different
   token than the operator named is worse than failing.
2. `~/.config/garmin-ai-coach/bws.env` — app-specific, so one app can opt out of
   the shared token without disturbing the others.
3. `~/.config/bws/bws.env` — shared across apps on this host.

The chosen path is logged (path only, never the token). Nothing is migrated: an
existing app-specific file keeps working untouched.

**Ignore a `BWS_PROJECT_ID` that arrives from the bootstrap file.**
`ai-trading-bot` stores its project id *inside* `bws.env` alongside the token, so
a genuinely shared bootstrap file would carry that id into this app. Sourcing it
would point the coach at the trading bot's project; every sentinel would then be
unresolvable and the render would abort with `MISSING:` listing all six keys —
fail-closed, but diagnostically misleading, since the real fault is the project,
not the secrets. `render_env.sh` therefore captures any environment override
*before* sourcing and discards whatever the file sets, logging that it did so. A
deliberate `BWS_PROJECT_ID=` in the environment still wins. The coach resolves
its project by *name*, which is inherently app-specific and cannot collide.

## Consequences

- Standing up a fresh server needs six real secrets, not eleven, and none of them
  are fictional.
- Secret rotation propagates automatically once the operator opts in, and never
  silently before then.
- Secrets are isolated per project, so adding an unrelated project to the same
  Bitwarden organisation cannot silently poison this deployment's `.env`.
- One machine account can safely serve every app on the host, because isolation
  comes from project scoping rather than from token separation. The account
  still only needs read access to the projects it actually renders.
- Switching providers is a deliberate two-step act: restore the sentinel *and*
  create the secret. The undeclared-sentinel test makes forgetting the second
  step a test failure rather than a production outage.
- The renderer's fail-closed semantics are untouched. This changes *which* keys
  are mandatory, not what happens when a mandatory key is missing.
