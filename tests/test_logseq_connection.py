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

