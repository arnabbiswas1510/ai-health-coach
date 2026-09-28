#!/usr/bin/env bash
# Materialise the host .env from Bitwarden Secrets Manager + .env.template.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/pom/docker/garmin-ai-coach}"
TEMPLATE="${ENV_TEMPLATE:-$PROJECT_DIR/.env.template}"
OUT="${ENV_OUT:-$PROJECT_DIR/.env}"
BOOTSTRAP="${BWS_ENV_FILE:-$HOME/.config/garmin-ai-coach/bws.env}"
SENTINEL='@bws'

log()  { printf '[render_env] %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

BWS_BIN="${BWS_BIN:-}"
if [ -z "$BWS_BIN" ]; then
    BWS_BIN="$(command -v bws || true)"
    [ -z "$BWS_BIN" ] && [ -x "$HOME/bin/bws" ] && BWS_BIN="$HOME/bin/bws"
fi
[ -n "$BWS_BIN" ] && [ -x "$BWS_BIN" ] || fail "bws binary not found (set BWS_BIN or install to ~/bin/bws)"

[ -f "$TEMPLATE" ] || fail "template not found: $TEMPLATE"
[ -f "$BOOTSTRAP" ] || fail "bootstrap token file not found: $BOOTSTRAP"

set -a
# shellcheck disable=SC1090
. "$BOOTSTRAP"
set +a
[ -n "${BWS_ACCESS_TOKEN:-}" ] || fail "BWS_ACCESS_TOKEN not set by $BOOTSTRAP"

SECRETS_JSON="$("$BWS_BIN" secret list -o json)" || fail "bws secret list failed (token/connectivity?)"

TMP="$(mktemp "${OUT}.XXXXXX")" || fail "mktemp failed next to $OUT"
trap 'rm -f "$TMP"' EXIT

RENDER_PY="${RENDER_PY:-$PROJECT_DIR/scripts/render_env.py}"
[ -f "$RENDER_PY" ] || fail "resolver not found: $RENDER_PY"
set +e
BWS_SECRETS_JSON="$SECRETS_JSON" python3 "$RENDER_PY" "$TEMPLATE" "$SENTINEL" > "$TMP" 2> "${TMP}.err"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
    log "$(cat "${TMP}.err" 2>/dev/null)"
    rm -f "${TMP}.err"
    fail "template resolution failed (rc=$rc); .env left unchanged"
fi
rm -f "${TMP}.err"

chmod 600 "$TMP"
mv "$TMP" "$OUT"
trap - EXIT
log "wrote $OUT ($(grep -c '=' "$OUT" || true) key lines)"
