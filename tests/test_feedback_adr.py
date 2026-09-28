"""Tests for athlete daily feedback ADRs and their use in WOTD generation."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from services.feedback import feedback_adr as fa


class FakeLLM:
    """Minimal stand-in for a LangChain chat model."""

    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        body = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)

        class _Resp:
            content = body

        return _Resp()


def _llm(title="Knee pain during run", category="injury", severity="high", supersedes=None):
    return FakeLLM(
        {
            "title": title,
            "category": category,
            "severity": severity,
            "insight": "Knee discomfort appeared mid-run.",
            "coaching_directive": "Keep tomorrow easy and walk-run only.",
            "supersedes": supersedes or [],
        }
    )


@pytest.fixture
def user_dir(tmp_path):
    d = tmp_path / "Arnabbiswas"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# Recording and round-tripping
# ---------------------------------------------------------------------------

def test_record_feedback_writes_parseable_adr(user_dir):
    adr = fa.record_feedback(user_dir, "Knee twinged at km 4.", llm=_llm(), sync_logseq=False)

    assert adr.path is not None and adr.path.exists()
    assert adr.path.parent == user_dir / "feedback_decisions"
    assert adr.category == "injury"
    assert adr.severity == "high"
    assert adr.status == fa.ACTIVE

    reloaded = fa.load_feedback_adrs(user_dir)
    assert len(reloaded) == 1
    assert reloaded[0].id == adr.id
    assert reloaded[0].raw_text == "Knee twinged at km 4."
    assert reloaded[0].coaching_directive == "Keep tomorrow easy and walk-run only."


def test_empty_feedback_rejected(user_dir):
    with pytest.raises(ValueError):
        fa.record_feedback(user_dir, "   ", llm=_llm(), sync_logseq=False)


def test_llm_failure_falls_back_without_losing_note(user_dir):
    class Boom:
        def invoke(self, prompt):
            raise RuntimeError("model unavailable")

    adr = fa.record_feedback(user_dir, "Skipped today, work ran late.", llm=Boom(), sync_logseq=False)

    assert adr.category == "other"
    assert adr.raw_text == "Skipped today, work ran late."
    assert fa.load_feedback_adrs(user_dir)[0].raw_text == "Skipped today, work ran late."


def test_invalid_category_and_severity_are_normalised(user_dir):
    adr = fa.record_feedback(
        user_dir, "Felt great.",
        llm=_llm(category="euphoria", severity="catastrophic"),
        sync_logseq=False,
    )
    assert adr.category == "other"
    assert adr.severity == "low"


def test_same_day_notes_do_not_overwrite_each_other(user_dir):
    a = fa.record_feedback(user_dir, "First note.", llm=_llm(), sync_logseq=False)
    b = fa.record_feedback(user_dir, "Second note.", llm=_llm(), sync_logseq=False)

    assert a.id != b.id
    assert len(fa.load_feedback_adrs(user_dir)) == 2


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------

def test_newer_note_supersedes_older_same_category(user_dir):
    old = fa.record_feedback(user_dir, "Knee hurts.", llm=_llm(), sync_logseq=False)

    fa.record_feedback(
        user_dir, "Knee feels fine now.",
        llm=_llm(title="Knee recovered", supersedes=[old.id]),
        sync_logseq=False,
    )

    active = fa.load_feedback_adrs(user_dir)
    assert [a.title for a in active] == ["Knee recovered"]

    everything = fa.load_feedback_adrs(user_dir, include_superseded=True)
    retired = next(a for a in everything if a.id == old.id)
    assert retired.status == fa.SUPERSEDED
    assert retired.superseded_by is not None


def test_cannot_supersede_across_categories(user_dir):
    old = fa.record_feedback(user_dir, "Knee hurts.", llm=_llm(), sync_logseq=False)

    new = fa.record_feedback(
        user_dir, "Work ran late.",
        llm=_llm(title="Missed session", category="missed-workout", supersedes=[old.id]),
        sync_logseq=False,
    )

    assert new.supersedes == []
    assert len(fa.load_feedback_adrs(user_dir)) == 2


def test_missed_workout_notes_never_supersede_each_other(user_dir):
    first = fa.record_feedback(
        user_dir, "Missed Monday.",
        llm=_llm(title="Missed Monday", category="missed-workout", severity="low"),
        sync_logseq=False,
    )
    second = fa.record_feedback(
        user_dir, "Missed Tuesday.",
        llm=_llm(title="Missed Tuesday", category="missed-workout",
                 severity="low", supersedes=[first.id]),
        sync_logseq=False,
    )

    # Each missed session is a distinct event, so both must survive.
    assert second.supersedes == []
    assert len(fa.load_feedback_adrs(user_dir)) == 2


def test_hallucinated_supersede_id_is_ignored(user_dir):
    adr = fa.record_feedback(
        user_dir, "Knee hurts.",
        llm=_llm(supersedes=["2020-01-01_does-not-exist"]),
        sync_logseq=False,
    )
    assert adr.supersedes == []


# ---------------------------------------------------------------------------
# Recency weighting
# ---------------------------------------------------------------------------

def _seed(user_dir, days_ago, title):
    when = datetime.now() - timedelta(days=days_ago)
    return fa.record_feedback(
        user_dir, f"note {title}", now=when, llm=_llm(title=title), sync_logseq=False
    )


def test_weights_decay_with_age_and_order_newest_first(user_dir):
    _seed(user_dir, 0, "today")
    _seed(user_dir, 1, "yesterday")
    _seed(user_dir, 5, "five days ago")

    entries = fa.load_weighted_feedback(user_dir)

    assert [e.title for e in entries] == ["today", "yesterday", "five days ago"]
    assert entries[0].weight == pytest.approx(1.0)
    assert entries[1].weight == pytest.approx(0.85)
    assert entries[2].weight == pytest.approx(0.85**5)
    assert entries[0].weight > entries[1].weight > entries[2].weight


def test_entries_outside_window_are_dropped(user_dir):
    _seed(user_dir, 0, "recent")
    _seed(user_dir, 40, "ancient")

    entries = fa.load_weighted_feedback(user_dir)
    assert [e.title for e in entries] == ["recent"]


def test_entry_count_is_capped(user_dir):
    for i in range(15):
        _seed(user_dir, i % 10, f"note-{i}")

    assert len(fa.load_weighted_feedback(user_dir)) == fa.MAX_ENTRIES


def test_superseded_entries_excluded_from_weighting(user_dir):
    old = _seed(user_dir, 2, "knee pain")
    fa.record_feedback(
        user_dir, "All better.",
        llm=_llm(title="knee fine", supersedes=[old.id]),
        sync_logseq=False,
    )

    titles = [e.title for e in fa.load_weighted_feedback(user_dir)]
    assert titles == ["knee fine"]


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def test_prompt_block_is_ordered_and_carries_weights(user_dir):
    _seed(user_dir, 3, "older note")
    _seed(user_dir, 0, "newest note")

    block = fa.render_feedback_prompt_block(fa.load_weighted_feedback(user_dir))

    assert "ATHLETE FEEDBACK" in block
    assert block.index("newest note") < block.index("older note")
    assert "weight 1.00" in block
    assert "Directive: Keep tomorrow easy and walk-run only." in block


def test_prompt_block_when_no_feedback():
    block = fa.render_feedback_prompt_block([])
    assert "None recorded" in block


# ---------------------------------------------------------------------------
# Timing auto-detection
# ---------------------------------------------------------------------------

def test_timing_is_pre_workout_when_nothing_pushed_yet(user_dir):
    assert fa.detect_timing(user_dir) == fa.TIMING_PRE_WOTD


def test_timing_is_post_run_after_a_run_is_logged(user_dir):
    (user_dir / "last_run.json").write_text(
        json.dumps({"date": date.today().isoformat(), "activity_id": "1"}), encoding="utf-8"
    )
    assert fa.detect_timing(user_dir) == fa.TIMING_POST_RUN


def test_timing_is_issued_not_run_when_wotd_pushed_but_no_run(user_dir):
    (user_dir / "wotd_today.json").write_text(
        json.dumps({"date": date.today().isoformat(), "garmin_workout_id": "9"}), encoding="utf-8"
    )
    assert fa.detect_timing(user_dir) == fa.TIMING_NO_RUN_YET


def test_yesterdays_run_does_not_mark_today_as_post_run(user_dir):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    (user_dir / "last_run.json").write_text(
        json.dumps({"date": yesterday, "activity_id": "1"}), encoding="utf-8"
    )
    assert fa.detect_timing(user_dir) == fa.TIMING_PRE_WOTD


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def test_delete_feedback_removes_entry(user_dir):
    adr = fa.record_feedback(user_dir, "Note.", llm=_llm(), sync_logseq=False)

    assert fa.delete_feedback(user_dir, adr.id) is True
    assert fa.load_feedback_adrs(user_dir) == []
    assert fa.delete_feedback(user_dir, adr.id) is False


@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "a/b", "..\\win"])
def test_delete_rejects_path_traversal(user_dir, bad_id):
    assert fa.delete_feedback(user_dir, bad_id) is False


# ---------------------------------------------------------------------------
# Safety: the classification prompt must forbid relaxing hard rules
# ---------------------------------------------------------------------------

def test_classifier_prompt_forbids_relaxing_safety_rules(user_dir):
    llm = _llm()
    fa.record_feedback(user_dir, "Let me run harder.", llm=llm, sync_logseq=False)

    prompt = llm.prompts[0]
    assert "NEVER" in prompt
    assert "walk breaks" in prompt
    assert "5 minutes" in prompt
