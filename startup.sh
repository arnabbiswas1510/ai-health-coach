#!/bin/bash
# =============================================================================
# Garmin AI Coach — Single-Container Startup Script
# =============================================================================
# Startup sequence:
#   1. Clean stale HTML artifacts
#   2. Run coach analysis (ABORT with error on failure)
#   3. Start nginx in background
#   4. Start uvicorn chat-api in background
#   5. exec daemon.py as PID 1 (foreground, receives Docker stop signals)
# =============================================================================

set -euo pipefail

BOLD="\033[1m"
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RESET="\033[0m"

log()  { echo -e "${CYAN}[startup]${RESET} $*"; }
ok()   { echo -e "${GREEN}[startup] ✔${RESET} $*"; }
warn() { echo -e "${YELLOW}[startup] ⚠${RESET} $*"; }
die()  {
    echo -e ""
    echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${RED}${BOLD}║              GARMIN AI COACH — STARTUP FAILED                ║${RESET}"
    echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
    echo -e "${RED}${BOLD}  ERROR: $*${RESET}"
    echo -e ""
    echo -e "${YELLOW}  Possible causes:${RESET}"
    echo -e "    • Garmin tokens expired → run interactive login (see README)"
    echo -e "    • No network / Garmin Connect unreachable"
    echo -e "    • AI API key missing or quota exceeded (check GOOGLE_API_KEY)"
    echo -e "    • coach_config.yaml missing or invalid"
    echo -e ""
    echo -e "${YELLOW}  To recover:${RESET}"
    echo -e "    docker compose -f docker-compose.nas.yml run --rm ai-health-coach \\"
    echo -e "      python cli/garmin_ai_coach_cli.py --config /app/coach_config.yaml"
    echo -e ""
    exit 1
}

echo -e ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════════${RESET}"
echo -e "${CYAN}${BOLD}         🏃  Garmin AI Coach — Container Startup                ${RESET}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════════${RESET}"
echo -e ""

# ── Step 1: Clean stale HTML artifacts ────────────────────────────────────────
log "Step 1/5 — Cleaning stale HTML artifacts..."
DELETED=$(find /app/data -maxdepth 3 -name "*.html" -print -delete 2>/dev/null | wc -l)
ok "Removed ${DELETED} HTML file(s) from /app/data"

# ── Step 2: Run initial coach analysis ────────────────────────────────────────
log "Step 2/5 — Running AI coach analysis (this takes 2–5 minutes)..."
echo -e ""

if ! python cli/garmin_ai_coach_cli.py --config /app/coach_config.yaml; then
    die "Coach analysis failed (exit code $?). See error output above."
fi

echo -e ""
ok "Coach analysis completed — fresh HTML artifacts generated."

# ── Step 3: Start nginx ───────────────────────────────────────────────────────
log "Step 3/5 — Starting nginx..."

# Symlink /app/data as nginx web root so generated HTML is served directly
if [ ! -L /usr/share/nginx/html ]; then
    rm -rf /usr/share/nginx/html
    ln -s /app/data /usr/share/nginx/html
fi

# Test nginx config before starting
nginx -t 2>/dev/null || die "nginx configuration test failed. Check nginx.nas.conf."
nginx
ok "nginx started (serving on :80)"

# ── Step 4: Start Chat API ────────────────────────────────────────────────────
log "Step 4/5 — Starting Chat API on :8001..."
python -m uvicorn services.chat_api.main:app \
    --host 0.0.0.0 \
    --port 8001 \
    --log-level info \
    --no-access-log &
CHAT_PID=$!
sleep 2  # brief pause to let uvicorn bind its port

# Verify chat-api actually started
if ! kill -0 "$CHAT_PID" 2>/dev/null; then
    die "Chat API (uvicorn) failed to start. Check logs above."
fi
ok "Chat API started (PID ${CHAT_PID})"

# ── Step 5: Start Poller Daemon (foreground / PID 1) ─────────────────────────
log "Step 5/5 — Starting Garmin Poller Daemon (foreground)..."
echo -e ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  ✅ All services running. Dashboard → http://\$(hostname):8085  ${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════════════${RESET}"
echo -e ""

# exec replaces this shell — daemon.py becomes PID 1 and receives SIGTERM on
# `docker stop`, allowing graceful shutdown.
exec python -u daemon.py
