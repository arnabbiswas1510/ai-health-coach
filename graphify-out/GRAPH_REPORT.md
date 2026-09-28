# Graph Report - ai-health-coach  (2026-09-28)

## Corpus Check
- 118 files · ~109,856 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1198 nodes · 2883 edges · 49 communities (43 shown, 6 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 160 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `566fb292`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TriathlonCoachDataExtractor
- OutsideApiGraphQlClient
- main.py
- run_analysis_from_config
- generate_workout_of_the_day
- Technology Stack
- Changelog
- TrainingAnalysisState
- create_initial_state
- LangSmithCostExtractor
- PlotStorage
- PlanParser
- planning_workflow.py
- GarminCalendarSyncer
- _make_syncer
- Garmin AI Coach — Project Context & Memory
- LangSmithConfig
- analysis_workflow.py
- test_langgraph_poc.py
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
- TestWorkflowStability
- startup.sh
- competition_models.py
- decisions/README.md
- chat_api/__init__.py
- garmin-ai-coach
- 2026-08-24 — Manual WOTD Dashboard Trigger

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
- `TestPlottingToolIntegration` --uses--> `AgentRole`  [INFERRED]
  tests/test_plotting_tool_integration.py → services/ai/ai_settings.py
- `test_all_nodes_importable()` --indirect_call--> `formatter_node()`  [INFERRED]
  tests/test_langgraph_core_migration.py → services/ai/langgraph/nodes/formatter_node.py
- `TestLangGraphFoundation` --uses--> `TrainingAnalysisState`  [INFERRED]
  tests/test_langgraph_foundation.py → services/ai/langgraph/state/training_analysis_state.py
- `TestWorkflowDataFlow` --uses--> `TrainingAnalysisState`  [INFERRED]
  tests/test_langgraph_planning_workflow.py → services/ai/langgraph/state/training_analysis_state.py

## Import Cycles
- None detected.

## Communities (49 total, 6 thin omitted)

### Community 0 - "TriathlonCoachDataExtractor"
Cohesion: 0.06
Nodes (50): GarminEncoder, main(), Any, AdaptiveRunningCoach, Any, Dynamically adjusts and suggests the next run.          Redistributes missed mil, DataExtractor, _daterange() (+42 more)

### Community 1 - "OutsideApiGraphQlClient"
Cohesion: 0.05
Nodes (16): Client, dt, OutsideApiGraphQlClient, Any, datetime, CalendarNode, CalendarResult, Event (+8 more)

### Community 2 - "main.py"
Cohesion: 0.08
Nodes (51): delete, get, post, _apply_suggested_run_override(), _build_planning_context(), _build_run_reply(), _build_week_dates(), _build_wotd_status() (+43 more)

### Community 3 - "run_analysis_from_config"
Cohesion: 0.08
Nodes (28): ABC, ConfigParser, create_config_template(), fetch_outside_competitions_from_config(), get_weight_analysis_context(), main(), parse_height_to_cm(), Any (+20 more)

### Community 4 - "generate_workout_of_the_day"
Cohesion: 0.07
Nodes (49): _call_ai_for_workout(), _classify_recovery(), _extract_sleep_summary(), _fetch_hrv(), _fetch_run_dynamics(), _fetch_training_readiness(), generate_workout_of_the_day(), _push_wotd() (+41 more)

### Community 5 - "Technology Stack"
Cohesion: 0.04
Nodes (46): AI & LLM Providers, AI Orchestration & Observability, CLI Interface, Code Analysis, Code Quality, Configuration & Environment, Core Dependencies, Core Python Framework (+38 more)

### Community 6 - "Changelog"
Cohesion: 0.04
Nodes (45): [0.1.0] - Previous, [1.0.0] - 2025-10-14, [1.1.0] - 2025-10-17, [2.0.0] - 2025-11-02, [2.1.0] - 2025-11-22, [2.2.0] - 2026-01-25, 2-Stage Agent Pipeline, ACWR v2 Implementation (+37 more)

### Community 7 - "TrainingAnalysisState"
Cohesion: 0.07
Nodes (68): Command, AIMode, Config, get_config(), Enum, reload_config(), MessagesState, Protocol (+60 more)

### Community 8 - "create_initial_state"
Cohesion: 0.18
Nodes (12): create_initial_state(), Any, asyncio, test_metrics_summarizer_node_basic(), test_metrics_summarizer_with_empty_data(), test_physiology_summarizer_node_basic(), test_physiology_summarizer_with_empty_data(), basic_test_state() (+4 more)

### Community 9 - "LangSmithCostExtractor"
Cohesion: 0.17
Nodes (13): LangSmithCostExtractor, NodeCostSummary, Any, WorkflowCostSummary, ProgressIntegratedCostTracker, Any, WorkflowCostTracker, WorkflowExecution (+5 more)

### Community 10 - "PlotStorage"
Cohesion: 0.08
Nodes (12): create_plotting_tools(), LangGraphPlottingTool, PlotMetadata, PlotStorage, Any, ProductionSecureExecutor, run_plot_code_get_html(), HTMLPlotEmbedder (+4 more)

### Community 11 - "PlanParser"
Cohesion: 0.11
Nodes (19): Match, clean_corrupted_json(), PlanParser, date, datetime, Plan Parser: converts the AI weekly planner markdown output into structured work, Initialize PlanParser.          Args:             max_hr: Athlete's estimated ma, Parse the 28-day plan markdown or JSON into a list of ParsedWorkout objects. (+11 more)

### Community 12 - "planning_workflow.py"
Cohesion: 0.24
Nodes (13): data_integration_node(), Any, master_orchestrator_node(), plan_formatter_node(), create_integrated_analysis_and_planning_workflow(), create_planning_workflow(), Re-run only the planning branch using cached expert outputs.      Used by the, run_complete_analysis_and_planning() (+5 more)

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

### Community 17 - "analysis_workflow.py"
Cohesion: 0.27
Nodes (13): combined_summarizer_node(), extract_combined_data(), formatter_node(), plot_resolution_node(), Any, create_analysis_workflow(), create_simple_sequential_workflow(), run_training_analysis() (+5 more)

### Community 18 - "test_langgraph_poc.py"
Cohesion: 0.24
Nodes (9): asyncio, fixture, patch, Minimal tests for LangGraph proof of concept., sample_garmin_data(), sample_state(), test_metrics_expert_node_basic(), test_state_creation() (+1 more)

### Community 19 - "logseq_client.py"
Cohesion: 0.06
Nodes (64): check_and_run(), _flush_pending_syncs(), _load_pending_syncs(), main(), Path, _queue_pending_sync(), Write sleep + weight to today's Logseq journal page.      WOTD is intentionally, Return the list of pending sync entries, or [] if none. (+56 more)

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
Cohesion: 0.13
Nodes (11): backfill(), main(), mfa_callback(), Garmin, main(), GarminConnectClient, test_client_property_raises_if_not_connected(), test_connect_failure() (+3 more)

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

### Community 32 - "extract_text_content"
Cohesion: 0.18
Nodes (5): Exception, extract_text_content(), If the library API fails, upload should proceed (not crash)., If one delete call fails, the rest should still be attempted., TestExtractTextContent

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

### Community 41 - "competition_models.py"
Cohesion: 0.67
Nodes (3): Competition, Enum, RacePriority

### Community 50 - "2026-08-24 — Manual WOTD Dashboard Trigger"
Cohesion: 0.40
Nodes (4): 2026-08-24 — Manual WOTD Dashboard Trigger, Consequences, Context, Decision

## Knowledge Gaps
- **134 isolated node(s):** `garmin-ai-coach`, `Competition`, `startup.sh script`, `Project Overview`, `Tech Stack & Architecture` (+129 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GarminCalendarSyncer` connect `GarminCalendarSyncer` to `TriathlonCoachDataExtractor`, `extract_text_content`, `run_analysis_from_config`, `_make_syncer`, `_make_syncer`, `GarminConnectClient`?**
  _High betweenness centrality (0.155) - this node is a cross-community bridge._
- **Why does `TriathlonCoachDataExtractor` connect `TriathlonCoachDataExtractor` to `GarminConnectClient`, `run_analysis_from_config`?**
  _High betweenness centrality (0.098) - this node is a cross-community bridge._
- **Why does `OutsideApiGraphQlClient` connect `OutsideApiGraphQlClient` to `run_analysis_from_config`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `TriathlonCoachDataExtractor` (e.g. with `GarminEncoder` and `GarminConnectClient`) actually correct?**
  _`TriathlonCoachDataExtractor` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `TrainingAnalysisState` (e.g. with `ConsoleInteractionProvider` and `InteractionProvider`) actually correct?**
  _`TrainingAnalysisState` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PlotStorage` (e.g. with `LangGraphPlottingTool` and `HTMLPlotEmbedder`) actually correct?**
  _`PlotStorage` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `garmin-ai-coach`, `Competition`, `startup.sh script` to the rest of the system?**
  _134 weakly-connected nodes found - possible documentation gaps or missing edges._