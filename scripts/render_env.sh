#!/usr/bin/env bash
# Materialise the host .env from Bitwarden Secrets Manager + .env.template.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/pom/docker/garmin-ai-coach}"
TEMPLATE="${ENV_TEMPLATE:-$PROJECT_DIR/.env.template}"
OUT="${ENV_OUT:-$PROJECT_DIR/.env}"
RENDER_PY="${RENDER_PY:-$PROJECT_DIR/scripts/render_env.py}"
BWS_PROJECT_NAME="${BWS_PROJECT_NAME:-ai-health-coach}"
SENTINEL='@bws'

# Bootstrap token file search order. The shared location exists because several
# apps on this host authenticate as the same machine account; project scoping
# below is what keeps their secrets apart, not the token.
BOOTSTRAP_CANDIDATES=(
    "$HOME/.config/garmin-ai-coach/bws.env"
    "$HOME/.config/bws/bws.env"
)

log()  { printf '[render_env] %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

BWS_BIN="${BWS_BIN:-}"
if [ -z "$BWS_BIN" ]; then
    BWS_BIN="$(command -v bws || true)"
    [ -z "$BWS_BIN" ] && [ -x "$HOME/bin/bws" ] && BWS_BIN="$HOME/bin/bws"
fi
[ -n "$BWS_BIN" ] && [ -x "$BWS_BIN" ] || fail "bws binary not found (set BWS_BIN or install to ~/bin/bws)"

[ -f "$TEMPLATE" ] || fail "template not found: $TEMPLATE"
[ -f "$RENDER_PY" ] || fail "resolver not found: $RENDER_PY"

# An explicit BWS_ENV_FILE is honoured exclusively: silently falling back to a
# different token than the one the operator named would be worse than failing.
if [ -n "${BWS_ENV_FILE:-}" ]; then
    [ -f "$BWS_ENV_FILE" ] || fail "BWS_ENV_FILE set but not found: $BWS_ENV_FILE"
    BOOTSTRAP="$BWS_ENV_FILE"
else
    BOOTSTRAP=""
    for candidate in "${BOOTSTRAP_CANDIDATES[@]}"; do
        if [ -f "$candidate" ]; then
            BOOTSTRAP="$candidate"
            break
        fi
    done
    [ -n "$BOOTSTRAP" ] \
        || fail "no bootstrap token file found; looked in: ${BOOTSTRAP_CANDIDATES[*]}"
fi
log "bootstrap token from $BOOTSTRAP"

# Capture any deliberate environment override before sourcing, so a value in the
# (possibly shared) bootstrap file cannot clobber it.
BWS_PROJECT_ID_OVERRIDE="${BWS_PROJECT_ID:-}"

set -a
# shellcheck disable=SC1090
. "$BOOTSTRAP"
set +a
[ -n "${BWS_ACCESS_TOKEN:-}" ] || fail "BWS_ACCESS_TOKEN not set by $BOOTSTRAP"

# The bootstrap file may be shared with other apps on this host, and a sibling
# deployment (ai-trading-bot) stores its own BWS_PROJECT_ID alongside the token.
# Sourcing that would silently point this app at the wrong project, so only an
# explicit environment override counts; a value from the file is discarded.
if [ -n "${BWS_PROJECT_ID:-}" ] && [ "${BWS_PROJECT_ID:-}" != "$BWS_PROJECT_ID_OVERRIDE" ]; then
    log "ignoring BWS_PROJECT_ID from $BOOTSTRAP (it belongs to another app); resolving '$BWS_PROJECT_NAME' by name instead"
fi
BWS_PROJECT_ID="$BWS_PROJECT_ID_OVERRIDE"

# Scope the lookup to one project. An unscoped `bws secret list` returns every
# secret the machine account can reach, so a key of the same name in another
# project could be rendered into this .env.
if [ -z "${BWS_PROJECT_ID:-}" ]; then
    PROJECTS_JSON="$("$BWS_BIN" project list -o json)" \
        || fail "bws project list failed (token/connectivity?)"
    BWS_PROJECT_ID="$(BWS_PROJECTS_JSON="$PROJECTS_JSON" \
        python3 "$RENDER_PY" --resolve-project "$BWS_PROJECT_NAME")" \
        || fail "could not resolve Bitwarden project '$BWS_PROJECT_NAME'"
    log "using Bitwarden project '$BWS_PROJECT_NAME' ($BWS_PROJECT_ID)"
else
    log "using Bitwarden project id $BWS_PROJECT_ID (supplied via BWS_PROJECT_ID)"
fi
export BWS_PROJECT_ID

SECRETS_JSON="$("$BWS_BIN" secret list "$BWS_PROJECT_ID" -o json)" \
    || fail "bws secret list failed (token/connectivity?)"

TMP="$(mktemp "${OUT}.XXXXXX")" || fail "mktemp failed next to $OUT"
trap 'rm -f "$TMP"' EXIT

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
