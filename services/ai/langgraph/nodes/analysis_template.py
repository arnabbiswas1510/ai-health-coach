"""Static HTML template for analysis.html (Physiology & Metrics tab).

The LLM supplies structured JSON; this module renders it into a locked HTML page.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON SCHEMA
# ---------------------------------------------------------------------------
ANALYSIS_JSON_SCHEMA = """\
Return a single JSON object with exactly these keys:

{
  "page_title": "string — e.g. 'Arnab – Physiology & Metrics Report'",
  "generated_at": "string — ISO date e.g. '2026-06-16'",
  "athlete_name": "string",
  "report_period": "string — e.g. 'June 2026'",

  "executive_summary": "string — 3-5 sentence HTML-safe paragraph",

  "kpi_rows": [
    {
      "indicator": "string — metric name e.g. 'Current Weight'",
      "value": "string — e.g. '81.5 kg (179.8 lbs)'",
      "trend": "string — e.g. 'Stagnant'",
      "status": "string — one of: optimal | ready | needs_improvement | behind_plan | target | neutral",
      "status_label": "string — e.g. '🚨 Behind Plan'"
    }
  ],

  "deep_dive_sections": [
    {
      "icon": "string — emoji e.g. '🏋️'",
      "title": "string — section title",
      "body": "string — HTML-safe paragraph(s)"
    }
  ],

  "recommendations": [
    {
      "icon": "string — emoji",
      "title": "string — bold title",
      "detail": "string — HTML-safe paragraph"
    }
  ]
}

CRITICAL RULES:
- All string values must be HTML-safe (no raw < > & characters).
- Return ONLY valid JSON. No markdown fences, no comments.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    return html.escape(str(text), quote=True)


_STATUS_STYLES = {
    "optimal":          ("rgba(63,185,80,0.18)",  "#3fb950"),
    "ready":            ("rgba(86,211,100,0.18)", "#56d364"),
    "needs_improvement":("rgba(210,153,34,0.18)", "#d29922"),
    "behind_plan":      ("rgba(248,81,73,0.18)",  "#f85149"),
    "target":           ("rgba(121,192,255,0.18)","#79c0ff"),
    "neutral":          ("rgba(139,148,158,0.1)", "#8b949e"),
}


def _status_badge(status: str, label: str) -> str:
    bg, fg = _STATUS_STYLES.get(status, _STATUS_STYLES["neutral"])
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'padding:3px 10px;border-radius:5px;font-size:0.83em;font-weight:600;">'
        f"{_e(label)}</span>"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """
:root{
  --bg:#0d1117;--card:rgba(22,27,34,0.7);--border:rgba(240,246,252,0.1);
  --text:#c9d1d9;--muted:#8b949e;--title:#f0f6fc;
  --blue:#58a6ff;--green:#3fb950;--red:#f85149;--yellow:#d29922;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
body{
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.65;padding:24px;
  -webkit-font-smoothing:antialiased;
}
header{text-align:center;padding:20px 0 24px;border-bottom:1px solid var(--border);margin-bottom:24px;}
header h1{font-size:2em;font-weight:700;color:var(--title);}
header p{color:var(--muted);margin-top:6px;font-size:0.95em;}
.container{max-width:1000px;margin:0 auto;display:flex;flex-direction:column;gap:20px;}
.an-section{
  background:var(--card);border:1px solid var(--border);border-radius:14px;
  padding:26px;box-shadow:0 4px 20px rgba(0,0,0,0.2);
}
h2{font-size:1.45em;font-weight:700;color:var(--title);
   border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:16px;}
h3{font-size:1.15em;font-weight:600;color:var(--blue);margin:18px 0 10px;}
p{margin-bottom:0.9em;color:var(--text);}
/* KPI Table */
.kpi-table{width:100%;border-collapse:collapse;border-radius:8px;overflow:hidden;
  border:1px solid var(--border);margin-top:4px;}
.kpi-table th{background:rgba(22,27,34,0.9);color:var(--title);font-weight:600;
  font-size:0.85em;text-transform:uppercase;letter-spacing:.05em;padding:11px 14px;text-align:left;}
.kpi-table td{padding:11px 14px;border-bottom:1px solid var(--border);color:var(--text);font-size:0.93em;}
.kpi-table tbody tr:last-child td{border-bottom:none;}
.kpi-table tbody tr:hover{background:rgba(255,255,255,0.03);}
.kpi-table td:first-child{color:var(--muted);}
/* Deep dive */
.deep-dive-grid{display:flex;flex-direction:column;gap:16px;}
.deep-article{background:rgba(255,255,255,0.02);border:1px solid var(--border);
  border-radius:10px;padding:18px 20px;}
.deep-article h3{margin-top:0;}
/* Recommendations */
.rec-list{display:flex;flex-direction:column;gap:14px;}
.rec-item{display:flex;gap:14px;align-items:flex-start;background:rgba(255,255,255,0.02);
  border:1px solid var(--border);border-radius:10px;padding:16px 18px;}
.rec-icon{font-size:1.5em;flex-shrink:0;margin-top:2px;}
.rec-body h4{font-size:0.97em;font-weight:600;color:var(--title);margin-bottom:6px;}
.rec-body p{font-size:0.9em;color:var(--muted);margin:0;}
@media(max-width:640px){
  body{padding:12px;}
  header h1{font-size:1.6em;}
  .kpi-table{font-size:0.85em;}
  .kpi-table th,.kpi-table td{padding:8px 10px;}
}
"""


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_summary(data: dict) -> str:
    return f"""
<section class="an-section">
  <h2>📝 Executive Summary</h2>
  <p>{_e(data.get("executive_summary",""))}</p>
</section>"""


def _render_kpis(data: dict) -> str:
    rows = ""
    for row in data.get("kpi_rows", []):
        badge = _status_badge(row.get("status","neutral"), row.get("status_label","—"))
        rows += (
            f'<tr>'
            f'<td>{_e(row.get("indicator",""))}</td>'
            f'<td><strong>{_e(row.get("value",""))}</strong></td>'
            f'<td>{_e(row.get("trend",""))}</td>'
            f'<td>{badge}</td>'
            f'</tr>\n'
        )
    return f"""
<section class="an-section">
  <h2>📈 Key Performance Indicators</h2>
  <table class="kpi-table">
    <thead><tr><th>Indicator</th><th>Value</th><th>Trend</th><th>Status</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _render_deep_dive(data: dict) -> str:
    articles = ""
    for sec in data.get("deep_dive_sections", []):
        articles += f"""
<div class="deep-article">
  <h3>{_e(sec.get("icon",""))} {_e(sec.get("title",""))}</h3>
  <p>{_e(sec.get("body",""))}</p>
</div>"""
    return f"""
<section class="an-section">
  <h2>🔍 Deep Dive Analysis</h2>
  <div class="deep-dive-grid">{articles}</div>
</section>"""


def _render_recommendations(data: dict) -> str:
    items = ""
    for rec in data.get("recommendations", []):
        items += f"""
<div class="rec-item">
  <div class="rec-icon">{_e(rec.get("icon","💡"))}</div>
  <div class="rec-body">
    <h4>{_e(rec.get("title",""))}</h4>
    <p>{_e(rec.get("detail",""))}</p>
  </div>
</div>"""
    return f"""
<section class="an-section">
  <h2>🌟 Recommendations</h2>
  <div class="rec-list">{items}</div>
</section>"""


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------

def render_analysis_html(data: dict) -> str:
    """Render the full analysis.html from structured data."""
    athlete = _e(data.get("athlete_name", "Athlete"))
    page_title = _e(data.get("page_title", f"{athlete} Physiology & Metrics"))
    period = _e(data.get("report_period", datetime.now().strftime("%B %Y")))
    generated_at = _e(data.get("generated_at", datetime.now().strftime("%Y-%m-%d")))

    body = (
        _render_summary(data)
        + _render_kpis(data)
        + _render_deep_dive(data)
        + _render_recommendations(data)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <h1>📊 {athlete} — Physiology &amp; Metrics</h1>
    <p>{period} · Generated {generated_at}</p>
  </header>
  <div class="container">
    {body}
  </div>
</body>
</html>"""
