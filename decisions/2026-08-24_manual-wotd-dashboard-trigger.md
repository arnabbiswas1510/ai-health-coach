# 2026-08-24 — Manual WOTD Dashboard Trigger

**Status:** Accepted

## Context

The dashboard already exposes the generated reports and a chat-driven replan flow, but there was no direct UI control to force a fresh Workout of the Day outside the daemon's hourly polling window.

The repository already includes `force_wotd.py`, which clears the WOTD markers and pushes a workout immediately. The missing piece was a safe dashboard-to-backend path for invoking it.

## Decision

Add a manual WOTD trigger flow with these properties:

1. The landing page (`index.html`) gets a dedicated "Manual Workout of the Day" widget.
2. The widget calls new FastAPI endpoints in `services/chat_api/main.py`:
   - `POST /wotd/trigger`
   - `GET /wotd/trigger/status`
3. The backend launches `force_wotd.py` in a detached background process, records its PID and state in the shared data directory, and refuses to start a second run while the current one is still active.
4. Trigger progress is written to `wotd_trigger.log`, which is linked directly from the dashboard.

## Consequences

- The manual trigger works in the same nginx `/api/` proxy path as the existing chat widget, so it fits the current UI deployment model without adding a new service.
- The PID/state files prevent accidental duplicate manual triggers from the dashboard.
- The UI can show whether a trigger is idle, starting, running, finished, or failed without reloading the full page.
- Completion is inferred from process liveness plus the persisted trigger state; detailed execution output remains in the log file.
