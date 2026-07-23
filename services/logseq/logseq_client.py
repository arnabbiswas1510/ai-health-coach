"""
services/logseq/logseq_client.py

Writes Garmin health metrics directly into Logseq daily journal .md files
via SSH/SFTP — no Logseq process required, no HTTP API, no Windows agent.

Architecture:
    container (DietPi)
      → SSH/SFTP → host machine (Windows / macOS / Linux)
        → journals/YYYY_MM_DD.md  (written/updated directly on disk)
          → Logseq picks it up automatically on next open

Migration to a new machine: update three env vars — nothing else.
No port forwarding rules. No Windows netsh. No Logseq settings to change.

Env vars (all from .env — never hard-coded):
  LOGSEQ_SSH_HOST      Hostname or IP of the host machine  (e.g. 192.168.1.17)
  LOGSEQ_SSH_USER      SSH username                        (e.g. arnab)
  LOGSEQ_SSH_PORT      SSH port, optional                  (default: 22)
  LOGSEQ_SSH_KEY_PATH  Private key on DietPi               (default: /root/.ssh/id_rsa)
  LOGSEQ_GRAPH_PATH    Absolute path to the Logseq graph root on the HOST machine:
                         macOS/Linux: /Users/arnab/Documents/Logseq
                         Windows:     C:/Users/arnab/Documents/Logseq
                       The bot appends  /journals/YYYY_MM_DD.md  automatically.

One-time host-machine setup (any OS):
  1. Enable SSH:
       macOS:   sudo systemsetup -setremotelogin on
       Windows: Settings → Optional Features → OpenSSH Server → Install + Start
       Linux:   (usually already on)
  2. Add DietPi's public key:
       cat /root/.ssh/id_rsa.pub   # on DietPi — copy this output
       # then append to ~/.ssh/authorized_keys on the host machine

Journal file format (Logseq page-level properties at top of file):
    sleep/duration:: 7.5
    sleep/bed-time:: 23:30
    sleep/wake-up-time:: 06:45
    sleep/quality:: 78
    run/distance:: 6.2
    run/avg-speed:: 5.75
    run/avg-heart-rate:: 152

Existing keys are updated in-place. New keys are prepended at the top.
Non-property content (notes, bullets) is preserved unchanged after the
property block.

Public API (same signatures as before — daemon.py needs no changes):
  build_props(...)             → dict  — convert raw Garmin values to props
  write_props_dict(...)        → bool  — write a pre-built props dict to a date
  write_daily_properties(...)  → bool  — convenience wrapper (build + write)
"""
from __future__ import annotations

import datetime
import logging
import os
import re
from typing import Any

import paramiko

logger = logging.getLogger(__name__)

# ── Configuration (from .env — never hard-code here) ─────────────────────────

_SSH_HOST     = os.environ.get("LOGSEQ_SSH_HOST", "")
_SSH_USER     = os.environ.get("LOGSEQ_SSH_USER", "")
_SSH_PORT     = int(os.environ.get("LOGSEQ_SSH_PORT", "22"))
_SSH_KEY_PATH = os.environ.get("LOGSEQ_SSH_KEY_PATH", "/root/.ssh/id_rsa")
_GRAPH_PATH   = os.environ.get("LOGSEQ_GRAPH_PATH", "")  # graph root, e.g. /Users/arnab/Logseq

# ── Journal path helper ───────────────────────────────────────────────────────

def _journal_sftp_path(date: datetime.date | None = None) -> str:
    """Return the SFTP path for the target journal file on the host machine."""
    d = date or datetime.date.today()
    filename = d.strftime("%Y_%m_%d") + ".md"
    graph = _GRAPH_PATH.rstrip("/\\").replace("\\", "/")
    return f"{graph}/journals/{filename}"


# ── Property file helpers ─────────────────────────────────────────────────────

def _is_property_line(line: str) -> bool:
    """True if the line is a Logseq page-level property (key:: value)."""
    return bool(re.match(r"^[a-zA-Z0-9_/\-].*::", line))


def _flatten_props(props: dict[str, Any]) -> dict[str, str]:
    """Flatten nested {'sleep': {'duration': 7.5}} → {'sleep/duration': '7.5'}.

    Also passes through already-flat keys like {'sleep/duration': 7.5} unchanged.
    """
    flat: dict[str, str] = {}
    for k, v in props.items():
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                flat[f"{k}/{sub_k}"] = str(sub_v)
        else:
            flat[k] = str(v)
    return flat


def _upsert_properties(content: str, flat_props: dict[str, str]) -> str:
    """Write/update page-level properties in a Logseq journal .md string.

    Strategy:
    - Lines at the top of the file that look like ``key:: value`` form the
      property block. All other lines are the body.
    - Existing property keys are updated in-place with the new value.
    - New keys are prepended before the existing property block.
    - Body content (notes, bullets) is preserved unchanged.
    """
    lines = content.splitlines(keepends=True)

    # Split into property block (top) and body (rest)
    prop_block: list[str] = []
    body: list[str] = []
    in_props = True
    for line in lines:
        stripped = line.rstrip("\n\r")
        if in_props and (not stripped or _is_property_line(stripped)):
            prop_block.append(line)
        else:
            in_props = False
            body.append(line)

    # Parse existing property keys → their current full "key:: value" strings
    existing: dict[str, str] = {}
    for line in prop_block:
        stripped = line.rstrip("\n\r")
        if _is_property_line(stripped):
            key = stripped.split("::")[0].strip()
            existing[key] = stripped

    # Merge: new values overwrite existing; new keys added
    merged = {**existing, **flat_props}
    prop_lines = [f"{v}\n" for v in merged.values()]

    # Reassemble: properties → (blank separator if body follows) → body
    separator = ["\n"] if body and prop_lines else []
    return "".join(prop_lines + separator + body)


# ── SSH/SFTP connection ───────────────────────────────────────────────────────

def _ssh_connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=_SSH_HOST,
        username=_SSH_USER,
        port=_SSH_PORT,
        key_filename=_SSH_KEY_PATH if os.path.exists(_SSH_KEY_PATH) else None,
        timeout=10,
        banner_timeout=10,
    )
    return client


def _write_via_sftp(props: dict[str, Any], date: datetime.date | None = None) -> bool:
    """SSH into the host machine and write/update the journal .md file directly.

    Returns True on success. Logs a clear warning and returns False on any
    failure — never raises, so it can never abort the main daemon pipeline.
    """
    if not _SSH_HOST or not _SSH_USER or not _GRAPH_PATH:
        logger.warning(
            "Logseq SSH writer not configured — set LOGSEQ_SSH_HOST, "
            "LOGSEQ_SSH_USER, LOGSEQ_GRAPH_PATH in .env."
        )
        return False

    flat = _flatten_props(props)
    if not flat:
        logger.info("Logseq: no properties to write")
        return False

    sftp_path = _journal_sftp_path(date)
    logger.info(
        "Logseq: writing %d properties to %s on %s@%s",
        len(flat), sftp_path, _SSH_USER, _SSH_HOST,
    )

    try:
        ssh = _ssh_connect()
        try:
            sftp = ssh.open_sftp()
            try:
                # Read the existing journal file (create empty string if new)
                try:
                    with sftp.file(sftp_path, "r") as fh:
                        existing_content = fh.read().decode("utf-8")
                    logger.debug("Logseq: read existing file %s", sftp_path)
                except FileNotFoundError:
                    existing_content = ""
                    logger.debug("Logseq: journal %s does not exist — will create", sftp_path)

                # Upsert properties into the file content
                updated_content = _upsert_properties(existing_content, flat)

                # Ensure journals/ directory exists on the remote host
                journals_dir = sftp_path.rsplit("/", 1)[0]
                try:
                    sftp.stat(journals_dir)
                except FileNotFoundError:
                    logger.info("Logseq: creating journals/ directory at %s", journals_dir)
                    sftp.mkdir(journals_dir)

                # Write back (overwrite the whole file — atomically safe for .md)
                with sftp.file(sftp_path, "w") as fh:
                    fh.write(updated_content.encode("utf-8"))

                logger.info(
                    "Logseq: ✓ wrote %d propert%s to %s — %s",
                    len(flat),
                    "y" if len(flat) == 1 else "ies",
                    sftp_path.split("/")[-1],
                    ", ".join(flat.keys()),
                )
                return True

            finally:
                sftp.close()
        finally:
            ssh.close()

    except paramiko.AuthenticationException:
        logger.warning(
            "Logseq SSH auth failed for %s@%s:%s — "
            "add DietPi's public key to ~/.ssh/authorized_keys on the host machine.\n"
            "  Run on DietPi:  cat %s  (copy that output)\n"
            "  Then on host:   echo '<paste>' >> ~/.ssh/authorized_keys",
            _SSH_USER, _SSH_HOST, _SSH_PORT, _SSH_KEY_PATH,
        )
        return False
    except (paramiko.SSHException, OSError) as exc:
        logger.warning(
            "Logseq SSH connection failed (%s@%s:%s): %s",
            _SSH_USER, _SSH_HOST, _SSH_PORT, exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Logseq: unexpected error writing journal: %s", exc)
        return False


# ── Garmin value formatters (pure helpers, no I/O) ───────────────────────────


def _format_time(raw: str | None) -> str | None:
    """Convert Garmin time value to display 'HH:MM', or None if invalid.

    Handles two formats Garmin returns:
      - 'HH:MM:SS' string  → strip seconds → 'HH:MM'
      - Unix epoch milliseconds (int or digit-only string, e.g. 1784597526000)
        → convert to local time → 'HH:MM'
    """
    if not raw:
        return None
    s = str(raw).strip()

    # Epoch milliseconds: all digits, length > 10 (ms timestamps are 13 digits)
    if s.isdigit() and len(s) > 10:
        try:
            import datetime as _dt
            ts = int(s) / 1000.0
            t = _dt.datetime.fromtimestamp(ts)
            return f"{t.hour:02d}:{t.minute:02d}"
        except Exception:
            return None

    # HH:MM:SS or HH:MM string
    parts = s.split(":")
    if len(parts) >= 2:
        try:
            return f"{int(parts[0]):02d}:{parts[1]}"
        except ValueError:
            return None
    return None


def _format_pace(speed_ms: float | None) -> float | None:
    """Convert m/s to decimal min/km pace (e.g. 2.78 m/s → 5.99 min/km)."""
    if speed_ms is None or speed_ms <= 0:
        return None
    pace_sec_per_km = 1000.0 / speed_ms
    return round(pace_sec_per_km / 60.0, 2)


# ── Public API ────────────────────────────────────────────────────────────────

def build_props(
    *,
    sleep_duration_hours: float | None = None,
    sleep_bed_time: str | None = None,       # raw Garmin string e.g. "23:30:00"
    sleep_wake_time: str | None = None,      # raw Garmin string e.g. "06:45:00"
    sleep_quality: int | None = None,        # Garmin overall sleep score 0-100
    run_distance_km: float | None = None,
    run_avg_speed_ms: float | None = None,   # m/s → converted to min/km pace
    run_avg_heart_rate: int | None = None,
) -> dict[str, Any]:
    """Convert raw Garmin values into a formatted Logseq properties dict.

    Only non-None values are included. The returned dict can be persisted
    and later passed to write_props_dict() to write to any past date.
    """
    props: dict[str, Any] = {"sleep": {}, "run": {}}

    if sleep_duration_hours is not None:
        props["sleep"]["duration"] = round(sleep_duration_hours, 2)

    t = _format_time(sleep_bed_time)
    if t:
        props["sleep"]["bed-time"] = t

    t = _format_time(sleep_wake_time)
    if t:
        props["sleep"]["wake-up-time"] = t

    if sleep_quality is not None:
        props["sleep"]["quality"] = int(sleep_quality)

    if run_distance_km is not None:
        props["run"]["distance"] = round(run_distance_km, 2)

    pace = _format_pace(run_avg_speed_ms)
    if pace is not None:
        props["run"]["avg-speed"] = pace

    if run_avg_heart_rate is not None:
        props["run"]["avg-heart-rate"] = int(run_avg_heart_rate)

    # Drop empty categories
    return {k: v for k, v in props.items() if v}


def write_props_dict(
    props: dict[str, Any],
    *,
    date: datetime.date | None = None,
) -> bool:
    """Write a pre-built props dict to the Logseq journal for a specific date.

    Args:
        props:  Formatted props dict (as returned by build_props()).
                Also accepts old flat-key format from queued entries:
                  {"sleep/duration": 7.5, "run/distance": 6.2}
        date:   Target journal date. Defaults to today. Pass a past date to
                backfill a missed sync (e.g. after the host machine was off).

    Returns True if the file was written successfully.
    """
    if not props:
        logger.info("Logseq: no properties to write — empty dict")
        return False

    # Normalize flat keys (backward-compat with old pending-sync queue entries)
    # e.g. "sleep/duration" → {"sleep": {"duration": ...}}
    # e.g. "sleep-duration" → {"sleep": {"duration": ...}}  (old hyphen style)
    normalized: dict[str, Any] = {}
    for k, v in props.items():
        if isinstance(v, dict):
            # Already nested — keep as-is
            normalized.setdefault(k, {}).update(v)
        else:
            # Flat key: split on "/" first, then on first "-"
            if "/" in k:
                cat, _, key = k.partition("/")
            elif "-" in k:
                parts = k.split("-", 1)
                cat, key = parts[0], parts[1]
            else:
                cat, key = "misc", k
            normalized.setdefault(cat, {})[key] = v

    page_name = (date or datetime.date.today()).strftime("%Y_%m_%d")
    logger.info(
        "Logseq: writing %d categories to journal '%s' via SSH direct-write",
        len(normalized), page_name,
    )
    return _write_via_sftp(normalized, date=date)


def write_daily_properties(
    *,
    sleep_duration_hours: float | None = None,
    sleep_bed_time: str | None = None,
    sleep_wake_time: str | None = None,
    sleep_quality: int | None = None,
    run_distance_km: float | None = None,
    run_avg_speed_ms: float | None = None,
    run_avg_heart_rate: int | None = None,
    date: datetime.date | None = None,
) -> bool:
    """Build and write health properties to today's (or a specific) Logseq journal.

    Convenience wrapper around build_props() + write_props_dict().
    """
    props = build_props(
        sleep_duration_hours=sleep_duration_hours,
        sleep_bed_time=sleep_bed_time,
        sleep_wake_time=sleep_wake_time,
        sleep_quality=sleep_quality,
        run_distance_km=run_distance_km,
        run_avg_speed_ms=run_avg_speed_ms,
        run_avg_heart_rate=run_avg_heart_rate,
    )
    if not props:
        logger.info("Logseq: no properties to write — all values are None")
        return False
    return write_props_dict(props, date=date)
