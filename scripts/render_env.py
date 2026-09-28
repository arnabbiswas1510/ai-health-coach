#!/usr/bin/env python3
"""Resolve @bws sentinels in .env.template against Bitwarden secrets."""
from __future__ import annotations

import json
import os
import sys


def render(template_text: str, secrets: dict[str, str], sentinel: str = "@bws") -> str:
    """Return the rendered .env text, or raise KeyError listing unmet sentinels."""
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
        else:
            out.append(raw)
    if missing:
        raise KeyError(",".join(missing))
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: render_env.py <template> [sentinel]\n")
        return 2
    template_path = argv[1]
    sentinel = argv[2] if len(argv) > 2 else "@bws"
    try:
        secrets_list = json.loads(os.environ["BWS_SECRETS_JSON"])
    except (KeyError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"bad or missing BWS_SECRETS_JSON: {exc}\n")
        return 2
    secrets = {secret["key"]: secret.get("value", "") for secret in secrets_list}
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
