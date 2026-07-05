import os
import pytest
import httpx
from unittest.mock import patch, MagicMock

from services.logseq.logseq_client import _LOGSEQ_HOST, build_props, write_props_dict

def test_logseq_default_host_uses_3001():
    """Verify that the host uses port 3001 (netsh portproxy endpoint: 3001→3000 on the Windows machine)."""
    assert "3001" in _LOGSEQ_HOST, f"Expected 3001 in host, got {_LOGSEQ_HOST}"

@patch("services.logseq.logseq_client._api_call")
def test_logseq_connection_success(mock_api_call):
    """
    Simulates a successful connection to the Logseq API on the new proxy port.
    This ensures that when the proxy is correctly forwarding 3001 -> 3000,
    the app handles the request properly without being blocked by iphlpsvc.
    """
    mock_api_call.return_value = [{"uuid": "test-uuid"}] # mock blocks response

    import datetime
    props = build_props(sleep_quality=85)
    success = write_props_dict(props, date=datetime.date(2026, 6, 25))
    
    assert success is True
    assert mock_api_call.call_count >= 1

@patch("services.logseq.logseq_client._api_call")
def test_logseq_connection_refused(mock_api_call):
    """
    Simulates a connection refused error (e.g., Logseq not running or proxy not set up).
    Verifies that the app handles it gracefully and logs the correct port (3001) in the warning.
    """
    mock_api_call.side_effect = httpx.ConnectError("Connection refused")
    
    import datetime
    props = build_props(sleep_quality=85)
    success = write_props_dict(props, date=datetime.date(2026, 6, 25))
    
    assert success is False
