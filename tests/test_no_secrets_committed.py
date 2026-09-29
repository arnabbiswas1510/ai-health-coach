"""Guard: no real secret may live in a tracked file."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SENTINEL = "@bws"
# Keys the app genuinely needs at runtime. These must carry the sentinel so the
# resolver fails loudly rather than starting the stack with no credentials.
REQUIRED_BWS_KEYS = {
    "GOOGLE_API_KEY",
    "GARMIN_EMAIL",
    "GARMIN_PASSWORD",
    "LOGSEQ_SSH_HOST",
    "LOGSEQ_SSH_USER",
    "LOGSEQ_GRAPH_PATH",
}
# Providers and observability hooks this deployment does not use. render_env.py
# counts an empty resolved secret as MISSING and aborts the entire render, so a
# sentinel here would demand a junk Bitwarden entry purely to appease the
# resolver. Blank is allowed; a literal value is still forbidden.
OPTIONAL_BWS_KEYS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "LANGSMITH_API_KEY",
}
BWS_SECRET_KEYS = REQUIRED_BWS_KEYS | OPTIONAL_BWS_KEYS
SKIP_PREFIXES = ("graphify-out/", "frontend/dist/", "node_modules/")
SKIP_SUFFIXES = (".patch",)


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    files = []
    for rel in out:
        if rel.startswith(SKIP_PREFIXES) or rel.endswith(SKIP_SUFFIXES):
            continue
        files.append(REPO / rel)
    return files


def _parse_env_template() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (REPO / ".env.template").read_text(encoding="utf-8").splitlines():
        s = line.lstrip()
        if not s or s.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


@pytest.mark.parametrize("key", sorted(REQUIRED_BWS_KEYS))
def test_required_env_template_secret_is_a_sentinel(key: str):
    values = _parse_env_template()
    assert key in values, f"{key} missing from .env.template"
    assert values[key] == SENTINEL, (
        f".env.template must not carry a literal for {key}; expected the "
        f"'{SENTINEL}' sentinel but found '{values[key]}'. Store the value in the "
        f"Bitwarden ai-health-coach project instead."
    )


@pytest.mark.parametrize("key", sorted(OPTIONAL_BWS_KEYS))
def test_optional_env_template_secret_is_sentinel_or_blank(key: str):
    values = _parse_env_template()
    assert key in values, f"{key} missing from .env.template"
    assert values[key] in {SENTINEL, ""}, (
        f".env.template must not carry a literal for {key}; expected the "
        f"'{SENTINEL}' sentinel or a blank value but found '{values[key]}'. "
        f"Store the value in the Bitwarden ai-health-coach project instead."
    )


def test_every_template_sentinel_is_a_known_secret_key():
    """Every sentinel in the template must be a declared key.

    Each @bws line adds a hard requirement on the Bitwarden project that would
    otherwise break deploys the moment the secret is absent.
    """
    values = _parse_env_template()
    sentinels = {key for key, val in values.items() if val == SENTINEL}
    undeclared = sentinels - BWS_SECRET_KEYS
    assert not undeclared, (
        "Undeclared @bws sentinels in .env.template: "
        f"{sorted(undeclared)}. Every sentinel must resolve to a non-empty "
        "Bitwarden secret or render_env.py aborts the whole render; add the key "
        "to REQUIRED_BWS_KEYS once the secret exists in the project."
    )


def test_no_example_file_with_real_secret_placeholders():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    banned_snippets = (
        "AIzaSy...",
        "sk-ant-...",
        "sk-...",
        "lsv2_...",
        "your_garmin_password",
    )
    offenders = [snippet for snippet in banned_snippets if snippet in example]
    assert not offenders, ".env.example should describe secrets via @bws workflow, not realistic placeholders"


def test_no_bws_sentinel_bypassed_in_tracked_templates():
    offenders: list[str] = []
    for path in _tracked_text_files():
        if path.name not in {".env.template", ".env.example"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "GARMIN_PASSWORD=your_garmin_password" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, "Tracked env templates contain literal secret placeholders:\n" + "\n".join(offenders)
