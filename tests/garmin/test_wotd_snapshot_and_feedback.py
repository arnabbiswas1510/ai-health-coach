"""The dashboard snapshot must never advertise a workout Garmin has not accepted.

The athlete trains from Garmin Connect. If the dashboard showed a workout that
was never pushed (AI succeeded but upload failed, or dry-run mode), the two
would disagree and the athlete could train off a workout that is not on the
watch. These tests pin the ordering: wotd_today.json is written only after
_push_wotd returns a real workout id.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from services.garmin.wotd_generator import generate_workout_of_the_day

BASELINE = {"avg_dist_km": 5.0, "avg_pace_min_km": "6:00", "avg_hr": 140, "avg_duration_min": 30}
AI_WORKOUT = {
    "workout_name": "WOTD: Easy walk-run",
    "workout_type": "structured",
    "duration_min": 45,
    "distance_km": 5.0,
    "target_hr_low": 132,
    "target_hr_high": 154,
    "coach_note": "Keep it easy today.",
    "intervals": [{"iterations": 5, "work_min": 5, "recovery_min": 2, "hr_low": 132, "hr_high": 154}],
}


def _client():
    client = MagicMock()
    client.get_user_profile.return_value = {"userData": {"lactateThresholdHeartRate": 177}}
    return client


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd", return_value="987654")
def test_snapshot_written_after_successful_push(mock_push, mock_sweep, mock_ai, mock_base, tmp_path):
    generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                                tmp_path, sleep_data={})

    snapshot_path = tmp_path / "wotd_today.json"
    assert snapshot_path.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["garmin_workout_id"] == "987654"
    assert snapshot["synced_to_garmin"] is True
    assert snapshot["date"] == date.today().isoformat()
    assert snapshot["workout_name"] == "WOTD: Easy walk-run"
    assert snapshot["intervals"]


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd", return_value=None)
def test_no_snapshot_when_push_fails(mock_push, mock_sweep, mock_ai, mock_base, tmp_path):
    with pytest.raises(RuntimeError):
        generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                                    tmp_path, sleep_data={})

    assert not (tmp_path / "wotd_today.json").exists()


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=None)
def test_no_snapshot_when_ai_fails(mock_ai, mock_base, tmp_path):
    with pytest.raises(RuntimeError):
        generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                                    tmp_path, sleep_data={})

    assert not (tmp_path / "wotd_today.json").exists()


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
def test_no_snapshot_in_dry_run(mock_ai, mock_base, tmp_path):
    generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": False}},
                                tmp_path, sleep_data={})

    assert not (tmp_path / "wotd_today.json").exists()


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd", return_value="111")
def test_snapshot_failure_does_not_fail_a_successful_push(
    mock_push, mock_sweep, mock_ai, mock_base, tmp_path
):
    with patch("services.garmin.wotd_generator._save_wotd_snapshot", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            generate_workout_of_the_day(
                _client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                tmp_path, sleep_data={},
            )

    # The Garmin id is still recorded — the push genuinely succeeded.
    assert (tmp_path / "wotd_last_id.txt").read_text(encoding="utf-8") == "111"


# ---------------------------------------------------------------------------
# Feedback injection into the WOTD prompt
# ---------------------------------------------------------------------------

@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd", return_value="222")
def test_feedback_is_passed_into_the_ai_call(mock_push, mock_sweep, mock_ai, mock_base, tmp_path):
    from services.feedback import feedback_adr as fa

    class FakeLLM:
        def invoke(self, prompt):
            class _R:
                content = json.dumps({
                    "title": "Knee pain during run",
                    "category": "injury",
                    "severity": "high",
                    "insight": "Knee flared mid-run.",
                    "coaching_directive": "Keep tomorrow to an easy walk-run.",
                    "supersedes": [],
                })
            return _R()

    fa.record_feedback(tmp_path, "Knee hurt at km 4.", llm=FakeLLM(), sync_logseq=False)

    generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                                tmp_path, sleep_data={})

    block = mock_ai.call_args.kwargs["feedback_block"]
    assert "ATHLETE FEEDBACK" in block
    assert "Knee hurt at km 4." in block
    assert "Keep tomorrow to an easy walk-run." in block


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd", return_value="333")
def test_missing_feedback_does_not_block_workout(mock_push, mock_sweep, mock_ai, mock_base, tmp_path):
    generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                                tmp_path, sleep_data={})

    assert "None recorded" in mock_ai.call_args.kwargs["feedback_block"]
    assert (tmp_path / "wotd_today.json").exists()


@patch("services.garmin.wotd_generator._weighted_run_baseline", return_value=BASELINE)
@patch("services.garmin.wotd_generator._call_ai_for_workout", return_value=dict(AI_WORKOUT))
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd", return_value="444")
def test_feedback_load_failure_does_not_block_workout(mock_push, mock_sweep, mock_ai, mock_base, tmp_path):
    with patch("services.feedback.load_weighted_feedback", side_effect=RuntimeError("corrupt")):
        generate_workout_of_the_day(_client(), {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}},
                                    tmp_path, sleep_data={})

    assert (tmp_path / "wotd_today.json").exists()
