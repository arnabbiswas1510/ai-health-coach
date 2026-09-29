r"""Guards that every committed shell script is syntactically valid.

`startup.sh` is the container entrypoint. A commit stripped backslashes across
the file, turning the line-continuation markers `\\\\"` inside `die()` into
escaped quotes `\\"`. That leaves the string literal unterminated, so the next
`echo -e "` closes it and `$(pwd)` lands outside quotes -- a hard parse error
on line 41.

Because bash parses the whole function body up front, the container died
immediately on boot with `syntax error near unexpected token '('` and entered
a restart loop. It went unnoticed for five weeks only because the deploy
pipeline was separately broken and production kept running a stale image; the
moment deploys started shipping real code, production crash-looped.

The same commit also deleted the `$*` argument from `log`/`ok`/`warn`/`die`,
so every startup message logged an empty string and `die()` reported a
useless fixed word instead of the actual failure reason.

A syntax error in the entrypoint is unrecoverable in production, so it must be
caught here rather than at boot.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

SHELL_SCRIPTS = sorted(
    p for p in REPO.glob("**/*.sh") if ".git" not in p.parts and "graphify-out" not in p.parts
)

STARTUP = REPO / "startup.sh"

# Helpers that forward their arguments to the log line they print.
ARG_FORWARDING_HELPERS = ("log()", "ok()", "warn()")


def _bash() -> str:
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash is present on CI and dev boxes
        pytest.skip("bash not available")
    return bash


def test_shell_scripts_discovered() -> None:
    """Guard the guard: a bad glob would make every test below vacuous."""
    names = {p.name for p in SHELL_SCRIPTS}
    assert "startup.sh" in names, f"startup.sh not discovered, found: {sorted(names)}"
    assert "render_env.sh" in names, f"render_env.sh not discovered, found: {sorted(names)}"


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_shell_script_parses(script: pathlib.Path) -> None:
    """`bash -n` parses without executing -- catches unterminated strings."""
    result = subprocess.run(
        [_bash(), "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,  # a non-zero exit IS the failure we assert on
    )
    assert result.returncode == 0, (
        f"{script.relative_to(REPO)} is not valid bash:\n{result.stderr.strip()}"
    )


@pytest.mark.parametrize("helper", ARG_FORWARDING_HELPERS)
def test_log_helpers_forward_their_arguments(helper: str) -> None:
    """`log "msg"` must print msg, not an empty string."""
    body = next(
        (ln for ln in STARTUP.read_text(encoding="utf-8").splitlines() if ln.startswith(helper)),
        None,
    )
    assert body is not None, f"{helper} not found in startup.sh"
    assert "$*" in body, f"{helper} dropped its argument, so it logs nothing: {body.strip()}"


def test_die_reports_the_actual_error() -> None:
    """die() must interpolate its argument, not print a hardcoded word."""
    text = STARTUP.read_text(encoding="utf-8")
    assert "  ERROR: $*" in text, "die() no longer reports the failure reason passed to it"


def test_startup_help_block_emits_line_continuations() -> None:
    r"""The copy-pasteable `docker run` block needs real trailing backslashes.

    Inside a double-quoted bash string a trailing `\"` is an escaped quote, not
    a backslash, and silently swallows the string terminator. The correct form
    is `\\"`, which echo -e renders as a single trailing backslash.
    """
    for line in STARTUP.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("echo -e "):
            continue
        assert not (stripped.endswith(r' \"') and not stripped.endswith(r' \\"')), (
            'unterminated string: trailing \\" is an escaped quote; use \\\\" '
            f"to emit a line continuation -> {stripped}"
        )
