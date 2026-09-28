# Graph Report - ai-health-coach  (2026-09-28)

## Corpus Check
- 121 files · ~112,188 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1245 nodes · 2994 edges · 56 communities (49 shown, 7 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 162 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `df004575`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TriathlonCoachDataExtractor
- OutsideApiGraphQlClient
- main.py
- run_analysis_from_config
- test_hr_zones.py
- Technology Stack
- Changelog
- TrainingAnalysisState
- create_initial_state
- LangSmithCostExtractor
- PlotReferenceResolver
- PlanParser
- planning_workflow.py
- GarminCalendarSyncer
- _make_syncer
- Garmin AI Coach — Project Context & Memory
- LangSmithConfig
- combined_analyst_node.py
- .get_llm
- logseq_client.py
- _make_syncer
- Question
- Workout of the Day — Implementation Plan
- TrainingMetricsCalculator
- test_no_secrets_committed.py
- GarminConnectClient
- logseq_writer.py
- render
- planning_template.py
- 2026-09-28 — Secrets resolved from Bitwarden at deploy time (`@bws` sentinel)
- CostTracker
- 🛠️ Implemented Architectural Fix
- extract_text_content
- analysis_template.py
- fail
- ProxyHTTPRequestHandler
- _parse_json_safely
- 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data
- Exception
- PlotStorage
- startup.sh
- competition_models.py
- decisions/README.md
- chat_api/__init__.py
- garmin-ai-coach
- extract_expert_output
- 2026-08-24 — Manual WOTD Dashboard Trigger
- 2026-09-28 — HR zones unified in `services/garmin/hr_zones.py`
- zone_calibrator.py
- HRZones
- calibration_for
- RetryConfig

## God Nodes (most connected - your core abstractions)
1. `OutsideApiGraphQlClient` - 75 edges
2. `TriathlonCoachDataExtractor` - 67 edges
3. `TrainingAnalysisState` - 58 edges
4. `TestOutsideApiGraphQlClient` - 47 edges
5. `PlotStorage` - 43 edges
6. `run_analysis_from_config()` - 36 edges
7. `AgentRole` - 35 edges
8. `GarminCalendarSyncer` - 30 edges
9. `create_initial_state()` - 29 edges
10. `retry_with_backoff()` - 26 edges

## Surprising Connections (you probably didn't know these)
- `ConfigParser` --uses--> `UserProfile`  [INFERRED]
  cli/garmin_ai_coach_cli.py → services/garmin/models.py
- `AgentRole` --uses--> `AIMode`  [INFERRED]
  services/ai/ai_settings.py → core/config.py
- `_StubSettings` --uses--> `AgentRole`  [INFERRED]
  tests/test_model_config.py → services/ai/ai_settings.py
- `TestPlottingToolIntegration` --uses--> `AgentRole`  [INFERRED]
  tests/test_plotting_tool_integration.py → services/ai/ai_settings.py
- `test_all_nodes_importable()` --indirect_call--> `activity_expert_node()`  [INFERRED]
  tests/test_langgraph_core_migration.py → services/ai/langgraph/nodes/activity_expert_node.py

## Import Cycles
- None detected.

## Communities (56 total, 7 thin omitted)

### Community 0 - "TriathlonCoachDataExtractor"
Cohesion: 0.06
Nodes (59): GarminEncoder, main(), Any, AdaptiveRunningCoach, Any, Path, Dynamically adjusts and suggests the next run.          Redistributes missed mil, DataExtractor (+51 more)

### Community 1 - "OutsideApiGraphQlClient"
Cohesion: 0.05
Nodes (15): dt, OutsideApiGraphQlClient, Any, datetime, CalendarNode, CalendarResult, Event, EventCategory (+7 more)

### Community 2 - "main.py"
Cohesion: 0.07
Nodes (53): delete, get, post, Re-run only the planning branch using cached expert outputs.      Used by the, run_weekly_planning_with_context(), _apply_suggested_run_override(), _build_planning_context(), _build_run_reply() (+45 more)

### Community 3 - "run_analysis_from_config"
Cohesion: 0.10
Nodes (22): ABC, ConfigParser, create_config_template(), fetch_outside_competitions_from_config(), get_weight_analysis_context(), main(), parse_height_to_cm(), Any (+14 more)

### Community 4 - "test_hr_zones.py"
Cohesion: 0.14
Nodes (27): compute_zones(), get_hr_zones(), Any, Single source of truth for the athlete's heart-rate zones.  Both WOTD generation, Build the full zone set from a live LTHR and calibrated percentages.      A manu, Resolve LTHR and return the athlete's zones.      Args:         recalibrate: whe, Return the athlete's current LTHR from Garmin.      Priority:       1. ``get_use, resolve_lthr() (+19 more)

### Community 5 - "Technology Stack"
Cohesion: 0.04
Nodes (46): AI & LLM Providers, AI Orchestration & Observability, CLI Interface, Code Analysis, Code Quality, Configuration & Environment, Core Dependencies, Core Python Framework (+38 more)

### Community 6 - "Changelog"
Cohesion: 0.04
Nodes (45): [0.1.0] - Previous, [1.0.0] - 2025-10-14, [1.1.0] - 2025-10-17, [2.0.0] - 2025-11-02, [2.1.0] - 2025-11-22, [2.2.0] - 2026-01-25, 2-Stage Agent Pipeline, ACWR v2 Implementation (+37 more)

### Community 7 - "TrainingAnalysisState"
Cohesion: 0.13
Nodes (21): Command, MessagesState, Protocol, AgentRole, Enum, extract_activity_data(), create_data_summarizer_node(), AgentType (+13 more)

### Community 8 - "create_initial_state"
Cohesion: 0.08
Nodes (36): combined_summarizer_node(), extract_combined_data(), formatter_node(), plot_resolution_node(), Any, synthesis_node(), create_initial_state(), Any (+28 more)

### Community 9 - "LangSmithCostExtractor"
Cohesion: 0.15
Nodes (14): Client, LangSmithCostExtractor, NodeCostSummary, Any, WorkflowCostSummary, ProgressIntegratedCostTracker, Any, WorkflowCostTracker (+6 more)

### Community 10 - "PlotReferenceResolver"
Cohesion: 0.11
Nodes (8): create_plotting_tools(), LangGraphPlottingTool, ProductionSecureExecutor, run_plot_code_get_html(), PlotReferenceResolver, Any, asyncio, TestPlottingToolIntegration

### Community 11 - "PlanParser"
Cohesion: 0.14
Nodes (14): Match, PlanParser, date, Parse the 28-day plan markdown or JSON into a list of ParsedWorkout objects., Split plan text into (date_str, block_text) tuples.          Uses a sliding wind, Try to parse a date string like 'Jun 02' or 'Jun 2' relative to start_date's yea, Classify and extract a single day's workout from its text block., Parse a structured intervals workout. (+6 more)

### Community 12 - "planning_workflow.py"
Cohesion: 0.19
Nodes (12): data_integration_node(), Any, master_orchestrator_node(), plan_formatter_node(), create_integrated_analysis_and_planning_workflow(), create_planning_workflow(), run_complete_analysis_and_planning(), run_weekly_planning() (+4 more)

### Community 13 - "GarminCalendarSyncer"
Cohesion: 0.13
Nodes (16): GarminCalendarSyncer, _HR_TARGET_TYPE(), Any, GarminCalendarSyncer: creates Garmin Connect workout objects and schedules worko, Upload a workout to Garmin's workout library with NO calendar date.          The, # NOTE: no schedule_workout() call here — caller decides when to schedule, Schedule an already-uploaded workout on today's calendar date.          This is, Delete all workouts from the Garmin library whose name starts with `prefix`. (+8 more)

### Community 14 - "_make_syncer"
Cohesion: 0.12
Nodes (15): _make_suggestion(), _make_syncer(), Tests for GarminCalendarSyncer — guards against workout accumulation on the watc, Workouts must NOT be scheduled on a date — they go to the library only., Exactly one workout template must be uploaded per pipeline run., Guard: all 'Coach:' workouts are deleted before upload., If library has >100 workouts, all pages must be fetched and cleaned., Guard: old calendar-dated workouts are always cleared. (+7 more)

### Community 15 - "Garmin AI Coach — Project Context & Memory"
Cohesion: 0.06
Nodes (35): ⏰ 6:20 AM Time-Gated WOTD Generation & Fallback, 🏃 Athlete Profile & Preferences (Arnab — updated 2026-07-13), Auto-Recalibration (every 10 runs), Do NOT run `graphify update .` after APPLYING a patch, Empirically Calibrated Zone Percentages (set 2026-07-13), Garmin AI Coach — Project Context & Memory, 🛠️ GitHub Actions SSH Deployment Pipeline, Goals (in priority order) (+27 more)

### Community 16 - "LangSmithConfig"
Cohesion: 0.21
Nodes (4): dict, configure_langsmith_for_user(), LangSmithConfig, TestLangGraphFoundation

### Community 17 - "combined_analyst_node.py"
Cohesion: 0.37
Nodes (20): activity_expert_node(), combined_analyst_node(), metrics_expert_node(), configure_node_tools(), create_cost_entry(), create_plot_entries(), execute_node_with_error_handling(), log_node_completion() (+12 more)

### Community 18 - ".get_llm"
Cohesion: 0.16
Nodes (16): AIMode, Config, get_config(), Enum, reload_config(), AISettings, Any, parametrize (+8 more)

### Community 19 - "logseq_client.py"
Cohesion: 0.06
Nodes (62): check_and_run(), _flush_pending_syncs(), _load_pending_syncs(), main(), Path, _queue_pending_sync(), Write sleep + weight to today's Logseq journal page.      WOTD is intentionally, Return the list of pending sync entries, or [] if none. (+54 more)

### Community 20 - "_make_syncer"
Cohesion: 0.13
Nodes (14): _make_syncer(), Tests for schedule_workout_for_today — guards against the watch sync regression., Guard: the two-step flow produces exactly one upload and one schedule call., The ID returned by upload must be the same ID passed to schedule., upload_workout_to_library must NOT schedule — that's schedule_workout_for_today', If upload fails, schedule should never be called., Regression: stale Coach: workouts must be deleted before each new upload, Guard: workout is always scheduled for today so it auto-syncs to watch. (+6 more)

### Community 21 - "Question"
Cohesion: 0.28
Nodes (15): AgentOutput, BaseModel, Question, Agent produces EITHER questions for HITL OR content for downstream consumers., ActivityExpertOutputs, CombinedAnalystOutputs, CombinedSummaryOutputs, ExpertOutputBase (+7 more)

### Community 22 - "Workout of the Day — Implementation Plan"
Cohesion: 0.10
Nodes (19): 1. Weighted run baseline (replaces flat last-10 average), 2. Sleep quality classification, 3. Weekday / weekend constraint, 4. AI prompt (single GPT-4o-mini call), 5. Delete yesterday's workout, 6. Push today's workout, Architecture: How It Fits Into the Existing System, Data Flow Diagram (+11 more)

### Community 23 - "TrainingMetricsCalculator"
Cohesion: 0.19
Nodes (4): Any, date, TrainingMetricsCalculator, TestTrainingMetricsCalculator

### Community 24 - "test_no_secrets_committed.py"
Cohesion: 0.28
Nodes (7): _parse_env_template(), parametrize, Path, Guard: no real secret may live in a tracked file., test_env_template_secret_is_a_sentinel(), test_no_bws_sentinel_bypassed_in_tracked_templates(), _tracked_text_files()

### Community 25 - "GarminConnectClient"
Cohesion: 0.06
Nodes (41): backfill(), One-off backfill of Garmin sleep/run metrics into the Logseq journal.  Writes vi, main(), mfa_callback(), Garmin, main(), GarminConnectClient, _call_ai_for_workout() (+33 more)

### Community 26 - "logseq_writer.py"
Cohesion: 0.18
Nodes (12): BaseHTTPRequestHandler, HealthHandler, _is_property_line(), journal_path(), main(), make_handler(), date, Path (+4 more)

### Community 27 - "render"
Cohesion: 0.39
Nodes (6): main(), Return the rendered .env text, or raise KeyError listing unmet sentinels., render(), test_render_fails_closed_for_missing_secret(), test_render_preserves_comments_and_blank_lines(), test_render_replaces_bws_sentinels()

### Community 28 - "planning_template.py"
Cohesion: 0.30
Nodes (14): _e(), Static HTML template for planning.html.  The LLM supplies structured JSON data;, HTML-escape a string., Render the full planning.html from structured data., _readiness_badge(), _render_forecast_section(), _render_hero_section(), render_planning_html() (+6 more)

### Community 29 - "2026-09-28 — Secrets resolved from Bitwarden at deploy time (`@bws` sentinel)"
Cohesion: 0.40
Nodes (4): 2026-09-28 — Secrets resolved from Bitwarden at deploy time (`@bws` sentinel), Consequences, Context, Decision

### Community 30 - "CostTracker"
Cohesion: 0.27
Nodes (4): AgentCostSummary, CostTracker, ModelUsage, Any

### Community 31 - "🛠️ Implemented Architectural Fix"
Cohesion: 0.18
Nodes (10): 1. 6:20 AM Cutoff Time Gate, 1. Premature State Mutation (The Core Issue), 2. Coupled Sleep Sync & WOTD Pushing, 2. Separate WOTD Pushing from Sleep Data Processing, 3. Update Marker Only AFTER Successful Push, 4. Automatic Hourly Retry Loop, Executive Summary, 🛠️ Implemented Architectural Fix (+2 more)

### Community 33 - "analysis_template.py"
Cohesion: 0.44
Nodes (9): _e(), Static HTML template for analysis.html (Physiology & Metrics tab).  The LLM supp, Render the full analysis.html from structured data., render_analysis_html(), _render_deep_dive(), _render_kpis(), _render_recommendations(), _render_summary() (+1 more)

### Community 34 - "fail"
Cohesion: 1.00
Nodes (3): fail(), log(), render_env.sh script

### Community 36 - "_parse_json_safely"
Cohesion: 0.50
Nodes (4): _parse_json_safely(), Remove ```json ... ``` or ``` ... ``` wrappers if present., Try to parse LLM output as JSON; return None on failure., _strip_fences()

### Community 37 - "2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data"
Cohesion: 0.29
Nodes (6): 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data, 2026-08-08 Resilience Fix & Model Alignment, Consequences, Context, Decision, Status

### Community 38 - "Exception"
Cohesion: 0.25
Nodes (5): Exception, APIOverloadError, RetryableError, If the library API fails, upload should proceed (not crash)., If one delete call fails, the rest should still be attempted.

### Community 39 - "PlotStorage"
Cohesion: 0.17
Nodes (4): PlotMetadata, PlotStorage, Any, HTMLPlotEmbedder

### Community 41 - "competition_models.py"
Cohesion: 0.67
Nodes (3): Competition, Enum, RacePriority

### Community 49 - "extract_expert_output"
Cohesion: 0.67
Nodes (5): extract_agent_content(), extract_expert_output(), _get_field(), Any, _render_receiver_payload()

### Community 50 - "2026-08-24 — Manual WOTD Dashboard Trigger"
Cohesion: 0.40
Nodes (4): 2026-08-24 — Manual WOTD Dashboard Trigger, Consequences, Context, Decision

### Community 51 - "2026-09-28 — HR zones unified in `services/garmin/hr_zones.py`"
Cohesion: 0.40
Nodes (4): 2026-09-28 — HR zones unified in `services/garmin/hr_zones.py`, Consequences, Context, Decision

### Community 52 - "zone_calibrator.py"
Cohesion: 0.19
Nodes (19): _cal_path(), _compute_new_percentages(), _extract_zone_boundaries(), _fetch_recent_run_zones(), increment_run_counter(), is_calibration_due(), load_calibration(), maybe_recalibrate() (+11 more)

### Community 53 - "HRZones"
Cohesion: 0.17
Nodes (8): HRZones, Resolved HR zones for the athlete, anchored on a live LTHR., Return Z1-Z5 as absolute bpm ranges.          Every boundary is anchored on LTHR, clean_corrupted_json(), datetime, Plan Parser: converts the AI weekly planner markdown output into structured work, Initialize PlanParser.          Args:             zones: The athlete's resolved, Remove invalid unicode/token corruptions printed outside JSON strings.      Thes

### Community 54 - "calibration_for"
Cohesion: 0.29
Nodes (6): calibration_for(), Path, Return the persisted zone calibration, or factory defaults.      Consumers that, Path, Build a parser from a live LTHR using the persisted calibration., test_plan_parser_honours_manual_zone_override()

## Knowledge Gaps
- **137 isolated node(s):** `garmin-ai-coach`, `Competition`, `startup.sh script`, `Project Overview`, `Tech Stack & Architecture` (+132 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GarminCalendarSyncer` connect `GarminCalendarSyncer` to `TriathlonCoachDataExtractor`, `run_analysis_from_config`, `Exception`, `_make_syncer`, `_make_syncer`, `GarminConnectClient`?**
  _High betweenness centrality (0.127) - this node is a cross-community bridge._
- **Why does `TriathlonCoachDataExtractor` connect `TriathlonCoachDataExtractor` to `GarminConnectClient`, `run_analysis_from_config`?**
  _High betweenness centrality (0.109) - this node is a cross-community bridge._
- **Why does `OutsideApiGraphQlClient` connect `OutsideApiGraphQlClient` to `run_analysis_from_config`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `TriathlonCoachDataExtractor` (e.g. with `GarminEncoder` and `GarminConnectClient`) actually correct?**
  _`TriathlonCoachDataExtractor` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `TrainingAnalysisState` (e.g. with `ConsoleInteractionProvider` and `InteractionProvider`) actually correct?**
  _`TrainingAnalysisState` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PlotStorage` (e.g. with `LangGraphPlottingTool` and `HTMLPlotEmbedder`) actually correct?**
  _`PlotStorage` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `garmin-ai-coach`, `Competition`, `startup.sh script` to the rest of the system?**
  _137 weakly-connected nodes found - possible documentation gaps or missing edges._