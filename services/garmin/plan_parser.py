"""
Plan Parser: converts the AI weekly planner markdown output into structured
workout dicts that GarminCalendarSyncer can push to Garmin Connect.

Supported run types:
  - structured:  warmup + intervals (repeat groups) + cooldown
  - simple:      warmup + steady run + cooldown, HR zone target
  - long:        warmup + long easy run + cooldown, no HR target
  - rest:        no workout created (skipped)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Zone HR defaults (overridden per athlete at construction time)
# ---------------------------------------------------------------------------
_DEFAULT_ZONES: dict[str, tuple[float, float]] = {
    "Z1": (0.50, 0.60),
    "Z2": (0.60, 0.72),
    "Z3": (0.72, 0.82),
    "Z4": (0.82, 0.90),
    "Z5": (0.90, 1.00),
}


@dataclass
class ParsedWorkout:
    date_str: str                        # "YYYY-MM-DD"
    workout_name: str
    workout_type: str                    # "structured" | "simple" | "long" | "rest"
    estimated_duration_secs: int
    description: str = ""
    # Warmup / cooldown durations
    warmup_secs: float = 300.0
    cooldown_secs: float = 300.0
    # For simple / long runs
    run_secs: float = 0.0
    target_hr_min: float | None = None
    target_hr_max: float | None = None
    # For structured interval runs
    intervals: list[dict[str, Any]] = field(default_factory=list)
    # {iterations, work_secs, recovery_secs, hr_zone}


class PlanParser:
    """
    Parses the markdown weekly plan text (output of weekly_planner_node)
    into a list of ParsedWorkout objects, one per training day.

    Dates are inferred from the plan text (e.g. "Mon, Jun 02") combined
    with the start_date anchor.
    """

    # Regex: "Mon, Jun 02" or "Monday, Jun 2" or "Mon Jun 02"
    _DAY_RE = re.compile(
        r"^\s*\*{0,2}"
        r"(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|"
        r"Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)"
        r"[,\s]+([A-Za-z]+\.?\s+\d{1,2})",
        re.IGNORECASE | re.MULTILINE,
    )

    # "4x(5' Z4, 2' r)" or "3x(8'Z3, 3'rec)"
    _INTERVAL_RE = re.compile(
        r"(\d+)\s*[xX×]\s*[\(\[]?\s*(\d+)['′m]\s*(Z\d)\s*[,/]\s*(\d+)['′m]\s*r(?:ec(?:overy)?)?",
        re.IGNORECASE,
    )

    # Simple duration: "45'" or "45 min" or "45m"
    _DURATION_RE = re.compile(r"(\d+)\s*[\'′]?\s*(?:min(?:utes?)?)?", re.IGNORECASE)

    # Zone reference: Z2, Z3, Z4 etc.
    _ZONE_RE = re.compile(r"Z(\d)", re.IGNORECASE)

    # Rest day indicators
    _REST_RE = re.compile(r"\b(rest|off|recovery day|complete rest)\b", re.IGNORECASE)

    # Long run indicators
    _LONG_RE = re.compile(r"\b(long run|LR|long easy)\b", re.IGNORECASE)

    def __init__(self, max_hr: int = 167):
        """
        Args:
            max_hr: Athlete's estimated max heart rate (default 220-53=167).
        """
        self.max_hr = max_hr
        self._zones = {
            zone: (int(lo * max_hr), int(hi * max_hr))
            for zone, (lo, hi) in _DEFAULT_ZONES.items()
        }

    def parse_weekly_plan(
        self,
        plan_text: str,
        start_date: datetime | date | None = None,
    ) -> list[ParsedWorkout]:
        """
        Parse the 28-day plan markdown into a list of ParsedWorkout objects.
        Rest days are included with type='rest' so callers can skip them.

        Args:
            plan_text: Markdown string from weekly_planner_node output.
            start_date: The anchor date for week 1. Defaults to today.

        Returns:
            List of ParsedWorkout objects sorted by date.
        """
        if start_date is None:
            start_date = datetime.now().date()
        elif isinstance(start_date, datetime):
            start_date = start_date.date()

        workouts: list[ParsedWorkout] = []
        blocks = self._split_into_day_blocks(plan_text, start_date)

        for date_str, block_text in blocks:
            pw = self._parse_day_block(date_str, block_text)
            workouts.append(pw)
            logger.debug("Parsed %s: %s (%s)", date_str, pw.workout_name, pw.workout_type)

        return sorted(workouts, key=lambda w: w.date_str)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_into_day_blocks(
        self, text: str, start_date: date
    ) -> list[tuple[str, str]]:
        """
        Split plan text into (date_str, block_text) tuples.
        Uses a sliding window: each "Mon, Jun 02" header starts a new block.
        Dates not found in text are estimated by sequential offset from start_date.
        """
        lines = text.split("\n")
        blocks: list[tuple[str, str]] = []
        current_date_str: str | None = None
        current_lines: list[str] = []
        day_offset = 0

        for line in lines:
            m = self._DAY_RE.match(line)
            if m:
                # Save previous block
                if current_date_str is not None and current_lines:
                    blocks.append((current_date_str, "\n".join(current_lines)))

                # Parse the date from the matched text
                date_str = self._resolve_date(m.group(1), start_date, day_offset)
                current_date_str = date_str
                current_lines = [line]
                day_offset += 1
            elif current_date_str is not None:
                current_lines.append(line)

        # Don't forget the last block
        if current_date_str and current_lines:
            blocks.append((current_date_str, "\n".join(current_lines)))

        # If no day headers found, fall back: create 28 rest entries
        if not blocks:
            logger.warning("No day headers found in plan text; returning 28 rest days")
            for i in range(28):
                d = start_date + timedelta(days=i)
                blocks.append((d.strftime("%Y-%m-%d"), "REST"))

        return blocks

    def _resolve_date(self, date_text: str, start_date: date, offset: int) -> str:
        """
        Try to parse a date string like 'Jun 02' or 'Jun 2' relative to start_date's year.
        Falls back to start_date + offset days.
        """
        date_text = date_text.strip().rstrip(".")
        for fmt in ("%b %d", "%B %d", "%b. %d"):
            try:
                parsed = datetime.strptime(f"{date_text} {start_date.year}", f"{fmt} %Y")
                # If parsed date is earlier than start (e.g. year rollover), add a year
                if parsed.date() < start_date:
                    parsed = parsed.replace(year=start_date.year + 1)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Fallback: sequential offset
        fallback = start_date + timedelta(days=offset)
        return fallback.strftime("%Y-%m-%d")

    def _parse_day_block(self, date_str: str, block_text: str) -> ParsedWorkout:
        """Classify and extract a single day's workout from its text block."""
        text = block_text

        # 1. Rest day?
        if self._REST_RE.search(text):
            return ParsedWorkout(
                date_str=date_str,
                workout_name="Rest",
                workout_type="rest",
                estimated_duration_secs=0,
                description="Rest day",
            )

        # 2. Structured interval run? e.g. "4x(5' Z4, 2' r)"
        interval_match = self._INTERVAL_RE.search(text)
        if interval_match:
            return self._parse_structured(date_str, text, interval_match)

        # 3. Long run?
        if self._LONG_RE.search(text):
            return self._parse_long(date_str, text)

        # 4. Default: simple steady run
        return self._parse_simple(date_str, text)

    def _parse_structured(
        self, date_str: str, text: str, m: re.Match
    ) -> ParsedWorkout:
        """Parse a structured intervals workout."""
        iterations = int(m.group(1))
        work_mins = int(m.group(2))
        zone_str = m.group(3).upper()
        rec_mins = int(m.group(4))

        hr_min, hr_max = self._zones.get(zone_str, self._zones["Z4"])

        warmup_secs = 300.0
        cooldown_secs = 300.0
        work_secs = work_mins * 60.0
        rec_secs = rec_mins * 60.0
        total_secs = int(
            warmup_secs
            + iterations * (work_secs + rec_secs)
            + cooldown_secs
        )

        # Extract a workout name from surrounding text
        name = self._extract_name(text, fallback=f"{iterations}x{work_mins}' {zone_str} Intervals")

        return ParsedWorkout(
            date_str=date_str,
            workout_name=name,
            workout_type="structured",
            estimated_duration_secs=total_secs,
            description=self._extract_purpose(text),
            warmup_secs=warmup_secs,
            cooldown_secs=cooldown_secs,
            intervals=[{
                "iterations": iterations,
                "work_secs": work_secs,
                "recovery_secs": rec_secs,
                "hr_min": float(hr_min),
                "hr_max": float(hr_max),
            }],
        )

    def _parse_long(self, date_str: str, text: str) -> ParsedWorkout:
        """Parse a long run — duration-only, no HR target."""
        duration_secs = self._extract_duration_secs(text, default_mins=60)
        warmup_secs = 300.0
        cooldown_secs = 300.0
        run_secs = max(duration_secs - warmup_secs - cooldown_secs, duration_secs * 0.8)
        name = self._extract_name(text, fallback="Long Run")

        return ParsedWorkout(
            date_str=date_str,
            workout_name=name,
            workout_type="long",
            estimated_duration_secs=int(duration_secs),
            description=self._extract_purpose(text),
            warmup_secs=warmup_secs,
            cooldown_secs=cooldown_secs,
            run_secs=run_secs,
        )

    def _parse_simple(self, date_str: str, text: str) -> ParsedWorkout:
        """Parse a simple steady-state run with optional HR zone."""
        duration_secs = self._extract_duration_secs(text, default_mins=40)
        warmup_secs = 300.0
        cooldown_secs = 300.0
        run_secs = max(duration_secs - warmup_secs - cooldown_secs, duration_secs * 0.8)

        # Detect zone
        zone_m = self._ZONE_RE.search(text)
        hr_min: float | None = None
        hr_max: float | None = None
        if zone_m:
            zone_str = f"Z{zone_m.group(1)}"
            lo, hi = self._zones.get(zone_str, self._zones["Z2"])
            hr_min, hr_max = float(lo), float(hi)

        name = self._extract_name(text, fallback="Easy Run")

        return ParsedWorkout(
            date_str=date_str,
            workout_name=name,
            workout_type="simple",
            estimated_duration_secs=int(duration_secs),
            description=self._extract_purpose(text),
            warmup_secs=warmup_secs,
            cooldown_secs=cooldown_secs,
            run_secs=run_secs,
            target_hr_min=hr_min,
            target_hr_max=hr_max,
        )

    def _extract_duration_secs(self, text: str, default_mins: int = 40) -> float:
        """Find the first standalone duration in minutes and convert to seconds."""
        # Look for patterns like "45'", "45 min", "90 minutes"
        m = re.search(
            r"(\d+)\s*(?:\'|′|min(?:utes?)?)\b",
            text,
            re.IGNORECASE,
        )
        if m:
            return float(m.group(1)) * 60.0
        return float(default_mins * 60)

    def _extract_name(self, text: str, fallback: str) -> str:
        """Try to extract a short workout name from WORKOUT or FOCUS lines."""
        for pattern in [
            r"FOCUS[:\s]+(.+)",
            r"WORKOUT[:\s]+(.+)",
            r"\*\*FOCUS\*\*[:\s]+(.+)",
            r"\*\*WORKOUT\*\*[:\s]+(.+)",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip().split(".")[0].strip("*").strip()
                return name[:60]  # Garmin name limit is 64 chars
        return fallback

    def _extract_purpose(self, text: str) -> str:
        """Try to extract the PURPOSE line as a description."""
        m = re.search(r"PURPOSE[:\s]+(.+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip().strip("*")[:200]
        return ""
