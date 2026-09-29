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
