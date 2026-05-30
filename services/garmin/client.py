import logging
import os
from collections.abc import Callable
from pathlib import Path

import garth
import requests
from garminconnect import Garmin

logger = logging.getLogger(__name__)


class GarminConnectClient:
    def __init__(self, token_dir: str | None = None):
        self._client: Garmin | None = None
        self._token_dir = Path(
            token_dir
            or os.getenv("GARMINCONNECT_TOKENS")
            or os.getenv("GARTH_HOME")
            or os.path.expanduser("~/.garminconnect")
        )

    def connect(
        self,
        email: str,
        password: str,
        mfa_callback: Callable[[], str] | None = None,
    ) -> None:
        try:
            logger.info("Initializing Garmin Connect client")
            self._token_dir.mkdir(parents=True, exist_ok=True)

            self._client = Garmin(
                email=email,
                password=password,
                prompt_mfa=mfa_callback,
            )

            logger.info("Logging in to Garmin Connect using tokenstore: %s", self._token_dir)
            self._client.login(tokenstore=str(self._token_dir))
            logger.info("Successfully connected to Garmin Connect")
        except Exception as exc:
            logger.error("Failed to connect to Garmin Connect: %s", exc)
            raise

    @property
    def client(self) -> Garmin:
        if self._client is None:
            raise RuntimeError("GarminConnectClient not connected")
        return self._client

    def disconnect(self) -> None:
        if self._client:
            self._client = None
            logger.info("Disconnected from Garmin Connect")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_val, _exc_tb):
        self.disconnect()
