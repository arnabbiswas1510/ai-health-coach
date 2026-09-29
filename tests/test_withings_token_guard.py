"""The Withings sync must skip cleanly when its OAuth token is absent.

withings-sync stores its credential at ``<config>/.withings_user.json``. When
that file is missing the library falls back to ``input("Token : ")`` to prompt
for an authorization code. In a detached container stdin is closed, so that
raises ``EOFError`` and the daemon logged a full traceback on every hourly
poll -- noise that buries real failures and obscures the one thing an operator
needs to know, which is that a one-time interactive authorization is required.

The guard also avoids a pointless Garmin tokenstore login on a run that cannot
proceed.
"""

from __future__ import annotations

import importlib
import logging
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

daemon = pytest.importorskip("daemon")


@pytest.fixture
def tokens_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_EMAIL", "athlete@example.com")
    monkeypatch.setenv("GARMINCONNECT_TOKENS", str(tmp_path))
    return tmp_path


def test_skips_and_explains_when_token_missing(tokens_dir, monkeypatch, caplog):
    """No token file -> one actionable warning, no Garmin login, no traceback."""
    called = []

    def _boom(*a, **k):  # pragma: no cover - must never run
        called.append(True)
        raise AssertionError("Garmin login attempted despite missing Withings token")

    monkeypatch.setattr("garminconnect.Garmin", _boom, raising=False)

    with caplog.at_level(logging.WARNING):
        daemon.run_withings_sync()

    assert not called, "must not attempt a Garmin login when the sync cannot proceed"

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert ".withings_user.json" in messages, (
        "the warning must name the missing file so the operator can act on it"
    )
    assert "withings-sync" in messages, (
        "the warning must include the command that creates the token"
    )
    assert "Traceback" not in caplog.text, "a missing token is expected, not an error"


def test_no_eof_error_is_raised(tokens_dir, monkeypatch, caplog):
    """The skip must be a clean early return, not an error path."""

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("Garmin login attempted despite missing Withings token")

    monkeypatch.setattr("garminconnect.Garmin", _boom, raising=False)

    with caplog.at_level(logging.DEBUG):
        daemon.run_withings_sync()  # must return, not raise

    assert "EOF when reading a line" not in caplog.text, (
        "withings-sync prompted on stdin; the missing-token guard did not fire"
    )
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, (
        "a missing token is an expected, operator-actionable state and must be "
        f"logged as a warning, not an error: {[r.getMessage() for r in errors]}"
    )


def test_guard_is_present_in_source():
    """Pin the executable guard, not merely a comment mentioning the filename."""
    src = (REPO / "daemon.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "withings_token" in body, "the missing-token guard was removed from daemon.py"
    assert "os.path.exists(withings_token)" in body, (
        "daemon.py no longer checks whether the Withings token file exists, so a "
        "missing credential will prompt on stdin and raise EOFError every poll"
    )


def test_daemon_module_imports_cleanly():
    """Guard the guard: importorskip must not be masking a real import break."""
    assert importlib.import_module("daemon") is daemon
