"""Guards on the image-based deploy pipeline.

CI publishes ghcr.io/<repo>:latest on every push to main and the deploy
workflow restarts production against it. Two historical misconfigurations broke
that contract silently -- production built its own `ai-health-coach:local`
image and ignored the published one, and source bind-mounts shadowed the
image's code with whatever stale checkout sat on the host. Both produced green
deploys that shipped nothing. These tests pin the fixed shape.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker-compose.yml"
DEPLOY_WORKFLOW = REPO / ".github/workflows/deploy_to_server.yml"
PUBLISH_WORKFLOW = REPO / ".github/workflows/deploy.yml"

PUBLISHED_IMAGE = "ghcr.io/arnabbiswas1510/ai-health-coach"

# The only paths production may legitimately bind-mount into the container.
# Everything else under /app ships in the image via the Dockerfile's `COPY . .`.
ALLOWED_CONTAINER_MOUNTS = {
    "/app/tokens",  # Garmin + Withings auth state, must survive image swaps
    "/app/data",  # generated HTML/JSON and feedback ADRs
    "/app/coach_config.yaml",  # host-specific athlete config
    "/root/.ssh",  # host SSH key for Logseq direct-write
}


def _service() -> dict:
    compose = yaml.safe_load(COMPOSE.read_text())
    return compose["services"]["ai-health-coach"]


def _mount_targets() -> list[str]:
    targets = []
    for volume in _service().get("volumes", []):
        # "source:target" or "source:target:ro"
        parts = volume.split(":")
        assert len(parts) >= 2, f"unparseable volume entry: {volume}"
        targets.append(parts[1])
    return targets


def test_compose_consumes_the_published_image():
    image = _service().get("image", "")
    assert PUBLISHED_IMAGE in image, (
        f"docker-compose.yml must run the image CI publishes ({PUBLISHED_IMAGE}), "
        f"but found image={image!r}. A local-only tag means `docker compose pull` "
        f"is a no-op and production keeps running whatever image it built once."
    )


def test_compose_does_not_build_on_the_production_host():
    service = _service()
    assert "build" not in service, (
        "docker-compose.yml must not declare `build:`. Production has no "
        "guaranteed source checkout, and `docker compose up` reuses an existing "
        "image rather than rebuilding, so a build directive silently pins "
        "production to a stale locally-built image instead of the CI artifact."
    )


@pytest.mark.parametrize("target", sorted(set(_mount_targets())))
def test_no_bind_mount_shadows_application_code(target: str):
    assert target in ALLOWED_CONTAINER_MOUNTS, (
        f"Bind mount onto {target!r} is not allowed. Application code ships in "
        f"the image (Dockerfile `COPY . .`); mounting a host path over it "
        f"replaces the freshly deployed code with the host's stale copy. If "
        f"this is genuinely persistent state, add it to ALLOWED_CONTAINER_MOUNTS."
    )


def test_persistent_state_is_still_mounted():
    """The fix removed source mounts; it must not have removed data mounts."""
    targets = set(_mount_targets())
    for required in ("/app/data", "/app/tokens"):
        assert required in targets, (
            f"{required} must stay bind-mounted or the container loses "
            f"persisted state (feedback ADRs, Garmin tokens) on every deploy."
        )


def test_publish_workflow_pushes_the_image_compose_consumes():
    published = PUBLISH_WORKFLOW.read_text()
    assert "ghcr.io/${{ github.repository }}" in published, (
        "The publish workflow must push to ghcr.io/<repository>, which is what docker-compose.yml pulls."
    )


def test_deploy_workflow_aborts_when_the_image_pull_fails():
    deploy = DEPLOY_WORKFLOW.read_text()
    assert "if ! docker compose pull; then" in deploy, (
        "The deploy workflow must fail when `docker compose pull` fails. "
        "Continuing to `docker compose up -d` restarts the stack on the "
        "previously cached image and reports success, which is how a deploy "
        "of code that never shipped looks green."
    )
    pull_index = deploy.index("docker compose pull")
    up_index = deploy.index("docker compose up -d")
    abort_index = deploy.index("Aborting rather than restarting on a stale image")
    assert pull_index < abort_index < up_index, "The pull failure check must sit between the pull and the `up`."


# ---------------------------------------------------------------------------
# Deploy verification
#
# `docker compose up -d` returns once the container is *created*, so a
# container whose entrypoint aborts immediately still exits 0 and the deploy
# reports success. That is precisely how a syntax error in startup.sh reached
# production and crash-looped while the workflow stayed green. These tests pin
# the verification that turns a broken deploy into a failed one.
# ---------------------------------------------------------------------------


def _deploy_script() -> str:
    workflow = yaml.safe_load(DEPLOY_WORKFLOW.read_text())
    steps = workflow["jobs"]["deploy"]["steps"]
    scripts = [s["with"]["script"] for s in steps if "script" in s.get("with", {})]
    assert scripts, "no ssh-action script step found in the deploy workflow"
    return "\n".join(scripts)


def test_deploy_fails_when_container_crash_loops():
    """A restarting container must abort the deploy, not pass silently."""
    script = _deploy_script()
    # Match the executable comparison, not prose that happens to use the word.
    assert '"$STATE" = "restarting"' in script, (
        "the deploy never tests the container state against 'restarting', so a "
        "crash-looping container is still reported as a successful deploy"
    )
    assert "{{.State.Status}}" in script, (
        "the deploy must inspect container state before declaring success"
    )
    # The state check is worthless unless it actually fails the workflow.
    tail = script.split('"$STATE" = "restarting"', 1)[1]
    assert "exit 1" in tail, (
        "the deploy detects a crash-looping container but never exits non-zero, "
        "so the workflow still reports success"
    )


def test_deploy_verifies_the_served_commit():
    """The running container must prove it is the commit just published."""
    script = _deploy_script()
    assert "/version" in script, (
        "the deploy must query /version to confirm which build is serving; "
        "without it a stale image still yields a green deploy"
    )
    assert "head_sha" in script or "github.sha" in script, (
        "the deploy must compare the served commit against the deployed SHA"
    )


def test_publish_workflow_stamps_the_commit_into_the_image():
    """/version can only be meaningful if CI bakes the SHA in at build time."""
    workflow = yaml.safe_load(PUBLISH_WORKFLOW.read_text())
    steps = workflow["jobs"]["build-and-push"]["steps"]
    build = [s for s in steps if "build-push-action" in str(s.get("uses", ""))]
    assert build, "no docker build-push-action step found"
    build_args = str(build[0].get("with", {}).get("build-args", ""))
    assert "GIT_COMMIT" in build_args, (
        "the build must pass --build-arg GIT_COMMIT=<sha> so the image can "
        f"report which commit it was built from; found build-args={build_args!r}"
    )


def test_dockerfile_accepts_and_exports_the_commit():
    dockerfile = (REPO / "Dockerfile").read_text()
    assert "ARG GIT_COMMIT" in dockerfile, "Dockerfile must accept the GIT_COMMIT build arg"
    assert "ENV GIT_COMMIT" in dockerfile, (
        "Dockerfile must export GIT_COMMIT so the running process can report it"
    )


def test_chat_api_exposes_the_version_endpoint():
    main = (REPO / "services/chat_api/main.py").read_text()
    assert '@app.get("/version")' in main, "chat API must expose GET /version"
    assert 'os.getenv("GIT_COMMIT"' in main, (
        "/version must report the GIT_COMMIT baked into the image"
    )
