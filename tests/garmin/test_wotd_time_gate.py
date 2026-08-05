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
