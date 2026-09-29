#!/usr/bin/env python3
"""Resolve @bws sentinels in .env.template against Bitwarden secrets."""
from __future__ import annotations

import json
import os
import sys


def resolve_project_id(projects_json_text: str, name: str) -> str:
    """Map a Bitwarden project name to its id, or raise LookupError."""
    projects = json.loads(projects_json_text)
    matches = [p for p in projects if p.get("name") == name]
    if not matches:
        visible = ", ".join(sorted(str(p.get("name", "?")) for p in projects))
        raise LookupError(
            f"no Bitwarden project named {name!r}; the machine account can see: "
            f"{visible or '<none>'}"
        )
    if len(matches) > 1:
        raise LookupError(
            f"{len(matches)} Bitwarden projects are named {name!r}; set "
            f"BWS_PROJECT_ID explicitly to disambiguate"
        )
    return str(matches[0]["id"])


def build_secret_map(secrets: list[dict], project_id: str | None = None) -> dict[str, str]:
    """Index secrets by key, scoped to a project and refusing ambiguous keys.

    A machine account with access to several projects can surface the same key
    more than once. Silently letting the last one win would quietly render
    another app's credential into this .env, so conflicting duplicates are a
    hard error.
    """
    mapping: dict[str, str] = {}
    conflicts: set[str] = set()
    for secret in secrets:
        if project_id is not None and secret.get("projectId") != project_id:
            continue
        key = secret["key"]
        value = secret.get("value", "")
        if key in mapping and mapping[key] != value:
            conflicts.add(key)
        mapping[key] = value
    if conflicts:
        raise ValueError(
            "duplicate Bitwarden secrets with conflicting values for: "
            + ",".join(sorted(conflicts))
        )
    return mapping


BOOTSTRAP_SENTINEL = "@bootstrap"


def render(
    template_text: str,
    secrets: dict[str, str],
    sentinel: str = "@bws",
    environ: dict[str, str] | None = None,
) -> str:
    """Return the rendered .env text, or raise KeyError listing unmet sentinels.

    Two sentinels are understood:

    ``@bws``
        Resolve from Bitwarden. This is the normal case.
    ``@bootstrap``
        Resolve from the process environment (i.e. the bootstrap file that
        render_env.sh sourced). This exists for BWS_ACCESS_TOKEN, which cannot
        come from Bitwarden because it is the credential that unlocks
        Bitwarden. An unresolved ``@bootstrap`` renders as empty and is *not*
        an error: these values are optional, and failing the whole render would
        make an optional feature able to block a deploy.
    """
    env = os.environ if environ is None else environ
    out: list[str] = []
    missing: list[str] = []
    for raw in template_text.splitlines():
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            out.append(raw)
            continue
        key, _, value = raw.partition("=")
        key_name = key.strip()
        if value.strip() == sentinel:
            resolved = secrets.get(key_name, "")
            if resolved == "":
                missing.append(key_name)
                out.append(f"{key_name}=")
            else:
                out.append(f"{key_name}={resolved}")
        elif value.strip() == BOOTSTRAP_SENTINEL:
            out.append(f"{key_name}={env.get(key_name, '')}")
        else:
            out.append(raw)
    if missing:
        raise KeyError(",".join(missing))
    return "\n".join(out) + "\n"


def _resolve_project_mode(name: str) -> int:
    try:
        projects_json = os.environ["BWS_PROJECTS_JSON"]
    except KeyError:
        sys.stderr.write("missing BWS_PROJECTS_JSON\n")
        return 2
    try:
        sys.stdout.write(resolve_project_id(projects_json, name) + "\n")
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"bad BWS_PROJECTS_JSON: {exc}\n")
        return 2
    except LookupError as exc:
        sys.stderr.write(f"{exc}\n")
        return 4
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--resolve-project":
        return _resolve_project_mode(argv[2])
    if len(argv) < 2:
        sys.stderr.write(
            "usage: render_env.py <template> [sentinel]\n"
            "       render_env.py --resolve-project <project-name>\n"
        )
        return 2
    template_path = argv[1]
    sentinel = argv[2] if len(argv) > 2 else "@bws"
    try:
        secrets_list = json.loads(os.environ["BWS_SECRETS_JSON"])
    except (KeyError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"bad or missing BWS_SECRETS_JSON: {exc}\n")
        return 2
    try:
        secrets = build_secret_map(secrets_list, os.environ.get("BWS_PROJECT_ID") or None)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 5
    with open(template_path, encoding="utf-8") as handle:
        template_text = handle.read()
    try:
        sys.stdout.write(render(template_text, secrets, sentinel))
    except KeyError as exc:
        sys.stderr.write(f"MISSING:{exc.args[0]}\n")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
