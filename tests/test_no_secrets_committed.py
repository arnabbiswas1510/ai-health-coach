"""Guard: no real secret may live in a tracked file."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SENTINEL = "@bws"
BWS_SECRET_KEYS = {
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "GARMIN_EMAIL",
    "GARMIN_PASSWORD",
    "LANGSMITH_API_KEY",
    "LOGSEQ_SSH_HOST",
    "LOGSEQ_SSH_USER",
    "LOGSEQ_GRAPH_PATH",
}
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


@pytest.mark.parametrize("key", sorted(BWS_SECRET_KEYS))
def test_env_template_secret_is_a_sentinel(key: str):
    values = _parse_env_template()
    assert key in values, f"{key} missing from .env.template"
    assert values[key] == SENTINEL, (
        f".env.template must not carry a literal for {key}; expected the "
        f"'{SENTINEL}' sentinel but found '{values[key]}'. Store the value in the "
        f"Bitwarden ai-health-coach project instead."
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
