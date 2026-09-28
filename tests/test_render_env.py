from __future__ import annotations

import pytest

from scripts.render_env import render


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
