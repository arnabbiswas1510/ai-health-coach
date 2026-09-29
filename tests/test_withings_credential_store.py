"""Guards for durable Withings credential storage.

The failure this protects against is specific and has already happened once:
the Withings OAuth credential never made it to disk, and because the only way
to create it is an interactive flow with a ~30-second window, the sync silently
never ran. These tests pin the behaviour that makes the credential recoverable
without a human.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from services.withings import credential_store as cs


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Keep a developer's real Bitwarden config out of these tests."""
    monkeypatch.delenv("BWS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BWS_PROJECT_NAME", raising=False)
    monkeypatch.setenv("BWS_BIN", "/nonexistent/bws")


def _fake_bws(monkeypatch, handler):
    """Replace the bws subprocess with a callable taking argv -> stdout|None."""
    monkeypatch.setattr(cs, "_bws_binary", lambda: "/fake/bws")
    monkeypatch.setattr(cs, "_run_bws", handler)


PROJECT_ID = "proj-health"
PROJECTS = json.dumps(
    [{"id": PROJECT_ID, "name": "ai-health-coach"}, {"id": "proj-trade", "name": "ai-trading-bot"}]
)
CREDENTIAL = json.dumps({"access_token": "a1", "refresh_token": "r1"})


# ── seeding ──────────────────────────────────────────────────────────────────


def test_seed_never_overwrites_an_existing_local_credential(tmp_path, monkeypatch):
    """The on-disk copy is the live one; the vault copy may be a rotation behind."""
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    path = cs.credential_path(tmp_path)
    path.write_text(CREDENTIAL, encoding="utf-8")

    def explode(args):  # pragma: no cover - must never run
        raise AssertionError("seed_from_vault consulted the vault despite a local file")

    _fake_bws(monkeypatch, explode)
    assert cs.seed_from_vault(tmp_path) is False
    assert path.read_text(encoding="utf-8") == CREDENTIAL


def test_seed_restores_the_credential_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")

    def handler(args):
        if args[0] == "project":
            return PROJECTS
        return json.dumps(
            [{"id": "s1", "key": cs.SECRET_KEY, "value": CREDENTIAL, "projectId": PROJECT_ID}]
        )

    _fake_bws(monkeypatch, handler)
    assert cs.seed_from_vault(tmp_path) is True
    assert cs.credential_path(tmp_path).read_text(encoding="utf-8") == CREDENTIAL


def test_seed_writes_the_credential_readable_only_by_its_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    _fake_bws(
        monkeypatch,
        lambda args: PROJECTS
        if args[0] == "project"
        else json.dumps(
            [{"id": "s1", "key": cs.SECRET_KEY, "value": CREDENTIAL, "projectId": PROJECT_ID}]
        ),
    )
    cs.seed_from_vault(tmp_path)
    assert cs.credential_path(tmp_path).stat().st_mode & 0o777 == 0o600


def test_seed_refuses_to_write_a_corrupt_credential(tmp_path, monkeypatch):
    """A malformed file would send withings-sync back to its stdin prompt."""
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    _fake_bws(
        monkeypatch,
        lambda args: PROJECTS
        if args[0] == "project"
        else json.dumps(
            [{"id": "s1", "key": cs.SECRET_KEY, "value": "not json", "projectId": PROJECT_ID}]
        ),
    )
    assert cs.seed_from_vault(tmp_path) is False
    assert not cs.credential_path(tmp_path).exists()


def test_seed_is_a_no_op_without_vault_access(tmp_path):
    """Bitwarden is optional: no token must degrade, not raise."""
    assert cs.seed_from_vault(tmp_path) is False


# ── project scoping ──────────────────────────────────────────────────────────


def test_project_is_resolved_by_name_not_by_a_shared_project_id(monkeypatch):
    """The host shares one bootstrap token whose bws.env pins another app's id.

    Honouring BWS_PROJECT_ID here would write this app's Withings credential
    into ai-trading-bot's project.
    """
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("BWS_PROJECT_ID", "proj-trade")
    _fake_bws(monkeypatch, lambda args: PROJECTS)
    assert cs.resolve_project_id() == PROJECT_ID


def test_secret_lookup_ignores_a_same_named_key_in_another_project(monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    _fake_bws(
        monkeypatch,
        lambda args: json.dumps(
            [{"id": "other", "key": cs.SECRET_KEY, "value": "foreign", "projectId": "proj-trade"}]
        ),
    )
    assert cs._find_secret(PROJECT_ID) is None


# ── pushing ──────────────────────────────────────────────────────────────────


def test_push_creates_the_secret_when_the_vault_has_none(tmp_path, monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    cs.credential_path(tmp_path).write_text(CREDENTIAL, encoding="utf-8")
    calls = []

    def handler(args):
        calls.append(args)
        if args[0] == "project":
            return PROJECTS
        if args[1] == "list":
            return "[]"
        return "ok"

    _fake_bws(monkeypatch, handler)
    assert cs.push_to_vault(tmp_path) is True
    assert ["secret", "create", cs.SECRET_KEY, CREDENTIAL, PROJECT_ID] in calls


def test_push_edits_the_existing_secret_rather_than_duplicating_it(tmp_path, monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    cs.credential_path(tmp_path).write_text(CREDENTIAL, encoding="utf-8")
    calls = []

    def handler(args):
        calls.append(args)
        if args[0] == "project":
            return PROJECTS
        if args[1] == "list":
            return json.dumps(
                [{"id": "s1", "key": cs.SECRET_KEY, "value": "stale", "projectId": PROJECT_ID}]
            )
        return "ok"

    _fake_bws(monkeypatch, handler)
    assert cs.push_to_vault(tmp_path) is True
    assert ["secret", "edit", "s1", "--value", CREDENTIAL] in calls
    assert not any(c[:2] == ["secret", "create"] for c in calls)


def test_push_skips_the_vault_when_the_credential_is_unchanged(tmp_path, monkeypatch):
    """Withings rotates on every sync, so an unchanged file means nothing to send."""
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    cs.credential_path(tmp_path).write_text(CREDENTIAL, encoding="utf-8")

    def handler(args):
        if args[0] == "project":
            return PROJECTS
        if args[1] == "list":
            return "[]"
        return "ok"

    _fake_bws(monkeypatch, handler)
    assert cs.push_to_vault(tmp_path) is True

    def explode(args):  # pragma: no cover - must never run
        raise AssertionError("push_to_vault wrote an unchanged credential")

    _fake_bws(monkeypatch, explode)
    assert cs.push_to_vault(tmp_path) is False


def test_push_resends_after_the_credential_rotates(tmp_path, monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    path = cs.credential_path(tmp_path)
    path.write_text(CREDENTIAL, encoding="utf-8")
    sent = []

    def handler(args):
        if args[0] == "project":
            return PROJECTS
        if args[1] == "list":
            return "[]"
        sent.append(args[3])
        return "ok"

    _fake_bws(monkeypatch, handler)
    cs.push_to_vault(tmp_path)

    rotated = json.dumps({"access_token": "a2", "refresh_token": "r2"})
    path.write_text(rotated, encoding="utf-8")
    assert cs.push_to_vault(tmp_path) is True
    assert sent == [CREDENTIAL, rotated]


def test_push_is_a_no_op_when_no_credential_exists(tmp_path, monkeypatch):
    def explode(args):  # pragma: no cover - must never run
        raise AssertionError("push_to_vault contacted the vault with nothing to send")

    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    _fake_bws(monkeypatch, explode)
    assert cs.push_to_vault(tmp_path) is False


def test_push_failure_does_not_record_a_digest(tmp_path, monkeypatch):
    """A recorded digest after a failed write would suppress every later retry."""
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    cs.credential_path(tmp_path).write_text(CREDENTIAL, encoding="utf-8")

    def handler(args):
        if args[0] == "project":
            return PROJECTS
        if args[1] == "list":
            return "[]"
        return None  # write rejected

    _fake_bws(monkeypatch, handler)
    assert cs.push_to_vault(tmp_path) is False
    assert not (tmp_path / cs.DIGEST_FILENAME).exists()


def test_bws_is_invoked_as_argv_never_through_a_shell(tmp_path, monkeypatch):
    """A shell string would word-split JSON credentials and leak them to history."""
    recorded = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded["kwargs"] = kwargs

        class R:
            returncode = 0
            stdout = "[]"
            stderr = ""

        return R()

    monkeypatch.setattr(cs, "_bws_binary", lambda: "/fake/bws")
    monkeypatch.setattr(cs.subprocess, "run", fake_run)
    cs._run_bws(["secret", "list", PROJECT_ID])
    assert isinstance(recorded["argv"], list)
    assert recorded["kwargs"].get("shell") in (None, False)
    assert recorded["kwargs"].get("check") is False


def test_bws_failure_never_raises(monkeypatch):
    """Bitwarden trouble must not take down a sync the local file can serve."""
    monkeypatch.setattr(cs, "_bws_binary", lambda: "/fake/bws")

    def boom(*args, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(cs.subprocess, "run", boom)
    assert cs._run_bws(["project", "list"]) is None


# ── daemon gating ────────────────────────────────────────────────────────────


def test_withings_sync_runs_once_per_day(tmp_path, monkeypatch):
    """Hourly polling would rotate the refresh token ~24x/day for no benefit."""
    import daemon

    monkeypatch.setenv("GARMINCONNECT_TOKENS", str(tmp_path))
    assert daemon._withings_sync_due(date(2026, 9, 29)) is True
    assert daemon._withings_sync_due(date(2026, 9, 29)) is False
    assert daemon._withings_sync_due(date(2026, 9, 30)) is True


def test_withings_gate_records_attempts_not_successes(tmp_path, monkeypatch):
    """Marking only on success lets a permanently failing sync spin hourly."""
    import daemon

    monkeypatch.setenv("GARMINCONNECT_TOKENS", str(tmp_path))
    daemon._withings_sync_due(date(2026, 9, 29))
    marker = tmp_path / ".withings_last_sync"
    assert marker.read_text(encoding="utf-8").strip() == "2026-09-29"
