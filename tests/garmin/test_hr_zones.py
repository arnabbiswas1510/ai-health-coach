"""Zone consistency between WOTD and post-run coaching feedback.

Regression guard for the discrepancy where run_coach_feedback derived Zone 2
from ``220 - age`` (≈100–120 bpm at age 53) while WOTD prescribed 132–154 bpm
from the live Garmin LTHR.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.garmin.hr_zones import (
    HRZones,
    compute_zones,
    get_hr_zones,
    resolve_lthr,
)
from services.garmin.zone_calibrator import _default_calibration


def _client_with_profile_lthr(lthr=177):
    client = MagicMock()
    client.get_user_profile.return_value = {
        "userData": {"lactateThresholdHeartRate": lthr}
    }
    return client


def test_resolve_lthr_prefers_user_profile():
    client = _client_with_profile_lthr(177)
    assert resolve_lthr(client) == 177
    client.get_training_status.assert_not_called()


def test_resolve_lthr_falls_back_to_training_status_scan():
    client = MagicMock()
    client.get_user_profile.return_value = {"userData": {}}
    client.get_training_status.return_value = {"lactateThresholdHeartRate": 174}
    assert resolve_lthr(client) == 174


def test_resolve_lthr_raises_instead_of_using_age_formula():
    client = MagicMock()
    client.get_user_profile.return_value = {"userData": {}}
    client.get_training_status.return_value = {}
    with pytest.raises(ValueError, match="LTHR is unavailable"):
        resolve_lthr(client)


def test_zones_match_documented_calibration_at_lthr_177():
    zones = compute_zones(177, _default_calibration())
    assert zones.z2_low == 132
    assert zones.walk_break_hr == 155
    assert zones.z2_low < zones.z2_high < zones.walk_break_hr


def test_zones_never_land_in_age_formula_territory():
    """The old bug produced Z2 = 100-120 bpm; assert we are nowhere near it."""
    zones = compute_zones(177, _default_calibration())
    assert zones.z2_low > 125, "Z2 floor collapsed toward the old age-based value"


def test_config_override_wins():
    zones = compute_zones(
        177, _default_calibration(), {"zone2_min": 118, "zone2_max": 135}
    )
    assert (zones.z2_low, zones.z2_high) == (118, 135)


def test_wotd_and_feedback_resolve_identical_zones(tmp_path: Path):
    """The whole point: both consumers must agree, bit for bit."""
    client = _client_with_profile_lthr(177)
    athlete_cfg = {"age": 53}

    wotd_zones = get_hr_zones(
        client, athlete_cfg, tmp_path, recalibrate=False, log_prefix="WOTD"
    )
    feedback_zones = get_hr_zones(
        client, athlete_cfg, tmp_path, recalibrate=False, log_prefix="RunFeedback"
    )

    assert wotd_zones == feedback_zones
    assert isinstance(wotd_zones, HRZones)


def test_feedback_path_does_not_consume_calibration_cycle(tmp_path: Path, monkeypatch):
    """recalibrate=False must never fire maybe_recalibrate (it resets the counter)."""
    called = []

    def _boom(*args, **kwargs):
        called.append(1)
        return _default_calibration()

    monkeypatch.setattr("services.garmin.hr_zones.maybe_recalibrate", _boom)

    get_hr_zones(
        _client_with_profile_lthr(177), {}, tmp_path, recalibrate=False
    )
    assert not called, "post-run feedback must not trigger recalibration"

    get_hr_zones(_client_with_profile_lthr(177), {}, tmp_path, recalibrate=True)
    assert called, "WOTD path should still recalibrate"


def test_zone_table_is_contiguous_and_lthr_anchored():
    """Z1-Z5 must tile without gaps and every edge must derive from LTHR."""
    zones = compute_zones(177, _default_calibration())
    table = zones.zone_table()

    assert table["Z2"] == (zones.z2_low, zones.z2_high)
    assert table["Z5"][1] == zones.max_hr

    ordered = [table[f"Z{i}"] for i in range(1, 6)]
    for (_, prev_high), (next_low, _) in zip(ordered, ordered[1:]):
        assert prev_high == next_low, "zone boundaries must be contiguous"
    for low, high in ordered:
        assert low < high


def test_plan_parser_zones_match_the_shared_model():
    """PlanParser must not reintroduce its own age-derived max-HR zone table."""
    from services.garmin.plan_parser import PlanParser

    parser = PlanParser.from_lthr(177)
    expected = compute_zones(177, _default_calibration())

    assert parser.max_hr == expected.max_hr
    assert parser._zones["Z2"] == (expected.z2_low, expected.z2_high)
    # The old 220-age default (max_hr=167) put Z2 at 100-120 bpm.
    assert parser._zones["Z2"] == (132, 153)


def test_plan_parser_honours_manual_zone_override():
    from services.garmin.plan_parser import PlanParser

    parser = PlanParser.from_lthr(177, athlete_cfg={"zone2_min": 125, "zone2_max": 145})
    assert parser._zones["Z2"] == (125, 145)


def test_resolve_lthr_falls_back_to_get_lactate_threshold():
    client = MagicMock()
    client.get_user_profile.return_value = {"userData": {}}
    client.get_lactate_threshold.return_value = {
        "speed_and_heart_rate": {"heartRate": 175}
    }
    assert resolve_lthr(client) == 175


def test_resolve_lthr_falls_back_to_get_heart_rate_zones():
    client = MagicMock()
    client.get_user_profile.return_value = {"userData": {}}
    client.get_lactate_threshold.return_value = {}
    client.get_training_status.return_value = {}
    client.get_heart_rate_zones.return_value = [
        {"sport": "RUNNING", "lactateThresholdHeartRate": 176}
    ]
    assert resolve_lthr(client) == 176

