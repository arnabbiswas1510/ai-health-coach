# Dashboard shell moves out of the repository root into frontend/

- **Date:** 2026-09-29
- **Status:** Accepted

## Context

The dashboard shell lived at the repository root as `index.html`. Running any
static file server rooted at the repository then served that page instead of a
directory listing:

```
$ python3 -m http.server 8081     # expected: directory listing
                                  # actual:   the dashboard, broken
```

This is not a bug in the server. `SimpleHTTPRequestHandler` renders a listing
only for a directory that contains no `index.html`; when one exists it is
served instead. The root had one, so the listing was unreachable.

The page that got served was unusable, which made a documented default look
like an application fault:

- It was served from the repository root, but `analysis.html` and
  `planning.html` are generated into `data/`, so its links 404.
- Nothing proxies `/api/` to the chat-api on port 8001, so the feedback panel,
  manual WOTD trigger and every other `fetch()` fail.

The sibling `ai-trading-bot` repository has no HTML at its root -- its UI lives
in `frontend/` -- and a static server there lists files as expected. The
divergence was incidental rather than deliberate.

An earlier attempt fixed the symptom by adding a listing-only server
(`scripts/serve_listing.py`, never shipped). That was the wrong layer: it
required knowing to use a bespoke command, left the trap in place for anyone
reaching for the obvious one, and did nothing about the layout inconsistency
between the two repositories.

## Decision

Move the dashboard to `frontend/index.html`, matching `ai-trading-bot`.

Three references follow it:

| File | Was | Now |
|---|---|---|
| `Dockerfile` (build-hash input) | `/app/index.html` | `/app/frontend/index.html` |
| `startup.sh` (copy into data volume) | `/app/index.html` | `/app/frontend/index.html` |
| `cli/garmin_ai_coach_cli.py` | `Path("index.html")` | `Path("frontend/index.html")` |

Nothing else changes. The nginx `index index.html planning.html;` directive
refers to files inside the served data directory, not the repository, and is
unaffected. `local_dev_server.py` already serves from `data/` and proxies
`/api/`, so it remains the correct way to preview the dashboard.

## Consequences

**Positive**

- `python3 -m http.server` at the repository root now lists files, as it does
  in `ai-trading-bot`. Verified: the root response drops from 75,726 bytes (the
  dashboard) to a 3,253-byte listing, and `frontend/index.html` still serves
  the page when requested explicitly.
- No bespoke tooling to remember, and no misleading broken page.
- The two repositories now share a layout convention.

**Negative / accepted**

- Any bookmark or script referencing the root `index.html` in a checkout
  breaks. Runtime is unaffected: the file is copied to `data/index.html` at
  container start and nginx serves it from there, so the dashboard URL does
  not change.
- All three stale-path failures would have been quiet -- `startup.sh` and the
  CLI both guard with an existence check, and the Dockerfile's `sha256sum`
  falls back to a timestamp, which would silently force a full re-run on every
  build. Tests therefore pin each reference explicitly rather than relying on
  a build or startup failure to surface a mistake.

## Verification

`tests/test_dashboard_layout.py` asserts the dashboard exists under
`frontend/`, that no `.html` file sits at the repository root, that each of the
three references points at the new path, and that none still points at the old
one. Mutation-tested against the previous layout: five of six tests fail.
