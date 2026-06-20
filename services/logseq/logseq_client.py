"""
services/logseq/logseq_client.py

Writes health metrics from Garmin Connect into the Logseq daily journal
by calling the windows_agent/logseq_writer.py HTTP receiver running on
the Windows machine. The agent writes directly to the journal .md files,
bypassing the Logseq HTTP API entirely (which requires auth in v0.10.x).

Architecture:
    container (192.168.1.50)
      → POST http://192.168.1.80:12316/health  (JSON health props)
        → windows_agent/logseq_writer.py  (running on Windows)
          → writes to C:\\Users\\arnab\\logseq\\journals\\YYYY_MM_DD.md

Properties written (Logseq page-level property format  key:: value):
  sleep/duration      decimal hours,    e.g. 7.5
  sleep/bed-time      24h HH:MM string, e.g. "23:30"
  sleep/wake-up-time  24h HH:MM string, e.g. "06:45"
  sleep/quality       integer 0-100     (Garmin overall sleep score)
  run/distance        km float,         e.g. 6.2
  run/avg-speed       min/km pace,      e.g. 5.75  (decimal, 5.75 = 5:45/km)
  run/avg-heart-rate  integer bpm,      e.g. 152

Logseq habit tracker query:
  #+BEGIN_QUERY
  {:title "Sleep + Run log"
   :query [:find ?day ?dur ?dist
           :where
           [?p :block/journal-day ?day]
           [?p :block/properties ?props]
           [(get ?props :sleep/duration) ?dur]
           [(get ?props :run/distance) ?dist]]}
  #+END_QUERY

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

# ── Configuration ─────────────────────────────────────────────────────────────

# URL of the windows_agent/logseq_writer.py HTTP server running on Windows.
# Port 12316 (separate from Logseq's own API port 12315).
# The netsh portproxy rule on Windows must forward 12316 → 127.0.0.1:12316.
_WRITER_HOST = os.environ.get("LOGSEQ_WRITER_HOST", "http://192.168.1.80:12316")
_API_TIMEOUT = int(os.environ.get("LOGSEQ_API_TIMEOUT", "5"))   # seconds


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

def write_daily_properties(
    *,
    sleep_duration_hours: float | None = None,
    sleep_bed_time: str | None = None,       # raw Garmin string e.g. "23:30:00"
    sleep_wake_time: str | None = None,      # raw Garmin string e.g. "06:45:00"
    sleep_quality: int | None = None,        # Garmin overall sleep score 0-100
    run_distance_km: float | None = None,
    run_avg_speed_ms: float | None = None,   # m/s → converted to min/km pace
    run_avg_heart_rate: int | None = None,
    date: datetime.date | None = None,       # defaults to today; unused here (agent writes to today)
    host: str = _WRITER_HOST,
) -> bool:
    """POST health properties to the Windows logseq_writer agent.

    All arguments are optional — only non-None values are included.
    Returns True if the agent accepted the data.
    """
    props: dict[str, Any] = {}

    if sleep_duration_hours is not None:
        props["sleep/duration"] = round(sleep_duration_hours, 2)

    t = _format_time(sleep_bed_time)
    if t:
        props["sleep/bed-time"] = t

    t = _format_time(sleep_wake_time)
    if t:
        props["sleep/wake-up-time"] = t

    if sleep_quality is not None:
        props["sleep/quality"] = int(sleep_quality)

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

    url = f"{host}/health"
    logger.info("Logseq: posting %d properties to %s", len(props), url)

    try:
        resp = httpx.post(url, json=props, timeout=_API_TIMEOUT)
        resp.raise_for_status()
        logger.info("Logseq: agent accepted — %s", resp.json())
        return True
    except httpx.ConnectError:
        logger.warning(
            "Logseq writer agent not reachable at %s "
            "— is windows_agent/logseq_writer.py running on the Windows machine?",
            url,
        )
        return False
    except Exception as exc:
        logger.warning("Logseq writer agent error: %s", exc)
        return False
