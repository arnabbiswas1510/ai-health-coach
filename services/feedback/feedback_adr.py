"""Athlete-authored daily feedback, captured as recency-weighted ADRs.

The athlete writes a free-text note from the dashboard ("knee twinged at km 4",
"skipped it, work ran late"). One fast LLM call turns that note into a
structured ADR which is persisted to::

    data/<athlete>/feedback_decisions/YYYY-MM-DD_<slug>.md

Each ADR carries YAML front matter (id, date, category, severity, status,
timing, coaching_directive) followed by the human-readable body. Newer entries
may mark older entries in the same category as ``superseded`` — a "knee is fine
now" note retires the earlier "knee pain" note rather than fighting with it.

Every morning :mod:`services.garmin.wotd_generator` calls
:func:`load_weighted_feedback` to pull the active entries from the last 21 days,
newest first, each weighted by exponential recency decay (0.85 ** days_ago) —
the same decay the run baseline already uses, so the two signals age at the
same rate.

Feedback is ADVISORY AND BOUNDED. It may make a workout easier, shorter or
change its format, but it can never override the walk-break rule, the 5-minute
warmup cap, the duration caps or the LTHR-derived HR zones. That guard lives in
the WOTD prompt (Rule 12), not here.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Vocabulary ──────────────────────────────────────────────────────────────
ACTIVE = "active"
SUPERSEDED = "superseded"

CATEGORIES = (
    "injury",
    "fatigue",
    "missed-workout",
    "nutrition",
    "motivation",
    "logistics",
    "performance",
    "other",
)

SEVERITIES = ("low", "medium", "high")

#: Categories where a newer note genuinely retires the older one. A second
#: "missed workout" note is a *separate* event and must not erase the first.
SUPERSEDING_CATEGORIES = frozenset({"injury", "fatigue", "motivation", "performance"})

# ── Recency weighting ───────────────────────────────────────────────────────
WINDOW_DAYS = 21
MAX_ENTRIES = 10
DECAY_FACTOR = 0.85

# ── Timing tags (auto-detected, never asked of the athlete) ─────────────────
TIMING_PRE_WOTD = "pre-workout"
TIMING_POST_RUN = "post-run"
TIMING_NO_RUN_YET = "workout-issued-not-yet-run"

_TIMING_HINTS = {
    TIMING_PRE_WOTD: (
        "Written BEFORE today's workout was issued — treat as a heads-up that "
        "should shape the very next workout."
    ),
    TIMING_POST_RUN: (
        "Written AFTER completing a run — treat as a retrospective report on "
        "how that workout actually felt."
    ),
    TIMING_NO_RUN_YET: (
        "Written after the workout was issued but with no run logged yet — "
        "often explains a skipped or deferred session."
    ),
}


@dataclass
class FeedbackADR:
    """One athlete feedback entry."""

    id: str
    date: date
    created_at: str
    title: str
    category: str
    severity: str
    status: str
    timing: str
    insight: str
    coaching_directive: str
    raw_text: str
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    path: Path | None = None
    weight: float = 1.0

    def to_front_matter(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "created_at": self.created_at,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "timing": self.timing,
            "supersedes": list(self.supersedes),
            "superseded_by": self.superseded_by,
        }

    def to_api_dict(self) -> dict[str, Any]:
        payload = self.to_front_matter()
        payload.update(
            {
                "insight": self.insight,
                "coaching_directive": self.coaching_directive,
                "raw_text": self.raw_text,
                "weight": round(self.weight, 4),
            }
        )
        return payload


# ---------------------------------------------------------------------------
# Paths and slugs
# ---------------------------------------------------------------------------

def feedback_dir(user_data_dir: Path) -> Path:
    return Path(user_data_dir) / "feedback_decisions"


def _slugify(text: str, max_len: int = 48) -> str:
    normalised = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalised).strip("-").lower()
    slug = slug[:max_len].strip("-")
    return slug or "feedback"


# ---------------------------------------------------------------------------
# ADR serialisation (YAML front matter + markdown body)
# ---------------------------------------------------------------------------

def _dump_front_matter(data: dict[str, Any]) -> str:
    """Serialise front matter without requiring a YAML round-trip on read."""
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                rendered = ", ".join(json.dumps(v) for v in value)
                lines.append(f"{key}: [{rendered}]")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {json.dumps(str(value))}")
    lines.append("---")
    return "\n".join(lines)


def _render_adr(adr: FeedbackADR) -> str:
    return f"""{_dump_front_matter(adr.to_front_matter())}

# {adr.title}

**Date:** {adr.date.isoformat()}  |  **Category:** {adr.category}  |  \
**Severity:** {adr.severity}  |  **Status:** {adr.status}  |  **Timing:** {adr.timing}

## Athlete said

> {adr.raw_text.strip()}

## Insight

{adr.insight.strip()}

## Coaching directive

{adr.coaching_directive.strip()}
"""


def _parse_front_matter(front_raw: str) -> dict[str, Any]:
    """Parse the simple key/value front matter written by :func:`_dump_front_matter`."""
    front: dict[str, Any] = {}
    for line in front_raw.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                front[key] = json.loads(value)
            except Exception:
                front[key] = []
        elif value == "null":
            front[key] = None
        else:
            try:
                front[key] = json.loads(value)
            except Exception:
                front[key] = value.strip('"')
    return front


def _parse_adr(path: Path) -> FeedbackADR | None:
    """Parse an ADR file back into a :class:`FeedbackADR`."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Feedback: could not read %s: %s", path, exc)
        return None

    if not text.startswith("---"):
        logger.warning("Feedback: %s has no front matter — skipping.", path)
        return None

    _, _, remainder = text.partition("---\n")
    front_raw, _, body = remainder.partition("\n---")
    front = _parse_front_matter(front_raw)

    def _section(name: str) -> str:
        match = re.search(rf"^## {name}\n(.*?)(?=\n## |\Z)", body, re.S | re.M)
        return match.group(1).strip() if match else ""

    raw_text = _section("Athlete said")
    raw_text = "\n".join(
        line.lstrip("> ").rstrip() for line in raw_text.splitlines()
    ).strip()

    try:
        entry_date = date.fromisoformat(str(front.get("date", "")))
    except ValueError:
        logger.warning("Feedback: %s has an unparseable date — skipping.", path)
        return None

    return FeedbackADR(
        id=str(front.get("id") or path.stem),
        date=entry_date,
        created_at=str(front.get("created_at") or ""),
        title=str(front.get("title") or path.stem),
        category=str(front.get("category") or "other"),
        severity=str(front.get("severity") or "low"),
        status=str(front.get("status") or ACTIVE),
        timing=str(front.get("timing") or TIMING_PRE_WOTD),
        insight=_section("Insight"),
        coaching_directive=_section("Coaching directive"),
        raw_text=raw_text,
        supersedes=list(front.get("supersedes") or []),
        superseded_by=front.get("superseded_by"),
        path=path,
    )


def _write_adr(adr: FeedbackADR, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_adr(adr), encoding="utf-8")
    adr.path = path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_feedback_adrs(
    user_data_dir: Path,
    include_superseded: bool = False,
) -> list[FeedbackADR]:
    """Load all feedback ADRs, newest first."""
    directory = feedback_dir(user_data_dir)
    if not directory.exists():
        return []

    entries: list[FeedbackADR] = []
    for path in directory.glob("*.md"):
        adr = _parse_adr(path)
        if adr is None:
            continue
        if not include_superseded and adr.status != ACTIVE:
            continue
        entries.append(adr)

    entries.sort(key=lambda a: (a.created_at or a.date.isoformat()), reverse=True)
    return entries


def load_weighted_feedback(
    user_data_dir: Path,
    today: date | None = None,
    window_days: int = WINDOW_DAYS,
    max_entries: int = MAX_ENTRIES,
    decay: float = DECAY_FACTOR,
) -> list[FeedbackADR]:
    """Return active feedback from the recency window, newest first, weighted.

    Weight is ``decay ** days_ago`` so a note written today counts fully and a
    three-week-old note counts for very little. Entries outside the window are
    dropped entirely; the newest ``max_entries`` survive the cap.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=window_days)

    weighted: list[FeedbackADR] = []
    for adr in load_feedback_adrs(user_data_dir):
        if adr.date < cutoff or adr.date > today:
            continue
        days_ago = max((today - adr.date).days, 0)
        adr.weight = decay**days_ago
        weighted.append(adr)

    weighted.sort(key=lambda a: (a.date, a.created_at), reverse=True)
    return weighted[:max_entries]


def render_feedback_prompt_block(entries: list[FeedbackADR]) -> str:
    """Render weighted feedback as a prompt section for the WOTD AI."""
    if not entries:
        return (
            "\nATHLETE FEEDBACK: None recorded in the last "
            f"{WINDOW_DAYS} days — design from the physiological signals alone."
        )

    lines = [
        "",
        f"ATHLETE FEEDBACK (newest first — the athlete's own words, last {WINDOW_DAYS} days):",
        "  Weight shows how much each note should count today (1.00 = written today,",
        "  decaying by 0.85 per day). Honour the highest-weighted notes first; where two",
        "  notes conflict, the newer one wins.",
    ]

    for idx, adr in enumerate(entries, start=1):
        days_ago = (date.today() - adr.date).days
        when = "today" if days_ago == 0 else f"{days_ago}d ago"
        lines.append(
            f"\n  {idx}. [{when} | weight {adr.weight:.2f} | {adr.category} | "
            f"severity {adr.severity}] {adr.title}"
        )
        lines.append(f'       Athlete said: "{adr.raw_text.strip()}"')
        if adr.insight:
            lines.append(f"       Insight: {adr.insight.strip()}")
        if adr.coaching_directive:
            lines.append(f"       Directive: {adr.coaching_directive.strip()}")
        hint = _TIMING_HINTS.get(adr.timing)
        if hint:
            lines.append(f"       Context: {hint}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Timing auto-detection
# ---------------------------------------------------------------------------

def detect_timing(user_data_dir: Path, today: date | None = None) -> str:
    """Infer whether a note is a pre-workout heads-up or a post-run report.

    Derived purely from state the daemon already persists — the athlete is
    never asked. A run logged today means the note is retrospective; a WOTD
    issued today with no run yet usually means a skipped or deferred session.
    """
    today = today or date.today()
    user_data_dir = Path(user_data_dir)

    last_run = _read_json(user_data_dir / "last_run.json")
    if last_run.get("date") == today.isoformat():
        return TIMING_POST_RUN

    wotd = _read_json(user_data_dir / "wotd_today.json")
    if wotd.get("date") == today.isoformat():
        return TIMING_NO_RUN_YET

    pushed = user_data_dir / "last_pushed_wotd_date.txt"
    try:
        if pushed.exists() and pushed.read_text(encoding="utf-8").strip() == today.isoformat():
            return TIMING_NO_RUN_YET
    except Exception:
        pass

    return TIMING_PRE_WOTD


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.debug("Feedback: could not read %s: %s", path, exc)
    return {}


# ---------------------------------------------------------------------------
# Classification (one fast LLM call)
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """You are the analytical layer of a running coach AI. The athlete has \
just written a short free-text note about their training day. Convert it into a \
structured decision record the coach AI will read tomorrow morning when designing \
the next workout.

ATHLETE CONTEXT:
  Goals, in priority order: (1) weight loss toward 160 lbs, (2) running endurance,
  (3) knee protection. Trains in a walk-run format with heart-rate-based targets.

WHEN THIS NOTE WAS WRITTEN: {timing_hint}

ATHLETE'S NOTE:
\"\"\"{text}\"\"\"

CURRENTLY ACTIVE FEEDBACK RECORDS (id | category | title):
{active_list}

Return ONLY valid JSON, no markdown fence, no commentary:
{{
  "title": "short imperative summary, max 8 words",
  "category": "one of: {categories}",
  "severity": "one of: low, medium, high",
  "insight": "1-2 sentences interpreting what this means for training",
  "coaching_directive": "one concrete, actionable instruction for tomorrow's workout design",
  "supersedes": ["id of any active record above that this note makes obsolete"]
}}

Rules:
- "supersedes" must contain ids copied EXACTLY from the active list, or be empty.
  Only supersede a record when this note genuinely resolves or replaces it
  (e.g. "knee feels fine now" supersedes an earlier knee-pain record).
  Never supersede a record from a different category.
- severity "high" is reserved for pain, injury, illness or three-or-more missed sessions.
- The coaching directive may make a workout easier, shorter, or change its format.
  It must NEVER instruct the coach to raise heart-rate zones, extend the warmup
  beyond 5 minutes, exceed the daily duration cap, or skip walk breaks.
"""


def _default_classification(text: str, reason: str) -> dict[str, Any]:
    """Deterministic fallback so a failed LLM call never loses the athlete's words."""
    logger.warning("Feedback: falling back to unclassified record (%s).", reason)
    summary = " ".join(text.split())
    return {
        "title": (summary[:60] + "…") if len(summary) > 60 else (summary or "Athlete feedback"),
        "category": "other",
        "severity": "low",
        "insight": "Automatic classification unavailable; the athlete's raw note is preserved verbatim.",
        "coaching_directive": "Read the athlete's note directly and account for it in today's design.",
        "supersedes": [],
    }


def _classify_feedback(
    text: str,
    timing: str,
    active: list[FeedbackADR],
    llm: Any | None = None,
) -> dict[str, Any]:
    active_list = (
        "\n".join(f"  {a.id} | {a.category} | {a.title}" for a in active) or "  (none)"
    )
    prompt = _CLASSIFY_PROMPT.format(
        timing_hint=_TIMING_HINTS.get(timing, timing),
        text=text.strip(),
        active_list=active_list,
        categories=", ".join(CATEGORIES),
    )

    model = llm
    if model is None:
        try:
            from services.ai.ai_settings import AgentRole
            from services.ai.model_config import ModelSelector

            model = ModelSelector.get_llm(AgentRole.WORKOUT)
        except Exception as exc:
            return _default_classification(text, f"no model available: {exc}")

    try:
        response = model.invoke(prompt)
        raw = (getattr(response, "content", None) or str(response)).strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        parsed = json.loads(raw)
    except Exception as exc:
        return _default_classification(text, f"LLM call or JSON parse failed: {exc}")

    if not isinstance(parsed, dict):
        return _default_classification(text, "LLM returned a non-object")

    category = str(parsed.get("category", "other")).strip().lower()
    if category not in CATEGORIES:
        category = "other"

    severity = str(parsed.get("severity", "low")).strip().lower()
    if severity not in SEVERITIES:
        severity = "low"

    known_ids = {a.id: a for a in active}
    supersedes = [
        sid
        for sid in (parsed.get("supersedes") or [])
        if isinstance(sid, str)
        and sid in known_ids
        and known_ids[sid].category == category
        and category in SUPERSEDING_CATEGORIES
    ]

    title = str(parsed.get("title") or "").strip() or _default_classification(text, "empty title")["title"]

    return {
        "title": title[:120],
        "category": category,
        "severity": severity,
        "insight": str(parsed.get("insight") or "").strip(),
        "coaching_directive": str(parsed.get("coaching_directive") or "").strip(),
        "supersedes": supersedes,
    }


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_feedback(
    user_data_dir: Path,
    text: str,
    now: datetime | None = None,
    llm: Any | None = None,
    sync_logseq: bool = True,
) -> FeedbackADR:
    """Classify a free-text note, persist it as an ADR and retire what it replaces.

    Raises:
        ValueError: if ``text`` is empty.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Feedback text must not be empty.")

    now = now or datetime.now()
    today = now.date()
    user_data_dir = Path(user_data_dir)

    timing = detect_timing(user_data_dir, today)
    active = load_feedback_adrs(user_data_dir)
    classified = _classify_feedback(cleaned, timing, active, llm=llm)

    entry_id = f"{today.isoformat()}_{_slugify(classified['title'])}"
    path = feedback_dir(user_data_dir) / f"{entry_id}.md"
    # Two notes on the same day can slugify identically — keep both.
    suffix = 2
    while path.exists():
        entry_id = f"{today.isoformat()}_{_slugify(classified['title'])}-{suffix}"
        path = feedback_dir(user_data_dir) / f"{entry_id}.md"
        suffix += 1

    adr = FeedbackADR(
        id=entry_id,
        date=today,
        created_at=now.isoformat(timespec="seconds"),
        title=classified["title"],
        category=classified["category"],
        severity=classified["severity"],
        status=ACTIVE,
        timing=timing,
        insight=classified["insight"],
        coaching_directive=classified["coaching_directive"],
        raw_text=cleaned,
        supersedes=classified["supersedes"],
    )
    _write_adr(adr, path)
    logger.info(
        "Feedback: recorded %s (category=%s, severity=%s, timing=%s).",
        entry_id, adr.category, adr.severity, timing,
    )

    _apply_supersession(adr, active)

    if sync_logseq:
        _mirror_to_logseq(adr)

    return adr


def _apply_supersession(new_adr: FeedbackADR, active: list[FeedbackADR]) -> None:
    """Mark records the new entry replaces as superseded."""
    by_id = {a.id: a for a in active}
    for sid in new_adr.supersedes:
        old = by_id.get(sid)
        if old is None or old.path is None:
            continue
        old.status = SUPERSEDED
        old.superseded_by = new_adr.id
        try:
            _write_adr(old, old.path)
            logger.info("Feedback: %s superseded by %s.", sid, new_adr.id)
        except Exception as exc:
            logger.warning("Feedback: could not supersede %s: %s", sid, exc)


def _mirror_to_logseq(adr: FeedbackADR) -> None:
    """Write the ADR summary into the Logseq daily journal (best effort)."""
    try:
        from services.logseq import write_props_dict

        props = {
            "daily-feedback": adr.raw_text.strip().replace("\n", " "),
            "daily-feedback-category": f"{adr.category} ({adr.severity})",
            "daily-feedback-directive": adr.coaching_directive.strip().replace("\n", " "),
        }
        if write_props_dict(props, date=adr.date):
            logger.info("Feedback: mirrored %s to Logseq journal.", adr.id)
        else:
            logger.info("Feedback: Logseq not reachable — ADR saved locally only.")
    except Exception as exc:
        logger.debug("Feedback: Logseq mirror skipped: %s", exc)


def delete_feedback(user_data_dir: Path, entry_id: str) -> bool:
    """Delete one feedback ADR by id. Returns True if a file was removed."""
    # Guard against path traversal via a crafted id.
    if "/" in entry_id or "\\" in entry_id or ".." in entry_id:
        logger.warning("Feedback: rejected unsafe entry id %r.", entry_id)
        return False

    path = feedback_dir(user_data_dir) / f"{entry_id}.md"
    if not path.exists():
        return False
    try:
        path.unlink()
        logger.info("Feedback: deleted %s.", entry_id)
        return True
    except Exception as exc:
        logger.warning("Feedback: could not delete %s: %s", entry_id, exc)
        return False
