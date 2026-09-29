# =============================================================================
# Garmin AI Coach — Multi-purpose Dockerfile
#
# Supports two deployment modes:
#
#   1. Classic multi-container (docker-compose.yml):
#      Each service overrides ENTRYPOINT at compose level.
#
#   2. Single-container NAS (docker-compose.nas.yml):
#      Uses startup.sh which runs: cleanup → coach analysis → nginx →
#      chat-api → daemon. nginx.nas.conf proxies /api/ to localhost:8001.
# =============================================================================

FROM python:3.13-slim

WORKDIR /app

# Install system dependencies:
#   build-essential — needed for some Python packages (e.g. numpy C extensions)
#   nginx           — serves the generated HTML dashboard in NAS mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    nginx \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Bitwarden Secrets Manager CLI.
#
# The daemon uses this to mirror the Withings OAuth credential into the vault.
# Withings rotates its refresh token on every sync, so the copy has to be
# written by the process that rotates it -- an external snapshot would capture
# a credential that is already superseded. Without this binary the daemon still
# works; it just falls back to local-only storage, so a wiped tokens/ directory
# would once again need a manual interactive re-authorization.
#
# Pinned to match the version already installed on the production host.
ARG BWS_VERSION=2.1.0
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) bws_arch="x86_64" ;; \
      arm64) bws_arch="aarch64" ;; \
      *) echo "unsupported architecture for bws: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/bws.zip \
      "https://github.com/bitwarden/sdk-sm/releases/download/bws-v${BWS_VERSION}/bws-${bws_arch}-unknown-linux-gnu-${BWS_VERSION}.zip"; \
    unzip -q -o /tmp/bws.zip -d /usr/local/bin; \
    rm -f /tmp/bws.zip; \
    chmod +x /usr/local/bin/bws; \
    bws --version

# Install Python dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure data and token directories exist inside the image
RUN mkdir -p /app/data /app/tokens

# ── NAS single-container assets ───────────────────────────────────────────────
# Install the NAS nginx config (proxies /api/ → localhost:8001 since
# chat-api lives in the same container, not a separate Docker host).
COPY nginx.nas.conf /etc/nginx/nginx.conf

# Install and make executable the container startup script
COPY startup.sh /app/startup.sh
RUN chmod +x /app/startup.sh

# Generate a build hash from ONLY the files whose changes require fresh HTML output.
# Narrowed to the dashboard and the two locked HTML template modules.
# Changes to other Python files (nodes, CLI, formatters, etc.) do NOT force a re-run.
# To force a re-run manually, set FORCE_ANALYTICS=true in your .env or docker-compose.
RUN sha256sum \
      /app/frontend/index.html \
      /app/services/ai/langgraph/nodes/planning_template.py \
      /app/services/ai/langgraph/nodes/analysis_template.py \
    > /app/build_hash.txt 2>/dev/null || \
    echo "build_hash_fallback_$(date +%s)" > /app/build_hash.txt

# ── Environment defaults ──────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV GARMINCONNECT_TOKENS=/app/tokens

# Commit this image was built from. CI passes --build-arg GIT_COMMIT=<sha>; the
# deploy then asserts the running container reports this exact value, which is
# what proves production actually consumed the freshly published image instead
# of silently restarting a stale one.
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Default entrypoint for classic mode (coach one-shot run).
# docker-compose.nas.yml overrides this via its `command` / entrypoint.
# startup.sh is the entrypoint for NAS single-container mode.
ENTRYPOINT ["python", "cli/garmin_ai_coach_cli.py"]
CMD ["--help"]
