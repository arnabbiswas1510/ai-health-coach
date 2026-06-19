"""Static HTML template for planning.html.

The LLM supplies structured JSON data; this module renders it into a fixed,
version-controlled HTML page whose CSS, fonts and JS never change between runs.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON SCHEMA (used in the LLM prompt — keep in sync with render_planning_html)
# ---------------------------------------------------------------------------
PLANNING_JSON_SCHEMA = """\
Return a single JSON object with exactly these keys:

{
  "page_title": "string — e.g. 'Arnab – Training Dashboard'",
  "generated_at": "ISO date string — today's date e.g. '2026-06-16'",
  "athlete_name": "string",

  "season_phase": "string — current phase name e.g. 'Base Building Phase 1'",
  "season_overview": "string — 2-4 sentence HTML-safe summary of the season plan",
  "season_milestones": [
    {"label": "string", "detail": "string"}
  ],

  "today_metrics": {
    "workout_type": "string — e.g. 'Zone 2 Run-Walk'",
    "distance_km": "string — e.g. '6.0 km'",
    "distance_miles": "string — e.g. '3.73 mi'",
    "duration": "string — e.g. '50 min'",
    "pace_km": "string — e.g. '8:20/km'",
    "pace_miles": "string — e.g. '13:25/mi'",
    "hr_zone": "string — e.g. 'Zone 2 (147–154 bpm)'"
  },

  "workout_steps": [
    {"label": "string — e.g. 'Warm-up'", "detail": "string — full instruction"}
  ],

  "why_prescription": "string — paragraph explaining autoregulation decision",

  "recovery_indicators": {
    "sleep": "string — e.g. '9h 43m / Score 87'",
    "hrv": "string — e.g. '44 ms'",
    "rhr": "string — e.g. '51 bpm'",
    "stress": "string — e.g. '11 (Low)'",
    "weight": "string — e.g. '81.5 kg'",
    "readiness_label": "string — e.g. 'Ready to Train'",
    "readiness_color": "string — one of: green | yellow | red"
  },

  "adaptation_message": "string — 1-2 sentences on how metrics shaped today's prescription",

  "forecast_days": [
    {
      "day": "string — e.g. 'Tue Jun 17'",
      "focus": "string — e.g. 'Rest / Active Recovery'",
      "workout": "string — brief description"
    }
  ],

  "season_progression": "string — HTML-safe paragraph on season progress vs plan",

  "weight_accountability": {
    "start_weight": "string",
    "target_weight": "string",
    "current_weight": "string",
    "deviation": "string — e.g. 'BEHIND by 0.3 lbs'",
    "status": "string — one of: on_track | behind | ahead",
    "coaching_message": "string — direct coaching paragraph"
  },

  "recent_runs": [
    {
      "date": "string — ISO format YYYY-MM-DD, MUST be sorted newest first",
      "title": "string — activity name",
      "distance_km": "string — e.g. '8.2 km'",
      "distance_miles": "string — e.g. '5.1 mi'",
      "duration": "string — e.g. '52:30'",
      "avg_hr": "number or string",
      "splits": [
        {
          "lap": "number",
          "dist": "string — e.g. '1.00 km (0.62 mi)'",
          "time": "string — e.g. '6:30'",
          "pace": "string — e.g. '6:30/km (10:27/mi)'",
          "avg_hr": "number or string",
          "review": "string — one of: good | warning | drift",
          "review_text": "string — e.g. '✅ Good Zone 2' or '⚠️ HR Spike'"
        }
      ]
    }
  ]
}

CRITICAL RULES:
- recent_runs MUST be sorted by date descending (newest first).
- All string values must be HTML-safe (no raw < > & characters unless inside HTML-value strings).
- Return ONLY valid JSON. No markdown fences, no comments, no explanation.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text), quote=True)


def _readiness_badge(color: str, label: str) -> str:
    colors = {
        "green": ("rgba(63,185,80,0.2)", "#3fb950"),
        "yellow": ("rgba(210,153,34,0.2)", "#d29922"),
        "red": ("rgba(248,81,73,0.2)", "#f85149"),
    }
    bg, fg = colors.get(color, colors["yellow"])
    return (
        f'<span style="background:{bg};color:{fg};padding:4px 12px;'
        f'border-radius:20px;font-size:0.85em;font-weight:600;">'
        f"{_e(label)}</span>"
    )


def _weight_status_style(status: str) -> str:
    if status == "on_track":
        return "color:#3fb950;"
    if status == "ahead":
        return "color:#58a6ff;"
    return "color:#f85149;"


def _split_review_style(review: str) -> str:
    if review == "good":
        return "color:#3fb950;font-weight:600;"
    if review == "drift":
        return "color:#d29922;font-weight:600;"
    return "color:#f85149;font-weight:600;"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_season_section(d: dict) -> str:
    milestones_html = ""
    for m in d.get("season_milestones", []):
        milestones_html += (
            f'<li><strong style="color:#f0f6fc;">{_e(m.get("label",""))}</strong>'
            f' — {_e(m.get("detail",""))}</li>\n'
        )
    return f"""
<section class="plan-section">
  <h2>🗓️ Season Plan — {_e(d.get("season_phase",""))} </h2>
  <p class="section-lead">{_e(d.get("season_overview",""))}</p>
  <ul class="milestone-list">
    {milestones_html}
  </ul>
</section>
"""


def _render_hero_section(d: dict) -> str:
    m = d.get("today_metrics", {})
    steps_html = ""
    for i, step in enumerate(d.get("workout_steps", [])):
        steps_html += f"""
<div class="workout-step">
  <input type="checkbox" id="step-{i}" name="step-{i}">
  <label for="step-{i}">
    <strong>{_e(step.get("label",""))}</strong> — {_e(step.get("detail",""))}
  </label>
</div>"""

    return f"""
<section class="plan-section hero-section">
  <h2>⚡ Next Workout — {_e(m.get("workout_type",""))}</h2>
  <div class="metric-grid">
    <div class="metric-card">
      <div class="metric-icon">📏</div>
      <div class="metric-label">Distance</div>
      <div class="metric-value">{_e(m.get("distance_km","TBD"))}</div>
      <div class="metric-sub">{_e(m.get("distance_miles",""))}</div>
    </div>
    <div class="metric-card">
      <div class="metric-icon">⏱️</div>
      <div class="metric-label">Duration</div>
      <div class="metric-value">{_e(m.get("duration","TBD"))}</div>
    </div>
    <div class="metric-card">
      <div class="metric-icon">🏃</div>
      <div class="metric-label">Pace</div>
      <div class="metric-value">{_e(m.get("pace_km","TBD"))}</div>
      <div class="metric-sub">{_e(m.get("pace_miles",""))}</div>
    </div>
    <div class="metric-card">
      <div class="metric-icon">❤️</div>
      <div class="metric-label">HR Zone</div>
      <div class="metric-value zone-value">{_e(m.get("hr_zone","TBD"))}</div>
    </div>
  </div>

  <div class="workout-steps-box">
    <h3>📋 Workout Steps</h3>
    {steps_html}
  </div>

  <details class="why-box">
    <summary>🧠 Why This Prescription?</summary>
    <p>{_e(d.get("why_prescription",""))}</p>
  </details>
</section>
"""


def _render_recovery_section(d: dict) -> str:
    r = d.get("recovery_indicators", {})
    color = r.get("readiness_color", "yellow")
    badge = _readiness_badge(color, r.get("readiness_label", "Assessing…"))
    return f"""
<section class="plan-section recovery-section">
  <h2>🩺 Garmin Recovery Check</h2>
  <div class="recovery-grid">
    <div class="recovery-item">
      <span class="rec-icon">😴</span>
      <span class="rec-label">Sleep</span>
      <span class="rec-value">{_e(r.get("sleep","—"))}</span>
    </div>
    <div class="recovery-item">
      <span class="rec-icon">💓</span>
      <span class="rec-label">HRV</span>
      <span class="rec-value">{_e(r.get("hrv","—"))}</span>
    </div>
    <div class="recovery-item">
      <span class="rec-icon">🫀</span>
      <span class="rec-label">RHR</span>
      <span class="rec-value">{_e(r.get("rhr","—"))}</span>
    </div>
    <div class="recovery-item">
      <span class="rec-icon">🧘</span>
      <span class="rec-label">Stress</span>
      <span class="rec-value">{_e(r.get("stress","—"))}</span>
    </div>
    <div class="recovery-item">
      <span class="rec-icon">⚖️</span>
      <span class="rec-label">Weight</span>
      <span class="rec-value">{_e(r.get("weight","—"))}</span>
    </div>
    <div class="recovery-item readiness-item">
      <span class="rec-label">Overall Readiness</span>
      {badge}
    </div>
  </div>
  <p class="adaptation-msg">{_e(d.get("adaptation_message",""))}</p>
</section>
"""


def _render_forecast_section(d: dict) -> str:
    rows = ""
    for day in d.get("forecast_days", []):
        rows += (
            f'<tr><td>{_e(day.get("day",""))}</td>'
            f'<td><strong>{_e(day.get("focus",""))}</strong></td>'
            f'<td>{_e(day.get("workout",""))}</td></tr>\n'
        )
    return f"""
<section class="plan-section forecast-section">
  <details class="forecast-details">
    <summary>🔮 7-Day Provisional Forecast</summary>
    <p class="forecast-disclaimer"><em>Provisional — Will dynamically recalculate tomorrow based on your body's recovery.</em></p>
    <table class="forecast-table">
      <thead><tr><th>Day</th><th>Focus</th><th>Workout</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </details>
</section>
"""


def _render_weight_card(d: dict) -> str:
    w = d.get("weight_accountability", {})
    status = w.get("status", "behind")
    style = _weight_status_style(status)
    deviation = w.get("deviation", "")
    emoji = "✅" if status == "on_track" else ("🏆" if status == "ahead" else "🚨")
    return f"""
<div class="weight-card">
  <h3>⚖️ Weight Loss Accountability Partner</h3>
  <div class="weight-stats">
    <div class="wstat"><span class="wlabel">Start</span><span class="wval">{_e(w.get("start_weight","—"))}</span></div>
    <div class="wstat"><span class="wlabel">Target</span><span class="wval">{_e(w.get("target_weight","—"))}</span></div>
    <div class="wstat"><span class="wlabel">Current</span><span class="wval">{_e(w.get("current_weight","—"))}</span></div>
    <div class="wstat"><span class="wlabel">Status</span>
      <span class="wval" style="{style}">{emoji} {_e(deviation)}</span>
    </div>
  </div>
  <p class="coaching-msg">{_e(w.get("coaching_message",""))}</p>
</div>
"""


def _render_runs_section(d: dict) -> str:
    runs = d.get("recent_runs", [])
    # Sort newest-first as a Python safety net
    def _parse_date(run):
        try:
            return datetime.strptime(run.get("date", "1970-01-01"), "%Y-%m-%d")
        except ValueError:
            return datetime.min
    runs = sorted(runs, key=_parse_date, reverse=True)

    run_cards = ""
    for idx, run in enumerate(runs):
        splits_rows = ""
        for sp in run.get("splits", []):
            review_style = _split_review_style(sp.get("review", "warning"))
            splits_rows += (
                f'<tr>'
                f'<td>{_e(str(sp.get("lap","?")))}.</td>'
                f'<td>{_e(sp.get("dist","—"))}</td>'
                f'<td>{_e(sp.get("time","—"))}</td>'
                f'<td>{_e(sp.get("pace","—"))}</td>'
                f'<td>{_e(str(sp.get("avg_hr","—")))} bpm</td>'
                f'<td style="{review_style}">{_e(sp.get("review_text","—"))}</td>'
                f'</tr>\n'
            )
        page_class = "run-page" + (" active-page" if idx == 0 else "")
        run_cards += f"""
<div class="{page_class}" data-run-idx="{idx}">
  <div class="run-header">
    <div class="run-title-block">
      <span class="run-date">{_e(run.get("date",""))}</span>
      <span class="run-name">{_e(run.get("title","Run"))}</span>
    </div>
    <div class="run-stats-inline">
      <span>📏 {_e(run.get("distance_km",""))} ({_e(run.get("distance_miles",""))})</span>
      <span>⏱ {_e(run.get("duration",""))}</span>
      <span>❤️ {_e(str(run.get("avg_hr","—")))} bpm avg</span>
    </div>
  </div>
  {"<div class='no-splits'>No split data available.</div>" if not run.get("splits") else f'''
  <div class="splits-table-wrap">
    <table class="splits-table">
      <thead>
        <tr><th>Lap</th><th>Distance</th><th>Time</th><th>Pace</th><th>Avg HR</th><th>Review</th></tr>
      </thead>
      <tbody>{splits_rows}</tbody>
    </table>
  </div>'''}
</div>"""

    total = len(runs)
    per_page = 5
    total_pages = max(1, (total + per_page - 1) // per_page)

    return f"""
<section id="retro-analysis" class="plan-section">
  <h2>🏅 Run Retro &amp; Analysis</h2>
  <div class="retro-top-grid">
    <div class="retro-progression-card">
      <h3>📈 Season Progression</h3>
      <p>{_e(d.get("season_progression",""))}</p>
    </div>
    {_render_weight_card(d)}
  </div>

  <h3>🏃 Recent Run Analysis (Last {total} Runs — Newest First)</h3>

  <div id="runs-container">
    {run_cards}
  </div>

  <div class="pagination-controls" id="pagination-controls">
    <button class="pg-btn" id="pg-prev" onclick="changePage(-1)" disabled>‹ Prev</button>
    <span id="pg-label">Page 1 of {total_pages}</span>
    <button class="pg-btn" id="pg-next" onclick="changePage(1)" {"disabled" if total_pages <= 1 else ""}>Next ›</button>
  </div>

  <script>
  (function(){{
    var perPage = {per_page};
    var total = {total};
    var totalPages = {total_pages};
    var currentPage = 0;

    function showPage(page) {{
      currentPage = page;
      var start = page * perPage;
      var end = Math.min(start + perPage, total);
      document.querySelectorAll('.run-page').forEach(function(el, idx) {{
        el.classList.toggle('active-page', idx >= start && idx < end);
      }});
      document.getElementById('pg-label').textContent = 'Page ' + (page + 1) + ' of ' + totalPages;
      document.getElementById('pg-prev').disabled = page === 0;
      document.getElementById('pg-next').disabled = page >= totalPages - 1;
    }}

    window.changePage = function(dir) {{
      var next = currentPage + dir;
      if (next >= 0 && next < totalPages) showPage(next);
    }};

    showPage(0);
  }})();
  </script>
</section>
"""


# ---------------------------------------------------------------------------
# CSS (locked — never changes)
# ---------------------------------------------------------------------------
_CSS = """
:root {
  --bg: #0d1117;
  --card: rgba(22,27,34,0.7);
  --border: rgba(240,246,252,0.1);
  --text: #c9d1d9;
  --muted: #8b949e;
  --title: #f0f6fc;
  --blue: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --purple: #bc8cff;
  --radius: 14px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
body{
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.65;padding:24px;
  -webkit-font-smoothing:antialiased;
}
header{text-align:center;padding:24px 0 28px;border-bottom:1px solid var(--border);margin-bottom:28px;}
header h1{font-size:2.2em;font-weight:700;color:var(--title);}
header p{color:var(--muted);font-size:1em;margin-top:6px;}
.container{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:24px;}
.plan-section{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:28px;box-shadow:0 4px 20px rgba(0,0,0,0.2);
}
h2{font-size:1.55em;font-weight:700;color:var(--title);border-bottom:1px solid var(--border);
   padding-bottom:10px;margin-bottom:18px;}
h3{font-size:1.2em;font-weight:600;color:var(--title);margin:20px 0 12px;}
.section-lead{color:var(--muted);font-size:0.97em;margin-bottom:14px;}
.milestone-list{list-style:none;padding:0;display:flex;flex-direction:column;gap:8px;}
.milestone-list li{
  border-left:3px solid var(--blue);padding:8px 14px;
  background:rgba(88,166,255,0.04);border-radius:6px;font-size:0.93em;color:var(--text);
}
/* Hero */
.hero-section{border-color:rgba(88,166,255,0.4);background:linear-gradient(135deg,rgba(22,27,34,0.85),rgba(20,32,48,0.85));}
.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin-bottom:22px;}
.metric-card{
  background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:10px;
  padding:16px;text-align:center;
}
.metric-icon{font-size:1.6em;margin-bottom:6px;}
.metric-label{font-size:0.78em;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;}
.metric-value{font-size:1.35em;font-weight:700;color:var(--title);margin-top:4px;}
.metric-sub{font-size:0.8em;color:var(--muted);margin-top:2px;}
.zone-value{color:var(--green);}
.workout-steps-box{background:rgba(255,255,255,0.03);border:1px solid var(--border);
  border-radius:10px;padding:18px 20px;margin-bottom:16px;}
.workout-step{display:flex;align-items:flex-start;gap:10px;padding:10px 0;
  border-bottom:1px dashed var(--border);font-size:0.93em;}
.workout-step:last-child{border-bottom:none;}
.workout-step input[type=checkbox]{margin-top:3px;accent-color:var(--blue);width:16px;height:16px;flex-shrink:0;}
.workout-step label{cursor:pointer;color:var(--text);}
.workout-step input:checked+label{color:var(--muted);text-decoration:line-through;}
.why-box{background:rgba(88,166,255,0.05);border:1px solid rgba(88,166,255,0.2);
  border-radius:10px;padding:14px 18px;margin-top:12px;}
.why-box summary{cursor:pointer;font-weight:600;color:var(--blue);font-size:0.95em;}
.why-box p{margin-top:10px;color:var(--text);font-size:0.93em;}
/* Recovery */
.recovery-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:16px;}
.recovery-item{
  background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;
  padding:14px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:4px;
}
.rec-icon{font-size:1.4em;}
.rec-label{font-size:0.75em;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);}
.rec-value{font-size:1em;font-weight:600;color:var(--title);}
.readiness-item{grid-column:1/-1;flex-direction:row;justify-content:center;gap:12px;}
.adaptation-msg{font-size:0.92em;color:var(--muted);border-left:3px solid var(--blue);
  padding-left:12px;margin-top:8px;}
/* Forecast */
.forecast-details{background:rgba(188,140,255,0.04);border:1px solid rgba(188,140,255,0.2);
  border-radius:10px;padding:14px 18px;}
.forecast-details summary{cursor:pointer;font-weight:600;color:var(--purple);font-size:0.95em;}
.forecast-disclaimer{margin-top:10px;font-size:0.85em;color:var(--muted);font-style:italic;}
.forecast-table{width:100%;border-collapse:collapse;margin-top:12px;font-size:0.9em;}
.forecast-table th{background:rgba(188,140,255,0.08);color:var(--title);
  padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);}
.forecast-table td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text);}
.forecast-table tr:last-child td{border-bottom:none;}
/* Retro */
.retro-top-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-bottom:22px;}
.retro-progression-card,.weight-card{
  background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;padding:20px;
}
.weight-stats{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0;}
.wstat{display:flex;flex-direction:column;align-items:center;
  background:rgba(255,255,255,0.04);border:1px solid var(--border);border-radius:8px;
  padding:10px 16px;min-width:90px;}
.wlabel{font-size:0.75em;color:var(--muted);text-transform:uppercase;}
.wval{font-size:1.05em;font-weight:700;color:var(--title);margin-top:4px;}
.coaching-msg{font-size:0.9em;color:var(--text);border-left:3px solid var(--yellow);
  padding-left:12px;margin-top:10px;}
/* Run cards */
.run-page{display:none;}
.run-page.active-page{display:block;}
.run-header{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;
  gap:10px;padding:14px 18px;background:rgba(88,166,255,0.06);border-radius:10px;margin-bottom:14px;}
.run-title-block{display:flex;flex-direction:column;gap:4px;}
.run-date{font-size:0.8em;color:var(--muted);}
.run-name{font-size:1.05em;font-weight:600;color:var(--title);}
.run-stats-inline{display:flex;flex-wrap:wrap;gap:12px;font-size:0.88em;color:var(--muted);}
.no-splits{color:var(--muted);font-size:0.9em;padding:12px;}
.splits-table-wrap{overflow-x:auto;}
.splits-table{width:100%;border-collapse:collapse;font-size:0.88em;min-width:560px;}
.splits-table th{background:rgba(88,166,255,0.08);color:var(--title);
  padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap;}
.splits-table td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text);}
.splits-table tr:nth-child(even){background:rgba(255,255,255,0.02);}
.splits-table tr:last-child td{border-bottom:none;}
.pagination-controls{display:flex;align-items:center;justify-content:center;gap:16px;margin-top:18px;}
.pg-btn{background:rgba(88,166,255,0.12);border:1px solid rgba(88,166,255,0.3);color:var(--blue);
  padding:8px 20px;border-radius:8px;cursor:pointer;font-size:0.9em;transition:background .2s;}
.pg-btn:hover:not(:disabled){background:rgba(88,166,255,0.25);}
.pg-btn:disabled{opacity:.35;cursor:default;}
#pg-label{color:var(--muted);font-size:0.88em;}
@media(max-width:640px){
  body{padding:12px;}
  .metric-grid{grid-template-columns:repeat(2,1fr);}
  header h1{font-size:1.7em;}
}
"""


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------

def render_planning_html(data: dict) -> str:
    """Render the full planning.html from structured data."""
    athlete = _e(data.get("athlete_name", "Athlete"))
    page_title = _e(data.get("page_title", f"{athlete} Training Dashboard"))
    generated_at = _e(data.get("generated_at", datetime.now().strftime("%Y-%m-%d")))

    body = (
        _render_season_section(data)
        + _render_hero_section(data)
        + _render_recovery_section(data)
        + _render_forecast_section(data)
        + _render_runs_section(data)
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
    <h1>🏃 {athlete} Training Dashboard</h1>
    <p>Generated {generated_at}</p>
  </header>
  <div class="container">
    {body}
  </div>
</body>
</html>"""
