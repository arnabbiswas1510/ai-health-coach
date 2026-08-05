# Graph Report - ai-health-coach  (2026-08-05)

## Corpus Check
- 110 files · ~105,340 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1120 nodes · 2764 edges · 47 communities (41 shown, 6 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 160 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6d3105f1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TriathlonCoachDataExtractor
- OutsideApiGraphQlClient
- logseq_client.py
- main.py
- run_analysis_from_config
- Technology Stack
- generate_workout_of_the_day
- Changelog
- combined_analyst_node.py
- TrainingAnalysisState
- LangSmithCostExtractor
- PlanParser
- PlotReferenceResolver
- create_initial_state
- planning_workflow.py
- GarminCalendarSyncer
- _make_syncer
- .get_llm
- GarminConnectClient
- _make_syncer
- Workout of the Day — Implementation Plan
- TrainingMetricsCalculator
- Garmin AI Coach — Project Context & Memory
- analysis_workflow.py
- logseq_writer.py
- planning_template.py
- LangSmithConfig
- CostTracker
- AgentRole
- extract_text_content
- analysis_template.py
- PlotStorage
- Exception
- ProxyHTTPRequestHandler
- startup.sh
- calendar_syncer.py
- competition_models.py
- HTMLPlotEmbedder
- chat_api/__init__.py
- garmin-ai-coach
- 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data
- extract_expert_output
- decisions/README.md

## God Nodes (most connected - your core abstractions)
1. `OutsideApiGraphQlClient` - 75 edges
2. `TriathlonCoachDataExtractor` - 67 edges
3. `TrainingAnalysisState` - 58 edges
4. `TestOutsideApiGraphQlClient` - 47 edges
5. `PlotStorage` - 43 edges
6. `run_analysis_from_config()` - 36 edges
7. `AgentRole` - 33 edges
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

## Communities (47 total, 6 thin omitted)

### Community 0 - "TriathlonCoachDataExtractor"
Cohesion: 0.06
Nodes (50): GarminEncoder, main(), Any, AdaptiveRunningCoach, Any, Dynamically adjusts and suggests the next run. Redistributes missed mileage and…, DataExtractor, _daterange() (+42 more)

### Community 1 - "OutsideApiGraphQlClient"
Cohesion: 0.05
Nodes (15): dt, OutsideApiGraphQlClient, Any, datetime, CalendarNode, CalendarResult, Event, EventCategory (+7 more)

### Community 2 - "logseq_client.py"
Cohesion: 0.06
Nodes (64): check_and_run(), _flush_pending_syncs(), _load_pending_syncs(), main(), Path, _queue_pending_sync(), Write sleep + weight to today's Logseq journal page. WOTD is intentionally NOT…, Return the list of pending sync entries, or [] if none. (+56 more)

### Community 3 - "main.py"
Cohesion: 0.07
Nodes (53): delete, get, post, AgentOutput, BaseModel, Question, Agent produces EITHER questions for HITL OR content for downstream consumers., ActivityExpertOutputs (+45 more)

### Community 4 - "run_analysis_from_config"
Cohesion: 0.09
Nodes (23): ABC, ConfigParser, create_config_template(), fetch_outside_competitions_from_config(), get_weight_analysis_context(), main(), parse_height_to_cm(), Any (+15 more)

### Community 5 - "Technology Stack"
Cohesion: 0.04
Nodes (46): AI & LLM Providers, AI Orchestration & Observability, CLI Interface, Code Analysis, Code Quality, Configuration & Environment, Core Dependencies, Core Python Framework (+38 more)

### Community 6 - "generate_workout_of_the_day"
Cohesion: 0.08
Nodes (46): _call_ai_for_workout(), _classify_recovery(), _extract_sleep_summary(), _fetch_hrv(), _fetch_run_dynamics(), _fetch_training_readiness(), generate_workout_of_the_day(), _push_wotd() (+38 more)

### Community 7 - "Changelog"
Cohesion: 0.04
Nodes (45): [0.1.0] - Previous, [1.0.0] - 2025-10-14, [1.1.0] - 2025-10-17, [2.0.0] - 2025-11-02, [2.1.0] - 2025-11-22, [2.2.0] - 2026-01-25, 2-Stage Agent Pipeline, ACWR v2 Implementation (+37 more)

### Community 8 - "combined_analyst_node.py"
Cohesion: 0.29
Nodes (22): activity_expert_node(), combined_analyst_node(), metrics_expert_node(), configure_node_tools(), create_cost_entry(), create_plot_entries(), execute_node_with_error_handling(), log_node_completion() (+14 more)

### Community 9 - "TrainingAnalysisState"
Cohesion: 0.19
Nodes (11): Command, MessagesState, Protocol, extract_activity_data(), extract_metrics_data(), ConsoleInteractionProvider, InteractionProvider, master_orchestrator_node() (+3 more)

### Community 10 - "LangSmithCostExtractor"
Cohesion: 0.15
Nodes (14): Client, LangSmithCostExtractor, NodeCostSummary, Any, WorkflowCostSummary, ProgressIntegratedCostTracker, Any, WorkflowCostTracker (+6 more)

### Community 11 - "PlanParser"
Cohesion: 0.13
Nodes (15): Match, PlanParser, date, Initialize PlanParser. Args: max_hr: Athlete's estimated max heart rate…, Parse the 28-day plan markdown or JSON into a list of ParsedWorkout objects.…, Split plan text into (date_str, block_text) tuples. Uses a sliding window: each…, Try to parse a date string like 'Jun 02' or 'Jun 2' relative to start_date's…, Classify and extract a single day's workout from its text block. (+7 more)

### Community 12 - "PlotReferenceResolver"
Cohesion: 0.11
Nodes (8): create_plotting_tools(), LangGraphPlottingTool, ProductionSecureExecutor, run_plot_code_get_html(), PlotReferenceResolver, Any, asyncio, TestPlottingToolIntegration

### Community 13 - "create_initial_state"
Cohesion: 0.15
Nodes (13): create_initial_state(), Any, asyncio, test_metrics_summarizer_node_basic(), test_metrics_summarizer_with_empty_data(), test_physiology_summarizer_node_basic(), test_physiology_summarizer_with_empty_data(), basic_test_state() (+5 more)

### Community 14 - "planning_workflow.py"
Cohesion: 0.14
Nodes (18): data_integration_node(), Any, plan_formatter_node(), create_integrated_analysis_and_planning_workflow(), create_planning_workflow(), _get_chat_panel_html(), _inject_chat_panel(), _inject_iframe_helpers() (+10 more)

### Community 15 - "GarminCalendarSyncer"
Cohesion: 0.14
Nodes (14): GarminCalendarSyncer, _HR_TARGET_TYPE(), Any, Upload a workout to Garmin's workout library with NO calendar date. The athlete…, Schedule an already-uploaded workout on today's calendar date. This is the key…, Delete all workouts from the Garmin library whose name starts with `prefix`.…, Build and schedule a single workout. Returns workout_id string., Warmup → steady HR-zone run → cooldown. (+6 more)

### Community 16 - "_make_syncer"
Cohesion: 0.12
Nodes (15): _make_suggestion(), _make_syncer(), Tests for GarminCalendarSyncer — guards against workout accumulation on the…, Workouts must NOT be scheduled on a date — they go to the library only., Exactly one workout template must be uploaded per pipeline run., Guard: all 'Coach:' workouts are deleted before upload., If library has >100 workouts, all pages must be fetched and cleaned., Guard: old calendar-dated workouts are always cleared. (+7 more)

### Community 17 - ".get_llm"
Cohesion: 0.16
Nodes (16): AIMode, Config, get_config(), Enum, reload_config(), AISettings, Any, parametrize (+8 more)

### Community 18 - "GarminConnectClient"
Cohesion: 0.13
Nodes (11): backfill(), main(), mfa_callback(), Garmin, main(), GarminConnectClient, test_client_property_raises_if_not_connected(), test_connect_failure() (+3 more)

### Community 19 - "_make_syncer"
Cohesion: 0.13
Nodes (14): _make_syncer(), Tests for schedule_workout_for_today — guards against the watch sync…, Guard: the two-step flow produces exactly one upload and one schedule call., The ID returned by upload must be the same ID passed to schedule., upload_workout_to_library must NOT schedule — that's…, If upload fails, schedule should never be called., Regression: stale Coach: workouts must be deleted before each new upload so the…, Guard: workout is always scheduled for today so it auto-syncs to watch. (+6 more)

### Community 20 - "Workout of the Day — Implementation Plan"
Cohesion: 0.10
Nodes (19): 1. Weighted run baseline (replaces flat last-10 average), 2. Sleep quality classification, 3. Weekday / weekend constraint, 4. AI prompt (single GPT-4o-mini call), 5. Delete yesterday's workout, 6. Push today's workout, Architecture: How It Fits Into the Existing System, Data Flow Diagram (+11 more)

### Community 21 - "TrainingMetricsCalculator"
Cohesion: 0.19
Nodes (4): Any, date, TrainingMetricsCalculator, TestTrainingMetricsCalculator

### Community 22 - "Garmin AI Coach — Project Context & Memory"
Cohesion: 0.11
Nodes (18): ⏰ 6:20 AM Time-Gated WOTD Generation & Fallback, 🏃 Athlete Profile & Preferences (Arnab — updated 2026-07-13), Auto-Recalibration (every 10 runs), Empirically Calibrated Zone Percentages (set 2026-07-13), Garmin AI Coach — Project Context & Memory, 🛠️ GitHub Actions SSH Deployment Pipeline, Goals (in priority order), Key Rules & Guidelines (+10 more)

### Community 23 - "analysis_workflow.py"
Cohesion: 0.14
Nodes (23): combined_summarizer_node(), extract_combined_data(), formatter_node(), plot_resolution_node(), Any, synthesis_node(), create_analysis_workflow(), create_simple_sequential_workflow() (+15 more)

### Community 24 - "logseq_writer.py"
Cohesion: 0.18
Nodes (12): BaseHTTPRequestHandler, HealthHandler, _is_property_line(), journal_path(), main(), make_handler(), date, Path (+4 more)

### Community 25 - "planning_template.py"
Cohesion: 0.30
Nodes (14): _e(), Static HTML template for planning.html. The LLM supplies structured JSON data;…, HTML-escape a string., Render the full planning.html from structured data., _readiness_badge(), _render_forecast_section(), _render_hero_section(), render_planning_html() (+6 more)

### Community 26 - "LangSmithConfig"
Cohesion: 0.21
Nodes (4): dict, configure_langsmith_for_user(), LangSmithConfig, TestLangGraphFoundation

### Community 27 - "CostTracker"
Cohesion: 0.27
Nodes (4): AgentCostSummary, CostTracker, ModelUsage, Any

### Community 28 - "AgentRole"
Cohesion: 0.19
Nodes (15): AgentRole, Enum, create_data_summarizer_node(), AgentType, Any, _parse_json_safely(), Formatter Node (analysis.html / Physiology & Metrics tab). Asks the LLM for a…, _strip_fences() (+7 more)

### Community 30 - "analysis_template.py"
Cohesion: 0.44
Nodes (9): _e(), Static HTML template for analysis.html (Physiology & Metrics tab). The LLM…, Render the full analysis.html from structured data., render_analysis_html(), _render_deep_dive(), _render_kpis(), _render_recommendations(), _render_summary() (+1 more)

### Community 31 - "PlotStorage"
Cohesion: 0.20
Nodes (3): PlotMetadata, PlotStorage, Any

### Community 32 - "Exception"
Cohesion: 0.29
Nodes (5): Exception, APIOverloadError, RetryableError, If the library API fails, upload should proceed (not crash)., If one delete call fails, the rest should still be attempted.

### Community 34 - "startup.sh"
Cohesion: 0.53
Nodes (4): die(), log(), ok(), startup.sh script

### Community 35 - "calendar_syncer.py"
Cohesion: 0.25
Nodes (6): GarminCalendarSyncer: creates Garmin Connect workout objects and schedules…, # NOTE: no schedule_workout() call here — caller decides when to schedule, clean_corrupted_json(), datetime, Plan Parser: converts the AI weekly planner markdown output into structured…, Remove invalid unicode/token corruptions printed outside JSON strings. These…

### Community 36 - "competition_models.py"
Cohesion: 0.67
Nodes (3): Competition, Enum, RacePriority

### Community 44 - "2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data"
Cohesion: 0.33
Nodes (5): 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data, Consequences, Context, Decision, Status

### Community 45 - "extract_expert_output"
Cohesion: 0.67
Nodes (5): extract_agent_content(), extract_expert_output(), _get_field(), Any, _render_receiver_payload()

## Knowledge Gaps
- **106 isolated node(s):** `garmin-ai-coach`, `Competition`, `Project Overview`, `Tech Stack & Architecture`, `Key Rules & Guidelines` (+101 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GarminCalendarSyncer` connect `GarminCalendarSyncer` to `TriathlonCoachDataExtractor`, `Exception`, `calendar_syncer.py`, `run_analysis_from_config`, `_make_syncer`, `GarminConnectClient`, `_make_syncer`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **Why does `TriathlonCoachDataExtractor` connect `TriathlonCoachDataExtractor` to `GarminConnectClient`, `run_analysis_from_config`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Why does `write_daily_properties()` connect `logseq_client.py` to `run_analysis_from_config`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `TriathlonCoachDataExtractor` (e.g. with `GarminEncoder` and `GarminConnectClient`) actually correct?**
  _`TriathlonCoachDataExtractor` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `TrainingAnalysisState` (e.g. with `ConsoleInteractionProvider` and `InteractionProvider`) actually correct?**
  _`TrainingAnalysisState` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PlotStorage` (e.g. with `LangGraphPlottingTool` and `HTMLPlotEmbedder`) actually correct?**
  _`PlotStorage` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `garmin-ai-coach`, `Competition`, `Project Overview` to the rest of the system?**
  _106 weakly-connected nodes found - possible documentation gaps or missing edges._