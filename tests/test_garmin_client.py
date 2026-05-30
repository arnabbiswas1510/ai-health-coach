from unittest.mock import MagicMock, patch

import pytest

from services.garmin.client import GarminConnectClient


def test_connect_successful(tmp_path):
    with patch("services.garmin.client.Garmin") as mock_garmin_class:
        mock_garmin_instance = MagicMock()
        mock_garmin_class.return_value = mock_garmin_instance

        client = GarminConnectClient(token_dir=str(tmp_path))

        email = "user@example.com"
        password = "secret_password"
        def mfa_callback():
            return "123456"

        client.connect(email, password, mfa_callback=mfa_callback)

        sanitized_email = "user_example_com"
        expected_token_path = tmp_path / sanitized_email

        # Verify directory was created
        assert expected_token_path.exists()

        # Verify Garmin class instantiation
        mock_garmin_class.assert_called_once_with(
            email=email,
            password=password,
            prompt_mfa=mfa_callback,
        )

        # Verify login was called with correct tokenstore path
        mock_garmin_instance.login.assert_called_once_with(tokenstore=str(expected_token_path))
        assert client.client == mock_garmin_instance

def test_connect_failure(tmp_path):
    with patch("services.garmin.client.Garmin") as mock_garmin_class:
        mock_garmin_instance = MagicMock()
        mock_garmin_instance.login.side_effect = RuntimeError("Login failed")
        mock_garmin_class.return_value = mock_garmin_instance

        client = GarminConnectClient(token_dir=str(tmp_path))

        with pytest.raises(RuntimeError, match="Login failed"):
            client.connect("user@example.com", "secret")

def test_disconnect_clears_client(tmp_path):
    client = GarminConnectClient(token_dir=str(tmp_path))
    client._client = MagicMock()

    assert client._client is not None
    client.disconnect()
    assert client._client is None

def test_context_manager(tmp_path):
    client = GarminConnectClient(token_dir=str(tmp_path))
    mock_client = MagicMock()
    client._client = mock_client

    with client as context_client:
        assert context_client is client
        assert context_client.client == mock_client

    assert client._client is None

def test_client_property_raises_if_not_connected():
    client = GarminConnectClient()
    with pytest.raises(RuntimeError, match="GarminConnectClient not connected"):
        _ = client.client
