"""
services/logseq/logseq_client.py

Writes health metrics from Garmin Connect into the Logseq daily journal
by calling the Logseq built-in HTTP API directly (enabled via
Settings → Features → Enable HTTP APIs server).

Architecture:
    container (192.168.1.50)
      → POST http://192.168.1.17:3000/api   (Logseq HTTP API, Bearer token)
        → Logseq (running on Windows machine 192.168.1.17)
          → upserts properties on the target journal page's first block

    NOTE: Logseq's API listens on 127.0.0.1:3000 by default.
    A portproxy rule on Windows must forward LAN → localhost:
        netsh interface portproxy add v4tov4 ^
            listenport=3001 listenaddress=0.0.0.0 ^
            connectport=3000 connectaddress=127.0.0.1
    And allow inbound in the firewall:
        New-NetFirewallRule -DisplayName "Logseq HTTP API" ^
            -Direction Inbound -LocalPort 3001 -Protocol TCP -Action Allow

Properties written (Logseq page-level property format  key:: value):
  sleep/duration      decimal hours,    e.g. 7.5
  sleep/bed-time      24h HH:MM string, e.g. "23:30"
  sleep/wake-up-time  24h HH:MM string, e.g. "06:45"
  sleep/quality       integer 0-100     (Garmin overall sleep score)
  run/distance        km float,         e.g. 6.2
  run/avg-speed       min/km pace,      e.g. 5.75  (decimal, 5.75 = 5:45/km)
  run/avg-heart-rate  integer bpm,      e.g. 152

Public API:
  build_props(...)         → dict  — convert raw Garmin values to formatted props
  write_props_dict(...)    → bool  — write a pre-built props dict to a specific date
  write_daily_properties(...)→bool — convenience wrapper (build + write in one call)

Environment variables:
  LOGSEQ_HOST         Base URL of the Logseq HTTP API  (defined in .env)
  LOGSEQ_API_TOKEN    Bearer token set in Logseq Settings → HTTP API → Authorization tokens
  LOGSEQ_API_TIMEOUT  Request timeout in seconds, default 5

The client is intentionally silent on failure — a sync error should
never abort the main pipeline.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Configuration (values come from .env — do NOT hard-code here) ────────────

_LOGSEQ_HOST  = os.environ.get("LOGSEQ_HOST", "")
_API_TOKEN    = os.environ.get("LOGSEQ_API_TOKEN", "")
_API_TIMEOUT  = int(os.environ.get("LOGSEQ_API_TIMEOUT", "5"))   # seconds

# NOTE: We validate _LOGSEQ_HOST lazily (inside _api_call) so that importing
# this module in tests or CI without a real Logseq instance does not crash.


# ── Logseq HTTP API helpers ────────────────────────────────────────────────────

def _api_call(client: httpx.Client, method: str, args: list[Any]) -> Any:
    """POST a single Logseq Plugin API call and return the parsed result."""
    if not _LOGSEQ_HOST:
        raise RuntimeError(
            "LOGSEQ_HOST env var is not set. "
            "Add it to your .env file, e.g.: LOGSEQ_HOST=http://192.168.1.17:3000"
        )
    resp = client.post(
        f"{_LOGSEQ_HOST}/api",
        json={"method": method, "args": args},
        headers={
            "Authorization": f"Bearer {_API_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=_API_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _journal_page_name(for_date: datetime.date | None = None) -> str:
    """Return the Logseq journal page name for a given date, e.g. 'Jun 20th, 2026'."""
    d = for_date or datetime.date.today()
    day = d.day
    # Ordinal suffix
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return d.strftime(f"%b {day}{suffix}, %Y")


def _get_journal_first_block_uuid(
    client: httpx.Client,
    page_name: str,
) -> str | None:
    # Deprecated: kept for backwards compatibility if needed, but not used by write_props_dict
    pass

def _ensure_journal_page(client: httpx.Client, page_name: str) -> str | None:
    """
    Ensure the journal page exists and return the UUID of the root block.
    This creates an independent block (sibling to the first block) so it doesn't
    overwrite existing page bullets or properties.
    """
    try:
        blocks = _api_call(client, "logseq.Editor.getPageBlocksTree", [page_name])
        if blocks and isinstance(blocks, list) and len(blocks) > 0:
            # Check if any block already is our sync root
            for block in blocks:
                content = block.get("content", "")
                if "Garmin Health Sync" in content:
                    logger.debug("Logseq: found existing health root block for '%s'", page_name)
                    return block.get("uuid")
            
            # If not, create a new block after the first block
            first_uuid = blocks[0].get("uuid")
            if first_uuid:
                result = _api_call(client, "logseq.Editor.insertBlock", [first_uuid, "Garmin Health Sync", {"sibling": True}])
                if result and isinstance(result, dict):
                    uuid = result.get("uuid")
                    logger.info("Logseq: created health root block %s on '%s'", uuid, page_name)
                    return uuid
    except Exception as exc:
        logger.debug("Logseq: could not get blocks for '%s': %s", page_name, exc)

    # Page doesn't exist yet — create it
    logger.info("Logseq: journal page '%s' not found — creating it", page_name)
    try:
        result = _api_call(client, "logseq.Editor.appendBlockInPage", [page_name, "Garmin Health Sync"])
        if result and isinstance(result, dict):
            return result.get("uuid")
    except Exception as exc:
        logger.warning("Logseq: could not create journal page '%s': %s", page_name, exc)

    return None


# ── Property value formatters ──────────────────────────────────────────────────

def _format_pace(avg_speed_ms: float | None) -> float | None:
    """Convert Garmin average speed (m/s) to pace in min/km (decimal minutes)."""
    if not avg_speed_ms or avg_speed_ms <= 0:
        return None
    pace_sec_per_km = 1000.0 / avg_speed_ms
    return round(pace_sec_per_km / 60.0, 2)  # e.g. 5.75 means 5:45/km


def _format_time(time_str: str | None) -> str | None:
    """Parse a Garmin time string (HH:MM:SS or HH:MM or epoch-ms) → 'HH:MM'."""
    if not time_str:
        return None
    # Try HH:MM or HH:MM:SS
    m = re.match(r"(\d{2}):(\d{2})", str(time_str))
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    # Try epoch ms (numeric string)
    try:
        import datetime as _dt
        ts = int(time_str)
        if ts > 1_000_000_000_000:  # ms
            ts //= 1000
        return _dt.datetime.fromtimestamp(ts).strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

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

    # Remove empty categories
    return {k: v for k, v in props.items() if v}


def write_props_dict(
    props: dict[str, Any],
    *,
    date: datetime.date | None = None,
) -> bool:
    """Write a pre-built props dict to the Logseq journal for a specific date.

    Args:
        props:  Formatted props dict (as returned by build_props()).
        date:   Target journal date. Defaults to today. Pass a past date to
                backfill a missed sync (e.g. after a vacation with Logseq closed).

    Returns True if all properties were accepted by Logseq.
    """
    if not props:
        logger.info("Logseq: no properties to write — empty dict")
        return False

    # Normalize flat properties (e.g. from old queue: "sleep-duration": 7.5) to nested format
    normalized_props = {}
    for k, v in props.items():
        if isinstance(v, dict):
            if k not in normalized_props:
                normalized_props[k] = {}
            normalized_props[k].update(v)
        else:
            cat = "misc"
            key = k
            if "/" in k:
                parts = k.split("/")
                cat = parts[0].strip()
                key = parts[-1].strip()
            elif "-" in k:
                parts = k.split("-")
                cat = parts[0].strip()
                key = "-".join(parts[1:]).strip()
                
            if cat not in normalized_props:
                normalized_props[cat] = {}
            normalized_props[cat][key] = v
            
    props = normalized_props

    page_name = _journal_page_name(date)
    logger.info(
        "Logseq: writing %d properties to journal '%s' via HTTP API at %s",
        len(props), page_name, _LOGSEQ_HOST,
    )

    try:
        with httpx.Client() as client:
            block_uuid = _ensure_journal_page(client, page_name)
            if not block_uuid:
                logger.warning(
                    "Logseq: could not obtain first block UUID for '%s' — "
                    "is Logseq running and is the HTTP API enabled? "
                    "(Settings → Features → Enable HTTP APIs server)",
                    page_name,
                )
                return False

            failed: list[str] = []
            
            # Get existing children to avoid duplicates
            cat_uuid_map = {}
            block_data = _api_call(client, "logseq.Editor.getBlock", [block_uuid, {"includeChildren": True}])
            if block_data and isinstance(block_data, dict):
                children = block_data.get("children", [])
                for child in children:
                    child_uuid = None
                    if isinstance(child, list) and len(child) == 2 and child[0] == "uuid":
                        child_uuid = child[1]
                    elif isinstance(child, dict):
                        child_uuid = child.get("uuid")
                        
                    if child_uuid:
                        child_block = _api_call(client, "logseq.Editor.getBlock", [child_uuid])
                        if child_block and isinstance(child_block, dict):
                            content = child_block.get("content", "")
                            for cat in props.keys():
                                if content.startswith(f"{cat}::"):
                                    cat_uuid_map[cat] = child_uuid

            for category, category_props in props.items():
                try:
                    cat_uuid = cat_uuid_map.get(category)
                    if not cat_uuid:
                        # Create the category block as a child of the root block
                        cat_block = _api_call(
                            client, 
                            "logseq.Editor.insertBlock", 
                            [block_uuid, f"{category}:: ", {"sibling": False}]
                        )
                        cat_uuid = cat_block.get("uuid") if cat_block else None

                    if not cat_uuid:
                        continue
                        
                    for key, value in category_props.items():
                        _api_call(
                            client,
                            "logseq.Editor.upsertBlockProperty",
                            [cat_uuid, key, value],
                        )
                        logger.debug("Logseq: wrote %s=%s on block %s", key, value, cat_uuid)
                except Exception as exc:
                    logger.warning("Logseq: failed to write category %s: %s", category, exc)
                    failed.append(category)

            if failed:
                logger.warning("Logseq: %d categories failed: %s", len(failed), failed)
                return False

            logger.info(
                "Logseq: successfully wrote %d categories to '%s'",
                len(props), page_name,
            )
            return True

    except httpx.ConnectError:
        logger.warning(
            "Logseq HTTP API not reachable at %s/api — "
            "is Logseq running, the HTTP API enabled, and port 3001 "
            "forwarded via netsh portproxy?",
            _LOGSEQ_HOST,
        )
        return False
    except Exception as exc:
        logger.warning("Logseq HTTP API error: %s", exc)
        return False


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
    For backfilling missed syncs, prefer calling both separately so you can
    persist the props dict before the write attempt.
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
