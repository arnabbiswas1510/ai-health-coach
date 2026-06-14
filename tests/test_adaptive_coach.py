from datetime import datetime, timedelta

import pytest

from services.garmin.adaptive_coach import AdaptiveRunningCoach
from services.garmin.models import Activity, ActivitySummary, GarminData


def create_mock_run(distance_km: float, duration_min: float, avg_hr: int, start_time: str) -> Activity:
    summary = ActivitySummary(
        distance=distance_km,
        duration=int(duration_min * 60),
        moving_duration=int(duration_min * 60),
        average_hr=avg_hr
    )
    return Activity(
        activity_id=123,
        activity_type="running",
        activity_name="Running Activity",
        start_time=start_time,
        summary=summary
    )

@pytest.fixture
def sample_garmin_data():
    now = datetime.now()
    activities = []
    # Create 30 historical runs, each 10km in 60 mins (pace = 6:00/km) with avg HR 135
    for i in range(30):
        run_time = (now - timedelta(days=35 - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        activities.append(create_mock_run(
            distance_km=10.0,
            duration_min=60.0,
            avg_hr=135,
            start_time=run_time
        ))
    return GarminData(
        user_profile=None,
        daily_stats=None,
        recent_activities=activities,
        all_activities=None,
        physiological_markers=None,
        body_metrics=None,
        recovery_indicators=None,
        training_status=None,
        vo2_max_history=None,
        training_load_history=None,
        long_term_vo2_max_trend=None,
        long_term_training_load_trend=None
    )

def test_baselines_calculation(sample_garmin_data):
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53)

    assert coach.baselines["avg_distance_km"] == 10.0
    assert coach.baselines["avg_duration_min"] == 60.0
    assert coach.baselines["avg_pace_min_km"] == 6.0
    assert coach.baselines["avg_hr"] == 135
    assert coach.baselines["total_runs_count"] == 30

def test_heart_rate_zones(sample_garmin_data):
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53)

    # Max HR = 220 - 53 = 167
    assert coach.max_hr == 167
    # Zone 2 Low = 167 * 0.60 = 100
    assert coach.zone2_low == 100
    # Zone 2 High = 167 * 0.72 = 120
    assert coach.zone2_high == 120

def test_suggest_next_run_no_missed_runs(sample_garmin_data):
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53)

    suggestion = coach.suggest_next_run(missed_runs_count=0)

    # Base building: 1.05 * average distance (10.0 * 1.05 = 10.5 km)
    assert suggestion["distance_km"] == 10.5
    assert suggestion["duration_min"] == 63.0
    assert suggestion["target_pace_str"] == "6:00 /km"
    assert suggestion["target_hr_range"] == "100-120 bpm"
    assert "Base Building Progression" in suggestion["focus"]
    assert suggestion["new_accumulated_debt_km"] == 0.0

def test_suggest_next_run_missed_one_run(sample_garmin_data):
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53)

    # 1 missed run: debt = 10km. Redistributes 10% of debt = +1.0km
    # Total suggested distance = 10.0 + 1.0 = 11.0km (Capped at 1.10x average distance = 11.0km)
    suggestion = coach.suggest_next_run(missed_runs_count=1, accumulated_debt_km=0.0)

    assert suggestion["distance_km"] == 11.0
    assert suggestion["duration_min"] == 66.0
    assert "Adaptive Aerobic Run" in suggestion["focus"]
    # 10.0 (debt) - 1.0 (added) = 9.0km remaining debt
    assert suggestion["new_accumulated_debt_km"] == 9.0

def test_suggest_next_run_missed_multiple_runs_debt_cap(sample_garmin_data):
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53)

    # 3 missed runs: new debt = 30km. Total debt = 30km. Capped at 4x average run distance = 40.0km.
    # Redistributed: 10% of 30km = +3.0km. Proposed distance = 13.0km.
    # Capped at 1.10x average = 11.0km. Added distance = 1.0km.
    # Remaining debt = 30km - 1.0km = 29.0km.
    suggestion = coach.suggest_next_run(missed_runs_count=3, accumulated_debt_km=0.0)

    assert suggestion["distance_km"] == 11.0
    assert suggestion["new_accumulated_debt_km"] == 29.0

def test_suggest_next_run_missed_week_reset(sample_garmin_data):
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53)

    # Missed 4 runs (a full week): reset debt to 0.0, reduce distance to 85% of average (8.5 km)
    suggestion = coach.suggest_next_run(missed_runs_count=4, accumulated_debt_km=15.0)

    assert suggestion["distance_km"] == 8.5
    assert suggestion["duration_min"] == 51.0
    assert suggestion["new_accumulated_debt_km"] == 0.0
    assert "Safe Return" in suggestion["focus"]
    assert "mileage debt has been reset" in suggestion["notes"].lower()


def test_adaptive_coach_weight_management(sample_garmin_data):
    from services.garmin.models import UserProfile

    # Test case 1: Above target weight
    sample_garmin_data.user_profile = UserProfile(weight=80.0, height=175.26)
    coach = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53, height=175.26)
    suggestion = coach.suggest_next_run()
    notes = suggestion["notes"]
    assert "Weight Management Check" in notes
    assert "**Current Weight**: 80.0" in notes
    assert "**BMI**: 26.0" in notes
    assert "Above lower-side target" in notes
    assert "Emphasize Zone 2" in notes

    # Test case 2: Underweight
    sample_garmin_data.user_profile.weight = 50.0
    coach_under = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53, height=175.26)
    suggestion_under = coach_under.suggest_next_run()
    notes_under = suggestion_under["notes"]
    assert "Underweight" in notes_under
    assert "Avoid further weight loss" in notes_under

    # Test case 3: Healthy lower range
    sample_garmin_data.user_profile.weight = 62.0
    coach_healthy = AdaptiveRunningCoach(sample_garmin_data, goal="base_building", age=53, height=175.26)
    suggestion_healthy = coach_healthy.suggest_next_run()
    notes_healthy = suggestion_healthy["notes"]
    assert "Within target lower-healthy-range" in notes_healthy
    assert "Maintain consistency" in notes_healthy


def test_dynamic_heart_rate_zones(sample_garmin_data):
    from services.garmin.models import UserProfile

    # Scenario 1: Dynamic LTHR is available (174 bpm)
    sample_garmin_data.user_profile = UserProfile(lactate_threshold_heart_rate=174)
    coach = AdaptiveRunningCoach(sample_garmin_data, age=53)
    
    # max_hr should be calculated from LTHR: int(174 / 0.88) = 197
    assert coach.max_hr == 197
    # zone2_low should be LTHR * 0.85 = 174 * 0.85 = 147.9 -> 147
    assert coach.zone2_low == 147
    # zone2_high should be LTHR * 0.89 = 174 * 0.89 = 154.86 -> 154
    assert coach.zone2_high == 154

    # Scenario 2: Manual config overrides are specified, they should take precedence
    coach_override = AdaptiveRunningCoach(
        sample_garmin_data, age=53, zone2_min=118, zone2_max=135
    )
    assert coach_override.zone2_low == 118
    assert coach_override.zone2_high == 135

    # Scenario 3: LTHR is not available, should fall back to 220 - age
    sample_garmin_data.user_profile = UserProfile(lactate_threshold_heart_rate=None)
    coach_fallback = AdaptiveRunningCoach(sample_garmin_data, age=53)
    assert coach_fallback.max_hr == 167
    assert coach_fallback.zone2_low == 100
    assert coach_fallback.zone2_high == 120

