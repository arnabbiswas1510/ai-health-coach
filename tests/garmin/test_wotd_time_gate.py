"""Unit tests for 6:20 AM time-gated WOTD generation and fallback sleep handling."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from services.garmin.wotd_generator import _extract_sleep_summary, generate_workout_of_the_day


def test_extract_sleep_summary_with_live_data():
    sleep_data = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 28800,
            "sleepScores": {"overall": {"value": 85}},
        }
    }
    summary = _extract_sleep_summary(sleep_data)
    assert summary["sleep_hours"] == 8.0
    assert summary["sleep_score"] == 85
    assert summary["recovery_status"] == "well_rested"
    assert summary["is_fallback"] is False


def test_extract_sleep_summary_with_fallback_data():
    today_sleep = {"dailySleepDTO": {"sleepTimeSeconds": 0}}
    yesterday_sleep = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 25200,
            "sleepScores": {"overall": {"value": 65}},
        }
    }
    summary = _extract_sleep_summary(today_sleep, fallback_sleep_data=yesterday_sleep)
    assert summary["sleep_hours"] == 7.0
    assert summary["sleep_score"] == 65
    assert "fallback" in summary["recovery_status"]
    assert summary["is_fallback"] is True


def test_extract_sleep_summary_total_fallback_default():
    today_sleep = {}
    summary = _extract_sleep_summary(today_sleep)
    assert summary["sleep_hours"] == 7.0
    assert summary["sleep_score"] == 70
    assert summary["is_fallback"] is True


@patch("services.garmin.wotd_generator._weighted_run_baseline")
@patch("services.garmin.wotd_generator._call_ai_for_workout")
def test_generate_wotd_raises_runtime_error_on_ai_failure(mock_ai, mock_base, tmp_path):
    mock_client = MagicMock()
    mock_client.get_user_profile.return_value = {"userData": {"lactateThresholdHeartRate": 177}}
    mock_base.return_value = {"avg_dist_km": 5.0, "avg_pace_min_km": "6:00", "avg_hr": 140, "avg_duration_min": 30}
    mock_ai.return_value = None  # AI call fails

    config = {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}}
    with pytest.raises(RuntimeError, match="WOTD generation failed: AI returned no workout"):
        generate_workout_of_the_day(mock_client, config, tmp_path, sleep_data={})


@patch("services.garmin.wotd_generator._weighted_run_baseline")
@patch("services.garmin.wotd_generator._call_ai_for_workout")
@patch("services.garmin.wotd_generator._sweep_stale_wotd_workouts")
@patch("services.garmin.wotd_generator._push_wotd")
def test_generate_wotd_raises_runtime_error_on_push_failure(mock_push, mock_sweep, mock_ai, mock_base, tmp_path):
    mock_client = MagicMock()
    mock_client.get_user_profile.return_value = {"userData": {"lactateThresholdHeartRate": 177}}
    mock_base.return_value = {"avg_dist_km": 5.0, "avg_pace_min_km": "6:00", "avg_hr": 140, "avg_duration_min": 30}
    mock_ai.return_value = {"workout_name": "WOTD: Test", "workout_type": "simple", "duration_min": 30}
    mock_push.return_value = None  # Garmin push fails

    config = {"workout_of_the_day": {"enabled": True, "push_to_garmin": True}}
    with pytest.raises(RuntimeError, match="WOTD push failed: Garmin API rejected workout upload"):
        generate_workout_of_the_day(mock_client, config, tmp_path, sleep_data={})

