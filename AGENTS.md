# Garmin AI Coach — Project Context & Memory

## Project Overview
A CLI-first tool that turns Garmin Connect data into:
- An evidence-based training analysis report (`analysis.html`)
- A season strategy + compact 4-week plan (`planning.html`)

It is powered by a LangGraph multi-agent workflow with optional human-in-the-loop (HITL) questions.

## Tech Stack & Architecture
- **Language**: Python
- **Environment & Task Runner**: Pixi (`pixi.toml`, `pixi.lock`)
- **Key Dependencies**: LangGraph, ruff, pytest
- **AI Providers**: OpenAI, Anthropic, OpenRouter (DeepSeek/Gemini/Grok)
- **Folder Structure**:
  - `core/`: Config parsing & options
  - `services/garmin/`: Garmin Connect extraction
  - `services/ai/langgraph/`: LangGraph workflows and state nodes
  - `services/ai/tools/plotting/`: Optional plotting tools
  - `cli/`: CLI entrypoint & config template

## Key Rules & Guidelines
- Keep the CLI-first workflow intact when adding features or modifying behavior.
- Maintain configuration values in template (`cli/coach_config_template.yaml`).
- Outputs are generated in `output.directory` (default: `./data`).

---

## ⚙️ Withings-Garmin Background Weight Sync

We integrated full body composition and scale weight synchronization directly into the `ai-health-coach` container, avoiding the overhead of secondary daemon containers:
1. **Container Integration & Local Build**:
   * Appended `withings-sync>=4.1.0` to `requirements.txt`.
   * Modified `docker-compose.yml` to compile the image locally using the root `Dockerfile` (`build: .`) and tagged it as `ai-health-coach:local`.
2. **Daemon-level Automation (`daemon.py`)**:
   * Added the `run_withings_sync()` subprocess routine to execute `withings-sync -c /app/tokens` inside the main loop alongside coach analyses (runs every hour).
3. **Multi-User Profile Locking**:
   * The Withings account hosts 4 family profiles. During the one-time interactive OAuth setup (`docker compose run --rm --entrypoint "withings-sync -c /app/tokens" ai-health-coach`), only the user profile **`arnab`** was authorized.
   * Authentication is saved in `/app/tokens/.withings_user.json` (persisted in the host's `./tokens` folder), locking all automated background uploads to the `arnab` profile's scale measurements.

---

## 🛠️ GitHub Actions SSH Deployment Pipeline

The `Deploy to Production Server` workflow connects to your DietPi server (`192.168.1.50` locally) over the internet via SSH:
1. **Dynamic DNS Routing**:
   * Connects via port `2222` using the dynamic DNS host `abiswas.duckdns.org`.
2. **Handshake Key Authorization**:
   * The repository's `DEPLOY_KEY` secret is configured with your SSH private key `id_ed25519` (length 411).
   * To prevent authentication timeouts, the matching public key (`id_ed25519.pub`) was appended to `/root/.ssh/authorized_keys` on the DietPi server.
3. **Repository Update Stage**:
   * Modified `.github/workflows/deploy_to_server.yml` to execute `git fetch --all` and `git reset --hard origin/main` inside the `/home/dietpi/docker/garmin-ai-coach` directory on the server *before* pulling/restarting container instances. This ensures all compose, daemon, and helper scripts match the latest repository state.

---

## 🏃 Athlete Profile & Preferences (Arnab — updated 2026-07-13)

### Goals (in priority order)
1. **Weight loss** — target ~160 lbs; fat-burning aerobic volume is more important than speed
2. **Running endurance** — build gradually without injury
3. **Knee protection** — paramount; walk-run format preferred over continuous running

### Workout Format Preferences
- **Walk-run is the PREFERRED format** — athlete explicitly confirmed this is working well and knees appreciate the structured recovery walks
- **Heart-rate based targets only** — do not use pace-based targets; HR keeps the athlete in the right zone automatically
- Walk segments are genuine recovery (HR drifts to 120–132 bpm) — this is intentional and correct, not a problem
- Run segments are the aerobic stimulus — design them to build duration progressively over weeks

### LTHR & Zone Model — CRITICAL RULES

#### Zone Calculation
- **Always use LTHR (lactate threshold heart rate)** fetched live from `get_user_profile() → userData.lactateThresholdHeartRate`
- **NEVER fall back** to age-based formulas or max-HR formulas — if LTHR is unavailable from all sources, **abort with a hard `ValueError`**
- Current LTHR: **177 bpm** (as of 2026-07-13; auto-updates as Garmin re-evaluates from training data)

#### Empirically Calibrated Zone Percentages (set 2026-07-13)
Derived from Garmin `get_activity_hr_in_timezones()` analysis across 3 recent runs:

| Constant | % of LTHR | @ LTHR=177 | Meaning |
|----------|-----------|-----------|---------|
| `Z2_FLOOR_PCT` | **74.6%** | **132 bpm** | Lowest HR athlete can sustain a run; below = walk recovery territory |
| `Z2_CEILING_PCT` | **87.0%** | **154 bpm** | Run ceiling; all well-paced runs stayed below this |
| `WALK_BREAK_PCT` | **87.6%** | **155 bpm** | Walk break trigger — start walking **immediately** at this HR |

Evidence basis:
- Jul 13 (walk-run): 96.8 min in 132–154 bpm, **0 min above 155** ← perfect
- Jul 11 (continuous): 15 min above 155 bpm ← ceiling too high without walk breaks
- Jul 10 (continuous): 8.8 min above 155 bpm ← same pattern

#### Auto-Recalibration (every 10 runs)
- `zone_calibrator.py` tracks completed runs in `data/{user}/zone_calibration.json`
- After 10 runs, `maybe_recalibrate()` fetches last 10 runs from Garmin, computes new floor/ceiling %, saves to JSON
- Constants are clamped to ±4% per cycle (one bad run can't blow up the zones)
- **Absolute bpm values auto-scale daily** because LTHR is fetched live — no code changes needed when LTHR improves
- Example: LTHR 177→185 → Z2 auto-becomes 138–161 bpm with zero intervention

### Walk-Break Rule (non-negotiable)
- **Run target**: 132–154 bpm
- **Walk immediately** if HR ≥ 155 bpm — non-negotiable for knee health and zone compliance
- **Resume running** when HR drops back below 132 bpm (full Z1 recovery achieved)
- This rule must appear in every AI workout prompt as Rule #10

### Workout Design Rules (for AI prompts)
1. Always HR-based targets, never pace targets
2. Walk-run structured format preferred (`workout_type: "structured"`)
3. Readiness score ≥ 70 → normal intensity; 50–69 → 10% reduction; < 50 → easy walk-run only
4. Max duration weekdays: 60 min; weekends: 105 min
5. Cadence target: 170+ spm (cue short quick steps during run segments)
6. Optimise for fat-burning aerobic volume — Z2 time > distance covered

---

## 🔢 Zone Auto-Calibration System

- **New file**: `services/garmin/zone_calibrator.py`
- **Trigger**: `daemon.py` calls `increment_run_counter(user_data_dir)` on every new run
- **Fires**: `maybe_recalibrate(client, lthr, user_data_dir)` called at top of `generate_workout_of_the_day()` when counter ≥ 10
- **Persistence**: `/app/data/{user}/zone_calibration.json` on production server
- **Guard rails**: ±4% max shift/cycle, floor 68–82%, ceiling 80–94%, needs ≥5 valid runs
