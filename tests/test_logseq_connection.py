import datetime
import os
from unittest.mock import MagicMock, patch

from services.logseq.logseq_client import (
    _get_ssh_key_path,
    _journal_sftp_path,
    _upsert_properties,
    _write_via_sftp,
    build_props,
    write_daily_properties,
    write_props_dict,
)


def test_journal_sftp_path_resolution():
    """Verify that graph path normalization works for both root directory and explicit /journals folder."""
    target_date = datetime.date(2026, 8, 5)

    with patch.dict(os.environ, {"LOGSEQ_GRAPH_PATH": "/home/pom/Logseq_Brain/journals/"}):
        path = _journal_sftp_path(target_date)
        assert path == "/home/pom/Logseq_Brain/journals/2026_08_05.md"

    with patch.dict(os.environ, {"LOGSEQ_GRAPH_PATH": "/home/pom/Logseq_Brain"}):
        path = _journal_sftp_path(target_date)
        assert path == "/home/pom/Logseq_Brain/journals/2026_08_05.md"

    with patch.dict(os.environ, {"LOGSEQ_GRAPH_PATH": "C:\\Users\\arnab\\Logseq_Brain\\journals"}):
        path = _journal_sftp_path(target_date)
        assert path == "C:/Users/arnab/Logseq_Brain/journals/2026_08_05.md"


def test_ssh_key_path_fallback():
    """Verify key path fallback logic."""
    with patch.dict(os.environ, {"LOGSEQ_SSH_KEY_PATH": "/custom/path/id_rsa"}):
        assert _get_ssh_key_path() == "/custom/path/id_rsa"


def test_upsert_properties_merging():
    """Verify that property block is built cleanly without corrupting existing markdown body."""
    existing_md = "- Existing note bullet\n- Another note\n"
    props = build_props(sleep_duration_hours=7.5, sleep_quality=85, body_weight_lbs=162.0)
    updated = _upsert_properties(existing_md, props)

    assert "- Garmin Health Sync" in updated
    assert "duration:: 7.5" in updated
    assert "quality:: 85" in updated
    assert "weight:: 162.0" in updated
    assert "- Existing note bullet" in updated


@patch("services.logseq.logseq_client._ssh_connect")
def test_write_via_sftp_success(mock_ssh_connect):
    """Simulate successful SFTP journal write on Linux host."""
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh_connect.return_value = mock_ssh
    mock_ssh.open_sftp.return_value = mock_sftp

    # Simulate existing journal file read
    mock_file = MagicMock()
    mock_file.read.return_value = b"- Old notes\n"
    mock_sftp.file.return_value.__enter__.return_value = mock_file

    with patch.dict(
        os.environ,
        {
            "LOGSEQ_SSH_HOST": "192.168.1.50",
            "LOGSEQ_SSH_USER": "pom",
            "LOGSEQ_GRAPH_PATH": "/home/pom/Logseq_Brain/journals",
        },
    ):
        props = build_props(sleep_quality=90)
        success = write_props_dict(props, date=datetime.date(2026, 8, 5))
        assert success is True
        mock_ssh_connect.assert_called_once()


def test_queue_pending_sync_merges_categories(tmp_path):
    from services.logseq import load_pending_syncs, queue_pending_sync

    queue_file = tmp_path / "pending.json"
    queue_pending_sync(queue_file, "2026-10-04", {"sleep": {"duration": 7.5}})
    queue_pending_sync(queue_file, "2026-10-04", {"coach": {"feedback": "Great run"}})

    entries = load_pending_syncs(queue_file)
    assert len(entries) == 1
    assert entries[0]["date"] == "2026-10-04"
    assert entries[0]["properties"] == {
        "sleep": {"duration": 7.5},
        "coach": {"feedback": "Great run"},
    }


def test_generate_run_feedback_skips_non_completed_run(tmp_path):
    from services.garmin.run_coach_feedback import generate_run_feedback

    client = MagicMock()
    config = {"athlete": {"age": 53}, "context": {}}

    # Short distance (< 0.5 km)
    act_short = {"activityId": "1", "distance": 400, "duration": 180, "averageSpeed": 2.5}
    assert generate_run_feedback(client, act_short, config, tmp_path) is None

    # Aborted duration (< 60 s)
    act_aborted = {"activityId": "2", "distance": 1000, "duration": 45, "averageSpeed": 3.0}
    assert generate_run_feedback(client, act_aborted, config, tmp_path) is None

    # Zero speed (e.g. calendar/scheduled planned workout)
    act_planned = {"activityId": "3", "distance": 5000, "duration": 1800, "averageSpeed": 0}
    assert generate_run_feedback(client, act_planned, config, tmp_path) is None


@patch("services.garmin.run_coach_feedback.get_hr_zones")
@patch("services.logseq.write_props_dict")
def test_generate_run_feedback_writes_and_queues_on_run_date(mock_write, mock_get_zones, tmp_path):
    from services.garmin.hr_zones import HRZones
    from services.garmin.run_coach_feedback import generate_run_feedback
    from services.logseq import load_pending_syncs

    mock_get_zones.return_value = HRZones(
        lthr=177,
        max_hr=201,
        z1_high=97,
        z2_low=132,
        z2_high=154,
        walk_break_hr=155,
        z3_high=166,
        z4_high=185,
        z2_floor_pct=0.746,
        z2_ceiling_pct=0.870,
        walk_break_pct=0.876,
    )
    mock_write.return_value = False  # Simulate SSH offline

    client = MagicMock()
    config = {"athlete": {"age": 53}, "context": {}}
    activity = {
        "activityId": "999",
        "activityName": "Morning Run",
        "startTimeLocal": "2026-09-29 07:15:00",
        "distance": 6000,
        "duration": 2100,
        "averageSpeed": 2.85,
        "averageHR": 140,
    }

    mock_model_selector = MagicMock()
    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = "Excellent aerobic walk-run keeping in Zone 2."
    mock_model_selector.get_llm.return_value = mock_llm

    with patch.dict("sys.modules", {
        "services.ai.model_config": MagicMock(ModelSelector=mock_model_selector),
        "services.ai.ai_settings": MagicMock(),
    }):
        fb = generate_run_feedback(client, activity, config, tmp_path)
        assert fb == "Excellent aerobic walk-run keeping in Zone 2."

        # Verify targeted date was the run date (2026-09-29)
        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs["date"] == datetime.date(2026, 9, 29)

        # Verify queued in pending_logseq_syncs.json because SSH was offline
        queue_path = tmp_path / "pending_logseq_syncs.json"
        entries = load_pending_syncs(queue_path)
        assert len(entries) == 1
        assert entries[0]["date"] == "2026-09-29"
        assert entries[0]["properties"] == {
            "coach": {"feedback": "Excellent aerobic walk-run keeping in Zone 2."}
        }


