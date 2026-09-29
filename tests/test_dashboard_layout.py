"""Guards on the dashboard's location in the repository tree.

The dashboard shell used to sit at the repository root as index.html. Any
static file server rooted at the repo -- `python3 -m http.server` being the
obvious one -- then served that page instead of a directory listing, because
SimpleHTTPRequestHandler only lists a directory that has no index.html. The
page rendered broken, since it was detached from data/ (where analysis.html
and planning.html are written) and from the /api/ proxy the chat panel needs,
so the default looked like an application fault.

It now lives under frontend/, matching the sibling ai-trading-bot repository.
These tests pin that, and pin the references that have to follow it.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "frontend/index.html"


def test_dashboard_lives_under_frontend():
    assert DASHBOARD.is_file(), (
        "frontend/index.html is missing. The dashboard shell must live here; "
        "Dockerfile, startup.sh and the CLI all read it from this path."
    )


def test_no_html_at_repository_root():
    stray = sorted(p.name for p in REPO.glob("*.html"))
    assert not stray, (
        f"HTML files found at the repository root: {stray}. A static server "
        f"rooted here (e.g. `python3 -m http.server`) serves index.html "
        f"instead of a directory listing, and the page renders broken because "
        f"it is detached from data/ and the /api/ proxy. Put dashboard assets "
        f"under frontend/."
    )


@pytest.mark.parametrize(
    ("relpath", "needle"),
    [
        ("Dockerfile", "/app/frontend/index.html"),
        ("startup.sh", "/app/frontend/index.html"),
        ("cli/garmin_ai_coach_cli.py", 'Path("frontend/index.html")'),
    ],
)
def test_references_point_at_the_new_location(relpath: str, needle: str):
    text = (REPO / relpath).read_text()
    assert needle in text, (
        f"{relpath} must reference the dashboard at {needle}. A stale path "
        f"here fails quietly: the Dockerfile's sha256sum falls back to a "
        f"timestamp (forcing a needless re-run every build), and startup.sh "
        f"and the CLI both guard with an existence check, so the dashboard "
        f"would simply never be copied into the data volume."
    )


def test_no_reference_to_the_old_root_location():
    for relpath in ("Dockerfile", "startup.sh", "cli/garmin_ai_coach_cli.py"):
        text = (REPO / relpath).read_text()
        assert "/app/index.html" not in text, f"{relpath} still references /app/index.html"
        assert 'Path("index.html")' not in text, f"{relpath} still resolves the dashboard from the repository root"
