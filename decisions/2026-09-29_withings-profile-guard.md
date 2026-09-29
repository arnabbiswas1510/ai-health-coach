# Pin the Withings sync to a single family profile

- **Date:** 2026-09-29
- **Status:** Accepted

## Context

The Withings account hosts four family profiles. `withings-sync` stores a
single credential at `tokens/.withings_user.json`, and that credential is bound
to exactly one profile via its `userid` field — the OAuth authorization screen
asks which profile to grant, and the resulting token can only read that
person's measurements.

Re-running the interactive authorization overwrites that file with whichever
profile was selected. Nothing in the system notices: the file is well-formed,
the sync succeeds, and the logs look normal.

The consequence is not a storage problem, it is a data-integrity one. The sync
would upload another family member's weight and body composition into *this*
athlete's Garmin Connect history. Garmin offers no clean bulk way to unpick
interleaved body-composition entries after the fact. Worse, those are exactly
the metrics the coach reads: weight loss toward ~160 lbs is the athlete's
first-priority goal, so corrupted weight data propagates into readiness scoring
and workout generation.

Two things made this newly reachable. First, `decisions/2026-09-29_withings-
credential-durability.md` added a Bitwarden mirror, so a wrong credential would
be pushed to the vault and become the copy a rebuilt host restores from —
making the mistake permanent rather than merely local. Second, the interactive
authorization command is now documented and known to work, so it is far more
likely to be re-run casually.

## Decision

Pin the deployment to one Withings profile and refuse to act on any other.

**Resolve the expected profile by trust-on-first-use, via the vault.**
`expected_userid()` prefers an explicit `WITHINGS_EXPECTED_USERID`, and
otherwise reads the `userid` out of the credential already stored in Bitwarden.
The vault copy is already the durable record of "whose scale this deployment
tracks", so reusing it needs no new state to keep in sync. With nothing stored
yet — the genuine first run — no constraint applies.

**Abort the sync, not just the push.** `userid_mismatch()` is checked in
`run_withings_sync()` *before* the Garmin login, because the upload is the
irreversible step. Guarding only the vault write would prevent the credential
from being stored while still letting the bad data reach Garmin, which is the
damage that actually matters.

**Also refuse the vault write.** `push_to_vault()` performs the same check, so
a mismatched credential can never replace the stored one even if the sync is
invoked by some other path.

**Provide a deliberate escape hatch.** `WITHINGS_ALLOW_USERID_CHANGE=true`
disables the check, for the legitimate case of genuinely moving the deployment
to a different profile. Without it, recovery is to delete the local file and
let it reseed from Bitwarden.

## Consequences

- Re-running the interactive authorization and selecting the wrong profile is
  now a loud, harmless no-op instead of a silent corruption of the athlete's
  Garmin history.
- The guard is inert when Bitwarden is unavailable and on the first ever run.
  This is deliberate: with no stored profile there is no basis on which to
  reject one, and failing closed would block the initial authorization.
- The error message names both profile ids and states the recovery, because
  this will be read months from now by someone who has forgotten the mechanism.
- Family-wide sync remains explicitly out of scope. Supporting it would require
  a separate Garmin account per person plus per-profile credentials; the
  application is single-athlete throughout (one `GARMIN_EMAIL`, one tokenstore,
  one LTHR).

## Alternatives considered

- **Hard-code the userid.** Rejected: it is deployment data, not source, and
  would have to be edited for any other user of this repository.
- **Guard only the vault write.** Rejected: it prevents the credential being
  persisted but still allows the bad upload, which is the irreversible half.
- **Refuse when the profile is unknown (fail closed).** Rejected: it would
  block the very first authorization, since nothing is stored at that point.
