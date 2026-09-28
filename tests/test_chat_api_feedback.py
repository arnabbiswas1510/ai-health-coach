"""API tests for daily feedback capture and the Garmin-gated workout mirror."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from services.chat_api import main as chat_api
from services.feedback import feedback_adr as fa

client = TestClient(chat_api.app)

USER = "TestAthlete"


class FakeLLM:
    def invoke(self, prompt):
        class _R:
            content = json.dumps({
                "title": "Knee pain during run",
                "category": "injury",
                "severity": "high",
                "insight": "Knee flared at km 4.",
                "coaching_directive": "Keep tomorrow to an easy walk-run.",
                "supersedes": [],
            })
        return _R()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_api, "DATA_DIR", tmp_path)
    user_dir = tmp_path / USER
    user_dir.mkdir(parents=True)
    return user_dir


# ---------------------------------------------------------------------------
# POST /feedback
# ---------------------------------------------------------------------------

def test_submit_feedback_records_adr(data_dir, monkeypatch):
    monkeypatch.setattr(
        fa, "_classify_feedback",
        lambda text, timing, active, llm=None: {
            "title": "Knee pain during run",
            "category": "injury",
            "severity": "high",
            "insight": "Knee flared at km 4.",
            "coaching_directive": "Keep tomorrow to an easy walk-run.",
            "supersedes": [],
        },
    )
    monkeypatch.setattr(fa, "_mirror_to_logseq", lambda adr: None)

    resp = client.post("/feedback", json={"user_id": USER, "text": "Knee hurt at km 4."})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "Knee pain during run" in body["reply"]
    assert body["entry"]["category"] == "injury"
    assert body["entry"]["raw_text"] == "Knee hurt at km 4."
    assert len(body["recent"]) == 1
    assert (data_dir / "feedback_decisions").exists()


def test_submit_empty_feedback_is_rejected(data_dir):
    resp = client.post("/feedback", json={"user_id": USER, "text": "   "})

    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
    assert not (data_dir / "feedback_decisions").exists()


def test_reply_says_shapes_todays_workout_when_none_pushed(data_dir, monkeypatch):
    monkeypatch.setattr(fa, "_mirror_to_logseq", lambda adr: None)
    monkeypatch.setattr(fa, "_classify_feedback", lambda *a, **k: {
        "title": "Feeling sore", "category": "fatigue", "severity": "medium",
        "insight": "", "coaching_directive": "", "supersedes": [],
    })

    resp = client.post("/feedback", json={"user_id": USER, "text": "Legs are sore."})

    assert "hasn't been generated yet" in resp.json()["reply"]


def test_reply_says_shapes_next_workout_once_pushed(data_dir, monkeypatch):
    (data_dir / "wotd_today.json").write_text(
        json.dumps({"date": date.today().isoformat(), "garmin_workout_id": "1"}), encoding="utf-8"
    )
    monkeypatch.setattr(fa, "_mirror_to_logseq", lambda adr: None)
    monkeypatch.setattr(fa, "_classify_feedback", lambda *a, **k: {
        "title": "Feeling sore", "category": "fatigue", "severity": "medium",
        "insight": "", "coaching_directive": "", "supersedes": [],
    })

    resp = client.post("/feedback", json={"user_id": USER, "text": "Legs are sore."})

    assert "next one" in resp.json()["reply"]


# ---------------------------------------------------------------------------
# GET /feedback/recent and DELETE /feedback/{id}
# ---------------------------------------------------------------------------

def test_recent_feedback_is_newest_first(data_dir, monkeypatch):
    monkeypatch.setattr(fa, "_mirror_to_logseq", lambda adr: None)
    from datetime import datetime

    for days_ago, title in [(3, "older"), (0, "newest")]:
        monkeypatch.setattr(fa, "_classify_feedback", lambda *a, _t=title, **k: {
            "title": _t, "category": "fatigue", "severity": "low",
            "insight": "", "coaching_directive": "", "supersedes": [],
        })
        fa.record_feedback(
            data_dir, f"note {title}",
            now=datetime.now() - timedelta(days=days_ago), sync_logseq=False,
        )

    resp = client.get(f"/feedback/recent?user_id={USER}")

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert [e["title"] for e in entries] == ["newest", "older"]
    assert entries[0]["weight"] > entries[1]["weight"]


def test_recent_feedback_empty_when_nothing_recorded(data_dir):
    resp = client.get(f"/feedback/recent?user_id={USER}")
    assert resp.json()["entries"] == []


def test_delete_feedback_removes_entry(data_dir, monkeypatch):
    monkeypatch.setattr(fa, "_mirror_to_logseq", lambda adr: None)
    monkeypatch.setattr(fa, "_classify_feedback", lambda *a, **k: {
        "title": "A note", "category": "other", "severity": "low",
        "insight": "", "coaching_directive": "", "supersedes": [],
    })
    adr = fa.record_feedback(data_dir, "Delete me.", sync_logseq=False)

    resp = client.delete(f"/feedback/{adr.id}?user_id={USER}")

    assert resp.json()["status"] == "deleted"
    assert resp.json()["entries"] == []


# ---------------------------------------------------------------------------
# GET /wotd/today — must only mirror what Garmin already accepted
# ---------------------------------------------------------------------------

def test_wotd_today_unavailable_when_no_snapshot(data_dir):
    resp = client.get(f"/wotd/today?user_id={USER}")

    assert resp.status_code == 200
    assert resp.json()["available"] is False
    assert resp.json()["workout"] is None


def test_wotd_today_returns_todays_pushed_workout(data_dir):
    (data_dir / "wotd_today.json").write_text(json.dumps({
        "date": date.today().isoformat(),
        "garmin_workout_id": "987",
        "workout_name": "WOTD: Easy walk-run",
        "duration_min": 45,
        "synced_to_garmin": True,
    }), encoding="utf-8")

    body = client.get(f"/wotd/today?user_id={USER}").json()

    assert body["available"] is True
    assert body["workout"]["workout_name"] == "WOTD: Easy walk-run"
    assert body["workout"]["garmin_workout_id"] == "987"


def test_stale_snapshot_is_not_shown_as_today(data_dir):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    (data_dir / "wotd_today.json").write_text(json.dumps({
        "date": yesterday, "garmin_workout_id": "987", "workout_name": "Yesterday's",
    }), encoding="utf-8")

    body = client.get(f"/wotd/today?user_id={USER}").json()

    assert body["available"] is False
    assert yesterday in body["message"]


def test_snapshot_without_garmin_id_is_not_shown(data_dir):
    (data_dir / "wotd_today.json").write_text(json.dumps({
        "date": date.today().isoformat(), "workout_name": "Unpushed",
    }), encoding="utf-8")

    body = client.get(f"/wotd/today?user_id={USER}").json()

    assert body["available"] is False
    assert "not been confirmed" in body["message"]
