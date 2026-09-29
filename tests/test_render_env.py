from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.render_env import build_secret_map, render, resolve_project_id


def test_render_replaces_bws_sentinels():
    template = "GOOGLE_API_KEY=@bws\nAI_MODE=cost_effective\n"
    rendered = render(template, {"GOOGLE_API_KEY": "secret-google"})
    assert rendered == "GOOGLE_API_KEY=secret-google\nAI_MODE=cost_effective\n"


def test_render_fails_closed_for_missing_secret():
    template = "GOOGLE_API_KEY=@bws\n"
    with pytest.raises(KeyError, match="GOOGLE_API_KEY"):
        render(template, {})


def test_render_preserves_comments_and_blank_lines():
    template = "# comment\n\nOPENAI_API_KEY=@bws\nLOG_LEVEL=INFO\n"
    rendered = render(template, {"OPENAI_API_KEY": "sk-test"})
    assert rendered == "# comment\n\nOPENAI_API_KEY=sk-test\nLOG_LEVEL=INFO\n"


def _deploy_script() -> str:
    """The inline shell block the SSH deploy step runs on the server."""
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[1]
         / ".github/workflows/deploy_to_server.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["deploy"]["steps"]
    ssh_steps = [s for s in steps if "ssh-action" in str(s.get("uses", ""))]
    assert ssh_steps, "deploy workflow lost its ssh-action step"
    return ssh_steps[-1]["with"]["script"]


def test_deploy_workflow_actually_runs_the_renderer():
    """Pin that the renderer is invoked, not just made executable.

    Regression: the workflow used to chmod +x render_env.sh and never call it,
    so .env silently never refreshed and secret rotations never reached prod.
    """
    script = _deploy_script()
    invocations = [
        line.strip() for line in script.splitlines()
        if "render_env.sh" in line and "chmod" not in line
    ]
    assert invocations, (
        "deploy_to_server.yml must execute scripts/render_env.sh, not merely "
        "make it executable."
    )


def test_deploy_workflow_renders_env_before_starting_the_stack():
    script = _deploy_script()
    assert script.index("render_env.sh") < script.index("docker compose up"), (
        "render_env.sh must run before 'docker compose up' so the stack reads "
        "the freshly rendered .env."
    )


def test_deploy_workflow_aborts_when_no_env_can_be_produced():
    """Abort the deploy when no .env can be produced at all.

    A failed render with no pre-existing .env must stop the deploy rather than
    booting the stack with no configuration whatsoever.
    """
    script = _deploy_script()
    assert "exit 1" in script, (
        "deploy_to_server.yml must fail the job when render_env.sh fails and no "
        "fallback .env exists."
    )


# --- Project scoping -------------------------------------------------------

PROJECTS = json.dumps([
    {"object": "project", "id": "AAAA-1111", "name": "ai-health-coach"},
    {"object": "project", "id": "BBBB-2222", "name": "trading-bot"},
])


def test_resolve_project_id_finds_the_named_project():
    assert resolve_project_id(PROJECTS, "ai-health-coach") == "AAAA-1111"


def test_resolve_project_id_lists_visible_projects_when_absent():
    with pytest.raises(LookupError) as excinfo:
        resolve_project_id(PROJECTS, "typo-name")
    message = str(excinfo.value)
    assert "typo-name" in message
    # The operator needs to see what the token *can* reach to fix the typo.
    assert "ai-health-coach" in message and "trading-bot" in message


def test_resolve_project_id_refuses_ambiguous_names():
    duplicated = json.dumps([
        {"id": "AAAA-1111", "name": "ai-health-coach"},
        {"id": "CCCC-3333", "name": "ai-health-coach"},
    ])
    with pytest.raises(LookupError, match="BWS_PROJECT_ID"):
        resolve_project_id(duplicated, "ai-health-coach")


def test_build_secret_map_excludes_other_projects():
    """Another project's same-named key must not leak into this .env.

    This is the entire point of scoping the lookup to a single project.
    """
    secrets = [
        {"key": "GOOGLE_API_KEY", "value": "coach-key", "projectId": "AAAA-1111"},
        {"key": "GOOGLE_API_KEY", "value": "trading-key", "projectId": "BBBB-2222"},
    ]
    assert build_secret_map(secrets, "AAAA-1111") == {"GOOGLE_API_KEY": "coach-key"}
    assert build_secret_map(secrets, "BBBB-2222") == {"GOOGLE_API_KEY": "trading-key"}


def test_build_secret_map_rejects_conflicting_duplicates_when_unscoped():
    """Ambiguous keys must fail closed rather than resolve arbitrarily.

    Unscoped, the same key from two projects is ambiguous; failing beats
    silently rendering whichever entry happened to sort last.
    """
    secrets = [
        {"key": "GOOGLE_API_KEY", "value": "coach-key", "projectId": "AAAA-1111"},
        {"key": "GOOGLE_API_KEY", "value": "trading-key", "projectId": "BBBB-2222"},
    ]
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        build_secret_map(secrets, None)


def test_build_secret_map_tolerates_identical_duplicates():
    secrets = [
        {"key": "GARMIN_EMAIL", "value": "same@example.com", "projectId": "AAAA-1111"},
        {"key": "GARMIN_EMAIL", "value": "same@example.com", "projectId": "BBBB-2222"},
    ]
    assert build_secret_map(secrets, None) == {"GARMIN_EMAIL": "same@example.com"}


def test_build_secret_map_defaults_missing_value_to_empty():
    secrets = [{"key": "LANGSMITH_API_KEY", "projectId": "AAAA-1111"}]
    assert build_secret_map(secrets, "AAAA-1111") == {"LANGSMITH_API_KEY": ""}


# --- Deploy-time auto-render gate ------------------------------------------

def _autorender_block() -> str:
    """The .env decision block of the deploy script, on its own."""
    script = _deploy_script()
    start = script.index('echo "=== Rendering')
    end = script.index('echo "=== Pulling')
    return script[start:end]


def test_autorender_is_gated_behind_an_opt_in_marker():
    block = _autorender_block()
    assert "autorender.enabled" in block
    assert block.index("autorender.enabled") < block.index("./scripts/render_env.sh"), (
        "the marker must be tested before the renderer is invoked"
    )


@pytest.mark.parametrize(
    "marker,env_exists,render_rc,expect_rc,expect_env",
    [
        # The cutover has not happened: the host .env is hand-maintained and a
        # deploy must not clobber it with template defaults.
        (False, True, 0, 0, "HAND_TUNED=keepme"),
        # Nothing to run on and no way to produce it: refuse to start the stack.
        (False, False, 0, 1, None),
        (True, True, 0, 0, "RENDERED=from-bitwarden"),
        # Bitwarden unreachable but a previous .env exists: degrade, do not
        # take the coach offline.
        (True, True, 1, 0, "HAND_TUNED=keepme"),
        (True, False, 1, 1, None),
    ],
    ids=[
        "no-marker-keeps-hand-tuned-env",
        "no-marker-no-env-aborts",
        "marker-renders",
        "marker-render-fails-keeps-existing",
        "marker-render-fails-no-env-aborts",
    ],
)
def test_autorender_gate_behaviour(tmp_path, marker, env_exists, render_rc, expect_rc, expect_env):
    """Execute the real deploy block against each host state.

    render_env.sh is atomic and fail-closed, so the stub leaves .env untouched
    when it fails, exactly as the real script does.
    """
    home = tmp_path / "home" / ".config" / "garmin-ai-coach"
    home.mkdir(parents=True)
    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)

    if marker:
        (home / "autorender.enabled").touch()
    if env_exists:
        (proj / ".env").write_text("HAND_TUNED=keepme\n")

    stub = proj / "scripts" / "render_env.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"if [ {render_rc} -eq 0 ]; then echo 'RENDERED=from-bitwarden' > .env; fi\n"
        f"exit {render_rc}\n"
    )
    stub.chmod(0o755)

    block = tmp_path / "block.sh"
    block.write_text(_autorender_block())

    result = subprocess.run(
        ["bash", str(block)],
        cwd=proj,
        env={"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expect_rc, result.stdout + result.stderr

    env_file = proj / ".env"
    if expect_env is None:
        assert not env_file.exists()
    else:
        assert env_file.read_text().strip() == expect_env


# --- Bootstrap token discovery ---------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

MOCK_BWS = """#!/usr/bin/env bash
if [ "$1" = "project" ]; then echo '[{"id":"AAAA","name":"ai-health-coach"}]'; exit 0; fi
if [ "$1" = "secret" ]; then
  printf '[{"key":"GOOGLE_API_KEY","value":"%s","projectId":"AAAA"},' "$BWS_ACCESS_TOKEN"
  echo '{"key":"GARMIN_EMAIL","value":"e","projectId":"AAAA"},
        {"key":"GARMIN_PASSWORD","value":"p","projectId":"AAAA"},
        {"key":"LOGSEQ_SSH_HOST","value":"h","projectId":"AAAA"},
        {"key":"LOGSEQ_SSH_USER","value":"u","projectId":"AAAA"},
        {"key":"LOGSEQ_GRAPH_PATH","value":"g","projectId":"AAAA"}]'
  exit 0
fi
exit 1
"""


def _bootstrap_env(tmp_path, *, app_token=None, shared_token=None):
    """Build a fake host with the real scripts and a mock bws binary."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    for name in ("render_env.sh", "render_env.py"):
        shutil.copy(REPO_ROOT / "scripts" / name, proj / "scripts" / name)
    (proj / "scripts" / "render_env.sh").chmod(0o755)
    shutil.copy(REPO_ROOT / ".env.template", proj / ".env.template")

    if app_token is not None:
        d = home / ".config" / "garmin-ai-coach"
        d.mkdir(parents=True)
        (d / "bws.env").write_text(f"BWS_ACCESS_TOKEN={app_token}\n")
    if shared_token is not None:
        d = home / ".config" / "bws"
        d.mkdir(parents=True)
        (d / "bws.env").write_text(f"BWS_ACCESS_TOKEN={shared_token}\n")
    home.mkdir(parents=True, exist_ok=True)

    bws = tmp_path / "bws"
    bws.write_text(MOCK_BWS)
    bws.chmod(0o755)
    return home, proj, bws


def _run_render(home, proj, bws, **extra_env):
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "BWS_BIN": str(bws),
        "PROJECT_DIR": str(proj),
    }
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(proj / "scripts" / "render_env.sh")],
        capture_output=True, text=True, env=env, check=False,
    )


def test_bootstrap_prefers_app_specific_over_shared(tmp_path):
    """The app-specific token wins when both files are present.

    This lets one app opt out of the shared token without touching the file
    the other apps rely on.
    """
    home, proj, bws = _bootstrap_env(tmp_path, app_token="app-tok", shared_token="shared-tok")
    result = _run_render(home, proj, bws)
    assert result.returncode == 0, result.stderr
    assert "garmin-ai-coach/bws.env" in result.stderr
    # The token actually used is echoed back by the mock as GOOGLE_API_KEY.
    assert "GOOGLE_API_KEY=app-tok" in (proj / ".env").read_text()


def test_bootstrap_falls_back_to_shared_location(tmp_path):
    """Only the shared file exists: several apps on one host share a token."""
    home, proj, bws = _bootstrap_env(tmp_path, shared_token="shared-tok")
    result = _run_render(home, proj, bws)
    assert result.returncode == 0, result.stderr
    assert "config/bws/bws.env" in result.stderr
    assert "GOOGLE_API_KEY=shared-tok" in (proj / ".env").read_text()


def test_bootstrap_missing_everywhere_lists_where_it_looked(tmp_path):
    home, proj, bws = _bootstrap_env(tmp_path)
    result = _run_render(home, proj, bws)
    assert result.returncode != 0
    assert "garmin-ai-coach/bws.env" in result.stderr
    assert "config/bws/bws.env" in result.stderr


def test_explicit_bws_env_file_overrides_both_defaults(tmp_path):
    home, proj, bws = _bootstrap_env(tmp_path, app_token="app-tok", shared_token="shared-tok")
    custom = tmp_path / "custom.env"
    custom.write_text("BWS_ACCESS_TOKEN=custom-tok\n")
    result = _run_render(home, proj, bws, BWS_ENV_FILE=str(custom))
    assert result.returncode == 0, result.stderr
    assert "GOOGLE_API_KEY=custom-tok" in (proj / ".env").read_text()


def test_explicit_bws_env_file_that_is_missing_fails_loudly(tmp_path):
    """An explicit path is honoured exclusively, never fallen back from.

    Silently using a different token than the operator named would be worse
    than failing outright.
    """
    home, proj, bws = _bootstrap_env(tmp_path, app_token="app-tok", shared_token="shared-tok")
    result = _run_render(home, proj, bws, BWS_ENV_FILE=str(tmp_path / "nope.env"))
    assert result.returncode != 0
    assert "BWS_ENV_FILE set but not found" in result.stderr
    assert not (proj / ".env").exists()


# --- Shared bootstrap must not leak another app's project id ---------------

# Echoes back the project id it was scoped to, so a test can assert which
# project was actually queried.
MOCK_BWS_ECHO_PROJECT = """#!/usr/bin/env bash
if [ "$1" = "project" ]; then
  echo '[{"id":"COACH-1","name":"ai-health-coach"},{"id":"TRADE-2","name":"ai-trading-bot"}]'
  exit 0
fi
if [ "$1" = "secret" ]; then
  printf '[{"key":"GOOGLE_API_KEY","value":"%s","projectId":"%s"},' "$3" "$3"
  printf '{"key":"GARMIN_EMAIL","value":"e","projectId":"%s"},' "$3"
  printf '{"key":"GARMIN_PASSWORD","value":"p","projectId":"%s"},' "$3"
  printf '{"key":"LOGSEQ_SSH_HOST","value":"h","projectId":"%s"},' "$3"
  printf '{"key":"LOGSEQ_SSH_USER","value":"u","projectId":"%s"},' "$3"
  printf '{"key":"LOGSEQ_GRAPH_PATH","value":"g","projectId":"%s"}]' "$3"
  exit 0
fi
exit 1
"""


def _shared_bootstrap_host(tmp_path, shared_body):
    home, proj, bws = _bootstrap_env(tmp_path)
    shared = home / ".config" / "bws"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "bws.env").write_text(shared_body)
    bws.write_text(MOCK_BWS_ECHO_PROJECT)
    bws.chmod(0o755)
    return home, proj, bws


def test_project_id_in_a_shared_bootstrap_file_is_ignored(tmp_path):
    """A foreign project id in a shared bws.env must not be adopted.

    The sibling ai-trading-bot deployment stores its own BWS_PROJECT_ID next to
    the token, so sourcing a shared file would otherwise silently point this app
    at that project.
    """
    home, proj, bws = _shared_bootstrap_host(
        tmp_path, "BWS_ACCESS_TOKEN=shared-token\nBWS_PROJECT_ID=TRADE-2\n"
    )
    result = _run_render(home, proj, bws)
    assert result.returncode == 0, result.stderr
    assert "ignoring BWS_PROJECT_ID" in result.stderr
    # Resolved by name, not by the foreign id in the file.
    assert "GOOGLE_API_KEY=COACH-1" in (proj / ".env").read_text()


def test_explicit_project_id_still_overrides_a_shared_bootstrap_file(tmp_path):
    home, proj, bws = _shared_bootstrap_host(
        tmp_path, "BWS_ACCESS_TOKEN=shared-token\nBWS_PROJECT_ID=TRADE-2\n"
    )
    result = _run_render(home, proj, bws, BWS_PROJECT_ID="COACH-1")
    assert result.returncode == 0, result.stderr
    assert "GOOGLE_API_KEY=COACH-1" in (proj / ".env").read_text()


# ── @bootstrap sentinel ──────────────────────────────────────────────────────
#
# BWS_ACCESS_TOKEN is the credential that unlocks Bitwarden, so it is the one
# value that cannot be stored in Bitwarden. It is resolved from the bootstrap
# file that render_env.sh sources instead.


def test_bootstrap_sentinel_resolves_from_the_environment_not_the_vault():
    out = render(
        "BWS_ACCESS_TOKEN=@bootstrap\n",
        {"BWS_ACCESS_TOKEN": "from-vault"},
        environ={"BWS_ACCESS_TOKEN": "from-bootstrap"},
    )
    assert "BWS_ACCESS_TOKEN=from-bootstrap" in out


def test_unset_bootstrap_sentinel_renders_empty_without_failing():
    """Bitwarden mirroring is optional; a missing token must not block a deploy."""
    out = render("BWS_ACCESS_TOKEN=@bootstrap\n", {}, environ={})
    assert "BWS_ACCESS_TOKEN=\n" in out


def test_bootstrap_sentinel_does_not_count_as_a_missing_bws_secret():
    render("BWS_ACCESS_TOKEN=@bootstrap\nGOOGLE_API_KEY=@bws\n",
           {"GOOGLE_API_KEY": "k"}, environ={})


def test_template_marks_the_access_token_as_bootstrap_not_bws():
    """Reject @bws for the access token.

    @bws here would send render_env.py hunting for the token inside the vault
    it is required to open -- a bootstrap paradox that fails the whole render.
    """
    text = (REPO_ROOT / ".env.template").read_text()
    assert "BWS_ACCESS_TOKEN=@bootstrap" in text
    assert "BWS_ACCESS_TOKEN=@bws" not in text
