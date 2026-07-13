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

## 🏃 WOTD Zone Model — Empirically Calibrated (2026-07-13)

### Zone Calculation Method
- **Primary anchor**: LTHR (lactate threshold heart rate) — fetched live from `get_user_profile()` on every WOTD cycle
- **Never use** age-based or max-HR formulas; abort with `ValueError` if LTHR unavailable

### Calibrated Percentages (from Garmin HR-timezones analysis, LTHR=177)
| Constant | % of LTHR | @ LTHR=177 | Meaning |
|----------|-----------|-----------|----|
| `Z2_FLOOR_PCT` | **74.6%** | 132 bpm | Lowest HR athlete can sustain a run; below = walk recovery |
| `Z2_CEILING_PCT` | **87.0%** | 154 bpm | Run ceiling; well-paced runs never exceed this |
| `WALK_BREAK_PCT` | **87.6%** | 155 bpm | Walk break trigger — walk immediately at this HR |

### Auto-Recalibration
- **Absolute bpm values auto-scale daily**: as Garmin raises LTHR from training data, all boundaries shift automatically
- **Percentages are stable athlete constants**: recalibrate only after sustained multi-week feedback ("always too easy" / "always hitting ceiling")
- **Example**: LTHR 177→185 → Z2 auto-becomes 138–161 bpm, zero code changes needed

### Walk-Break Rule (non-negotiable — knee health + zone compliance)
- Run segments target: **132–154 bpm**
- Walk immediately if HR ≥ **155 bpm**
- Resume running when HR drops back below **132 bpm** (full recovery)
- Walk-run is the **PREFERRED format** for this athlete

### Athlete Goals
- **Primary**: Weight loss (target ~160 lbs); fat-burning aerobic volume > speed
- **Secondary**: Building running endurance without injuries; knee protection paramount
