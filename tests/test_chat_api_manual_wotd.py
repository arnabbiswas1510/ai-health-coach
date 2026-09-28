from fastapi.testclient import TestClient

from services.chat_api import main as chat_api


client = TestClient(chat_api.app)


def _set_wotd_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_api, "WOTD_TRIGGER_PID_PATH", tmp_path / ".wotd_trigger.pid")
    monkeypatch.setattr(chat_api, "WOTD_TRIGGER_STATE_PATH", tmp_path / ".wotd_trigger_state.json")
    monkeypatch.setattr(chat_api, "WOTD_TRIGGER_LOG_PATH", tmp_path / "wotd_trigger.log")
    monkeypatch.setattr(chat_api, "APP_ROOT", tmp_path)


def test_trigger_wotd_background_writes_pid_and_state(tmp_path, monkeypatch):
    _set_wotd_paths(monkeypatch, tmp_path)
    script = tmp_path / "force_wotd.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    class DummyPopen:
        def __init__(self, *args, **kwargs):
            self.pid = 4242

    monkeypatch.setattr(chat_api.subprocess, "Popen", DummyPopen)

    result = chat_api._trigger_wotd_background(script)

    assert result["status"] == "started"
    assert result["pid"] == 4242
    assert chat_api.WOTD_TRIGGER_PID_PATH.read_text(encoding="utf-8") == "4242"

    saved_state = chat_api._load_json(chat_api.WOTD_TRIGGER_STATE_PATH)
    assert saved_state["status"] == "running"
    assert saved_state["pid"] == 4242


def test_get_wotd_trigger_status_marks_finished_when_process_exits(tmp_path, monkeypatch):
    _set_wotd_paths(monkeypatch, tmp_path)
    chat_api.WOTD_TRIGGER_PID_PATH.write_text("4242", encoding="utf-8")
    chat_api._write_json(
        chat_api.WOTD_TRIGGER_STATE_PATH,
        {
            "status": "running",
            "message": "Manual WOTD generation started.",
            "pid": 4242,
            "started_at": "2026-08-24T18:00:00",
            "finished_at": None,
        },
    )
    monkeypatch.setattr(chat_api, "_is_process_running", lambda pid: False)

    result = chat_api._get_wotd_trigger_status()

    assert result["status"] == "finished"
    assert result["pid"] is None
    assert not chat_api.WOTD_TRIGGER_PID_PATH.exists()


def test_trigger_wotd_route_returns_running_response(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_trigger_wotd_background",
        lambda: {
            "status": "started",
            "message": "Manual WOTD generation started.",
            "pid": 5150,
            "started_at": "2026-08-24T18:00:00",
            "finished_at": None,
        },
    )

    response = client.post("/wotd/trigger")

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["pid"] == 5150


def test_wotd_status_route_returns_current_status(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_get_wotd_trigger_status",
        lambda: {
            "status": "running",
            "message": "Manual WOTD generation is in progress.",
            "pid": 5150,
            "started_at": "2026-08-24T18:00:00",
            "finished_at": None,
        },
    )

    response = client.get("/wotd/trigger/status")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["pid"] == 5150
