# Withings credential durability via Bitwarden

- **Date:** 2026-09-29
- **Status:** Accepted

## Context

The Withings → Garmin weight sync authenticates with an OAuth credential that
`withings-sync` stores at `tokens/.withings_user.json`. Creating that file
requires an interactive flow: the operator runs a one-off container, opens a
Withings URL, authorizes a profile, and pastes a code back within roughly
30 seconds before it expires.

**This has already failed once, silently.** Investigation of the production box
showed the sync had never run successfully since it was deployed:

- The `tokens/` directory's mtime was frozen at the moment of the original
  setup attempt. A directory's mtime updates when an entry is created *or*
  deleted, so had the credential ever been written and later removed, the mtime
  would record the removal instead.
- No Withings artefact existed anywhere on the host outside image layers.
- The bind mount demonstrably persists other files (`garmin_tokens.json`
  survives restarts), so the mount was not at fault.

The only explanation consistent with all three is that the authorization never
completed — almost certainly the 30-second window expired. Nothing alerted us,
because a missing credential simply made `withings-sync` prompt on stdin, which
in a detached container raises `EOFError` inside an already-noisy log.

Two properties make this worse than a one-time annoyance:

1. The credential lives only in a host directory. A rebuilt host, a wiped disk,
   or a migration loses it and forces the 30-second scramble again.
2. `WithingsOAuth2.__init__` calls `refresh_accesstoken()` **unconditionally**,
   and Withings issues a **new refresh token on every refresh**. The daemon
   polls hourly, so the credential was set to rotate roughly 24 times a day.

## Decision

Mirror the credential into the same Bitwarden project that already holds every
other production secret, and gate the sync to run once a day.

**Seed on the way in.** `seed_from_vault()` restores the file when it is absent,
so a fresh host needs no interaction at all. It never overwrites an existing
local file: the on-disk copy is the live one, and the vault copy may be a
rotation behind. It validates JSON before writing, because a corrupt file would
send `withings-sync` straight back to its stdin prompt.

**Push on the way out, in-process.** `push_to_vault()` runs immediately after a
successful sync — in the *same process* that just rotated the token. This is
forced by the rotation behaviour above: any externally scheduled snapshot would
usually capture a credential that has already been superseded, and would
restore a dead token at exactly the moment it is needed. A sha256 marker
suppresses no-op writes, and is deliberately *not* recorded when the write
fails, so a failure cannot suppress every later retry.

**Rotate once a day, not once an hour.** `_withings_sync_due()` gates on a date
marker. Scale measurements arrive a few times a day at most, so hourly rotation
bought nothing while making the mirror expensive to keep current. The marker is
written on every *attempt* rather than on success, so a persistently failing
sync cannot spin hourly.

**Resolve the project by name, never by id.** The production host shares one
bootstrap token with a sibling deployment whose `bws.env` pins *its* project id.
Honouring an ambient `BWS_PROJECT_ID` would write this application's Withings
credential into the other project. `resolve_project_id()` therefore ignores it
and matches on name, mirroring the rule already enforced in `render_env.sh`.

**Bitwarden is optional.** Without a `bws` binary or access token, everything
still works; the credential just lives only in `tokens/`, with a warning. A
vault problem must never take down a sync that the local file can serve, so
`_run_bws()` never raises.

**`BWS_ACCESS_TOKEN` uses a new `@bootstrap` sentinel.** It is the credential
that unlocks Bitwarden, so it cannot be stored inside Bitwarden — `@bws` would
be a bootstrap paradox that fails the whole render. `@bootstrap` resolves from
the process environment, which `render_env.sh` has already populated from the
host bootstrap file. Unlike `@bws`, an unresolved `@bootstrap` renders empty
rather than aborting, because this feature is optional and must not be able to
block a deploy.

## Consequences

- A rebuilt host recovers the Withings credential automatically. The 30-second
  interactive flow is needed exactly once, ever.
- The refresh token rotates ~1×/day instead of ~24×/day.
- The container now ships the `bws` CLI (pinned to 2.1.0, matching the host)
  and receives `BWS_ACCESS_TOKEN`. This is a real, if marginal, privilege
  increase: the container already receives every project secret as environment
  variables, but *write* access to the vault is new. Judged acceptable because
  it is confined to a single key and is strictly optional.
- `bws` accepts secret values only as command-line arguments, so the credential
  is briefly visible in `/proc` to anyone who can already read the container's
  environment — i.e. to nobody who could not already read the credential.
  Values are passed as an argv list and never through a shell.
- **The machine account must be upgraded from "Can read" to "Can read, write"**
  on the `ai-health-coach` project, or pushes fail with a warning (seeding and
  the sync itself continue to work).

## Alternatives considered

- **A periodic snapshot of `tokens/` into the vault.** Rejected: the token
  rotates on every sync, so a snapshot taken out-of-band would routinely store
  a consumed credential — strictly worse than storing nothing, because it would
  restore a token that fails.
- **A host-side systemd path unit watching the file.** Rejected for the same
  race, plus it would put deployment logic outside the repository, which is the
  arrangement that let the original failure go unnoticed.
- **Leaving it manual and documenting the recovery.** Rejected: the failure mode
  is silent, and the documented recovery is the same 30-second window that
  failed the first time.
