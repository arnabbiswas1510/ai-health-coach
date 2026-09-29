"""Durable storage for the Withings OAuth credential.

withings-sync keeps its credential in ``<tokens>/.withings_user.json``. When
that file is absent the library falls back to prompting for an authorization
code on stdin, which a detached container cannot answer -- so the only recovery
is an interactive ``docker compose run`` with a 30-second window to paste the
code. That is a poor thing to depend on, and a lost ``tokens/`` directory or a
rebuilt host forces it every time.

This module makes the credential survive those events by mirroring it into the
same Bitwarden project that already holds every other production secret:

  * :func:`seed_from_vault` writes the file back if it is missing, so a fresh
    host needs no interaction at all.
  * :func:`push_to_vault` mirrors the file up whenever it changes.

**Why the push must be immediate.** ``WithingsOAuth2.__init__`` calls
``refresh_accesstoken()`` on every run and Withings returns a *new* refresh
token each time. A periodic snapshot would therefore usually restore a
superseded credential, which fails at exactly the moment it is needed. The push
runs in the same process that rotates the token so the vault copy is never
behind.

Bitwarden access is **optional**. Without a usable ``bws`` binary and access
token this degrades to local-only storage with a warning -- it never blocks a
sync, because the local file is authoritative.

Security note: ``bws`` accepts secret values only as command-line arguments, so
the credential is briefly visible in ``/proc`` to users who can already read the
container's environment. Values are passed as an argv list, never through a
shell, so they are not exposed to shell history or word splitting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SECRET_KEY = "WITHINGS_USER_JSON"
CREDENTIAL_FILENAME = ".withings_user.json"
DIGEST_FILENAME = ".withings_user.pushed-sha256"
DEFAULT_PROJECT_NAME = "ai-health-coach"

_BWS_TIMEOUT_SECONDS = 60


def credential_path(tokens_dir: str | os.PathLike[str]) -> Path:
    """Where withings-sync expects to find its credential."""
    return Path(tokens_dir) / CREDENTIAL_FILENAME


def _digest_path(tokens_dir: str | os.PathLike[str]) -> Path:
    return Path(tokens_dir) / DIGEST_FILENAME


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bws_binary() -> str | None:
    """Locate the bws CLI, mirroring scripts/render_env.sh's discovery order."""
    explicit = os.getenv("BWS_BIN", "")
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("bws")
    if found:
        return found
    fallback = Path.home() / "bin" / "bws"
    return str(fallback) if os.access(fallback, os.X_OK) else None


def vault_unavailable_reason() -> str | None:
    """Return why Bitwarden cannot be used, or None if it can."""
    if not os.getenv("BWS_ACCESS_TOKEN"):
        return "BWS_ACCESS_TOKEN is not set"
    if _bws_binary() is None:
        return "the bws CLI was not found (set BWS_BIN or install it on PATH)"
    return None


def _run_bws(args: list[str]) -> str | None:
    """Run bws and return stdout, or None if it failed.

    Never raises: Bitwarden is a convenience here, and a vault problem must not
    take down a sync that the local credential can satisfy on its own.
    """
    binary = _bws_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=_BWS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Withings vault: bws invocation failed: %s", exc)
        return None
    if result.returncode != 0:
        # stderr can echo the value on a failed write, so report only the code.
        logger.warning(
            "Withings vault: bws %s exited %d",
            args[0] if args else "?",
            result.returncode,
        )
        return None
    return result.stdout


def resolve_project_id() -> str | None:
    """Resolve the Bitwarden project by NAME.

    An explicit BWS_PROJECT_ID is deliberately ignored: the production host
    shares one bootstrap token with another application, whose bws.env pins
    *its* project id. Resolving by name keeps the two apart.
    """
    name = os.getenv("BWS_PROJECT_NAME", DEFAULT_PROJECT_NAME)
    raw = _run_bws(["project", "list", "-o", "json"])
    if raw is None:
        return None
    try:
        projects = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Withings vault: could not parse `bws project list` output")
        return None
    matches = [p for p in projects if p.get("name") == name]
    if len(matches) != 1:
        visible = ", ".join(sorted(str(p.get("name", "?")) for p in projects)) or "<none>"
        logger.warning(
            "Withings vault: expected exactly one Bitwarden project named %r, found %d "
            "(machine account can see: %s)",
            name,
            len(matches),
            visible,
        )
        return None
    return str(matches[0]["id"])


def _find_secret(project_id: str) -> dict | None:
    """Return the stored credential secret for this project, if present."""
    raw = _run_bws(["secret", "list", project_id, "-o", "json"])
    if raw is None:
        return None
    try:
        secrets = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Withings vault: could not parse `bws secret list` output")
        return None
    for secret in secrets:
        # Scope defensively: a shared token can surface other projects' keys.
        if secret.get("key") == SECRET_KEY and secret.get("projectId") == project_id:
            return secret
    return None


def seed_from_vault(tokens_dir: str | os.PathLike[str]) -> bool:
    """Restore the credential from Bitwarden when it is missing locally.

    Returns True only if a credential was actually written.
    """
    path = credential_path(tokens_dir)
    if path.exists():
        return False  # local file is authoritative; never overwrite it

    reason = vault_unavailable_reason()
    if reason:
        logger.warning(
            "Withings credential missing and it cannot be restored from Bitwarden (%s).",
            reason,
        )
        return False

    project_id = resolve_project_id()
    if project_id is None:
        return False

    secret = _find_secret(project_id)
    value = (secret or {}).get("value", "").strip()
    if not value:
        logger.warning(
            "Withings credential missing and Bitwarden holds no %s secret yet. "
            "Authorize once to create it.",
            SECRET_KEY,
        )
        return False

    try:
        json.loads(value)  # refuse to write a corrupt credential
    except json.JSONDecodeError:
        logger.warning(
            "Withings vault: %s does not contain valid JSON; refusing to write it.",
            SECRET_KEY,
        )
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    _digest_path(tokens_dir).write_text(_digest(value), encoding="utf-8")
    logger.info("Withings credential restored from Bitwarden into %s", path)
    return True


def push_to_vault(tokens_dir: str | os.PathLike[str]) -> bool:
    """Mirror the local credential into Bitwarden if it changed.

    Returns True only if the vault was actually written.
    """
    path = credential_path(tokens_dir)
    if not path.exists():
        return False

    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Withings vault: could not read %s: %s", path, exc)
        return False

    current = _digest(value)
    digest_file = _digest_path(tokens_dir)
    try:
        if digest_file.exists() and digest_file.read_text(encoding="utf-8").strip() == current:
            return False  # unchanged since the last successful push
    except OSError:
        pass  # an unreadable marker just means we push again

    reason = vault_unavailable_reason()
    if reason:
        logger.debug("Withings credential not mirrored to Bitwarden (%s).", reason)
        return False

    project_id = resolve_project_id()
    if project_id is None:
        return False

    existing = _find_secret(project_id)
    if existing and existing.get("id"):
        out = _run_bws(["secret", "edit", str(existing["id"]), "--value", value])
        action = "updated"
    else:
        out = _run_bws(["secret", "create", SECRET_KEY, value, project_id])
        action = "created"

    if out is None:
        logger.warning(
            "Withings vault: could not mirror the rotated credential to Bitwarden. "
            "The local copy is still valid, but a host rebuild would require "
            "re-authorizing. Check the machine account has write access."
        )
        return False

    try:
        digest_file.write_text(current, encoding="utf-8")
        digest_file.chmod(0o600)
    except OSError as exc:
        # Losing the marker only costs a redundant push next time.
        logger.debug("Withings vault: could not record push digest: %s", exc)

    logger.info("Withings credential %s in Bitwarden (%s).", action, SECRET_KEY)
    return True
