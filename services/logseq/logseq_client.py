"""
services/logseq/logseq_client.py

Writes health metrics from Garmin Connect into the Logseq daily journal
via the Logseq HTTP API (port 12315).

Properties written to today's journal page (page-level, first block):
  sleep/duration    — total sleep in decimal hours  e.g. 7.5
  sleep/bed-time    — bed time as HH:MM (24h)       e.g. 23:30
  run/distance      — most recent run distance, km  e.g. 6.2
  run/avg-speed     — avg speed in min/km pace      e.g. 5.2  (min/km)
  run/avg-heart-rate— avg heart rate of last run    e.g. 152

Property names use hyphens (not slashes + slashes) because Logseq
strips trailing "/" from property keys in queries. The namespace prefix
(sleep/, run/) is preserved as part of the key string and works correctly
with Datalog queries and the Logseq Habit Tracker plugin.

Habit-tracker query example (table of sleep duration per day):
  #+BEGIN_QUERY
  {:title "Sleep Duration"
   :query [:find ?day ?dur
           :where
           [?p :block/journal-day ?day]
           [?p :block/properties ?props]
           [(get ?props :sleep/duration) ?dur]]}
  #+END_QUERY

The client is intentionally silent on failure — a Logseq sync error should
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

# ── Configuration ─────────────────────────────────────────────────────────────

# Host of the machine running Logseq. In production the server reaches the
# Windows host via the portproxy rule (127.0.0.1:12315 → Windows 12315).
# Override with LOGSEQ_HOST env var if the host IP is different.
_DEFAULT_HOST = os.environ.get("LOGSEQ_HOST", "http://host.docker.internal:12315")
_API_TIMEOUT  = int(os.environ.get("LOGSEQ_API_TIMEOUT", "5"))   # seconds


# ── Low-level API call ─────────────────────────────────────────────────────────

def _call(method: str, args: list[Any], host: str = _DEFAULT_HOST) -> Any:
    """Call the Logseq HTTP API and return the result, or None on error."""
    url = f"{host}/api"
    payload = {"method": method, "args": args}
    try:
        resp = httpx.post(url, json=payload, timeout=_API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        logger.warning("Logseq not reachable at %s — skipping journal sync", url)
        return None
    except Exception as exc:
        logger.warning("Logseq API error (%s): %s", method, exc)
        return None


# ── Journal page helpers ───────────────────────────────────────────────────────

def _journal_page_name(d: datetime.date | None = None) -> str:
    """Return today's journal page name in Logseq's default format, e.g. 'Jun 20th, 2026'."""
    if d is None:
        d = datetime.date.today()
    day = d.day
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day if day < 20 else day % 10, "th")
    return f"{d.strftime('%b')} {day}{suffix}, {d.year}"


def _get_or_create_page(page_name: str, host: str) -> dict | None:
    """Return the Logseq page object, creating it as a journal page if absent."""
    page = _call("logseq.Editor.getPage", [page_name], host)
    if page:
        return page
    # Try to create as journal page (isJournal=True)
    page = _call("logseq.Editor.createPage",
                 [page_name, {}, {"journal": True, "redirect": False}], host)
    return page


def _get_first_block(page_name: str, host: str) -> dict | None:
    """Return the first block of the page (where page-level properties live)."""
    blocks = _call("logseq.Editor.getPageBlocksTree", [page_name], host)
    if isinstance(blocks, list) and blocks:
        return blocks[0]
    return None


# ── Property helpers ───────────────────────────────────────────────────────────

def _upsert_property(block_uuid: str, prop: str, value: Any, host: str) -> None:
    """Set a single property on a block, overwriting any existing value."""
    _call("logseq.Editor.upsertBlockProperty", [block_uuid, prop, value], host)


def _format_pace(avg_speed_ms: float | None) -> float | None:
    """Convert Garmin average speed (m/s) to pace in min/km (decimal minutes)."""
    if not avg_speed_ms or avg_speed_ms <= 0:
        return None
    pace_sec_per_km = 1000.0 / avg_speed_ms
    return round(pace_sec_per_km / 60.0, 2)  # e.g. 5.75 means 5:45/km


def _format_bed_time(sleep_time_str: str | None) -> str | None:
    """Parse Garmin's sleepTime string (HH:MM:SS or HH:MM) → 'HH:MM' 24h."""
    if not sleep_time_str:
        return None
    m = re.match(r"(\d{2}):(\d{2})", sleep_time_str)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def write_daily_properties(
    *,
    sleep_duration_hours: float | None = None,
    sleep_bed_time: str | None = None,       # raw Garmin string e.g. "23:30:00"
    run_distance_km: float | None = None,
    run_avg_speed_ms: float | None = None,   # m/s → converted to min/km pace
    run_avg_heart_rate: int | None = None,
    date: datetime.date | None = None,
    host: str = _DEFAULT_HOST,
) -> bool:
    """Write Garmin health properties to the Logseq daily journal page.

    All arguments are optional — only non-None values are written.
    Returns True if at least one property was written successfully.

    Property keys written (Logseq namespace format, hyphen-separated):
      sleep/duration        decimal hours, e.g. 7.5
      sleep/bed-time        24h HH:MM string, e.g. "23:30"
      run/distance          km float, e.g. 6.2
      run/avg-speed         pace in min/km (decimal), e.g. 5.75
      run/avg-heart-rate    integer bpm, e.g. 152
    """
    page_name = _journal_page_name(date)
    logger.info("Logseq: targeting journal page '%s' at %s", page_name, host)

    page = _get_or_create_page(page_name, host)
    if page is None:
        logger.warning("Logseq: could not get/create page '%s'", page_name)
        return False

    first_block = _get_first_block(page_name, host)
    if first_block is None:
        logger.warning("Logseq: no blocks found on page '%s'", page_name)
        return False

    block_uuid = first_block.get("uuid")
    if not block_uuid:
        logger.warning("Logseq: first block has no uuid on page '%s'", page_name)
        return False

    # Build the properties dict — only include non-None values
    props: dict[str, Any] = {}

    if sleep_duration_hours is not None:
        props["sleep/duration"] = round(sleep_duration_hours, 2)

    bed_time_formatted = _format_bed_time(sleep_bed_time)
    if bed_time_formatted:
        props["sleep/bed-time"] = bed_time_formatted

    if run_distance_km is not None:
        props["run/distance"] = round(run_distance_km, 2)

    pace = _format_pace(run_avg_speed_ms)
    if pace is not None:
        props["run/avg-speed"] = pace

    if run_avg_heart_rate is not None:
        props["run/avg-heart-rate"] = int(run_avg_heart_rate)

    if not props:
        logger.info("Logseq: no properties to write — all values are None")
        return False

    written = 0
    for prop_key, prop_val in props.items():
        _upsert_property(block_uuid, prop_key, prop_val, host)
        logger.info("Logseq: wrote %s:: %s", prop_key, prop_val)
        written += 1

    logger.info("Logseq: wrote %d properties to '%s'", written, page_name)
    return written > 0
