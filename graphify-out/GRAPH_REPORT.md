# Graph Report - ai-health-coach  (2026-09-29)

## Corpus Check
- 140 files · ~131,157 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1576 nodes · 3607 edges · 75 communities (69 shown, 6 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 165 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `32797be7`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- zone_calibrator.py
- OutsideApiGraphQlClient
- main.py
- run_analysis_from_config
- TriathlonCoachDataExtractor
- Technology Stack
- Changelog
- AgentRole
- analysis_workflow.py
- LangSmithCostExtractor
- PlotStorage
- PlanParser
- TrainingAnalysisState
- GarminCalendarSyncer
- _make_syncer
- Garmin AI Coach — Project Context & Memory
- LangSmithConfig
- combined_analyst_node.py
- .get_llm
- test_withings_credential_store.py
- _make_syncer
- Question
- Workout of the Day — Implementation Plan
- TrainingMetricsCalculator
- test_no_secrets_committed.py
- generate_workout_of_the_day
- logseq_writer.py
- test_render_env.py
- planning_template.py
- 2026-09-28 — Secrets resolved from Bitwarden at deploy time (`@bws` sentinel)
- CostTracker
- 🛠️ Implemented Architectural Fix
- extract_text_content
- analysis_template.py
- fail
- ProxyHTTPRequestHandler
- feedback_adr.py
- 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data
- test_shell_scripts_parse.py
- test_deploy_image_pipeline.py
- startup.sh
- competition_models.py
- decisions/README.md
- chat_api/__init__.py
- garmin-ai-coach
- extract_expert_output
- 2026-08-24 — Manual WOTD Dashboard Trigger
- 2026-09-28 — HR zones unified in `services/garmin/hr_zones.py`
- Production consumes the published image instead of building on the host
- AdaptiveRunningCoach
- .env.template declares every key docker-compose.yml reads
- Withings credential durability via Bitwarden
- GarminConnectClient
- record_feedback
- create_initial_state
- test_chat_api_feedback.py
- Decision
- feedback/__init__.py
- load_weighted_feedback
- detect_timing
- logseq_client.py
- Scope secrets to one Bitwarden project, reduce the mandatory set to six, and actually run the renderer
- FakeLLM
- compute_zones
- test_dashboard_layout.py
- Dashboard shell moves out of the repository root into frontend/
- test_hr_zones.py
- Exception
- hr_zones.py
- test_withings_token_guard.py
- A deploy must prove production is running the code it just published

## God Nodes (most connected - your core abstractions)
1. `OutsideApiGraphQlClient` - 75 edges
2. `TriathlonCoachDataExtractor` - 67 edges
3. `TrainingAnalysisState` - 58 edges
4. `TestOutsideApiGraphQlClient` - 47 edges
5. `PlotStorage` - 43 edges
6. `AgentRole` - 37 edges
7. `run_analysis_from_config()` - 36 edges
8. `record_feedback()` - 34 edges
9. `generate_workout_of_the_day()` - 32 edges
10. `GarminCalendarSyncer` - 30 edges

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

## Communities (75 total, 6 thin omitted)

### Community 0 - "zone_calibrator.py"
Cohesion: 0.19
Nodes (19): _cal_path(), _compute_new_percentages(), _extract_zone_boundaries(), _fetch_recent_run_zones(), increment_run_counter(), is_calibration_due(), load_calibration(), maybe_recalibrate() (+11 more)

### Community 1 - "OutsideApiGraphQlClient"
Cohesion: 0.05
Nodes (16): Client, dt, OutsideApiGraphQlClient, Any, datetime, CalendarNode, CalendarResult, Event (+8 more)

### Community 2 - "main.py"
Cohesion: 0.06
Nodes (65): delete, get, post, _apply_suggested_run_override(), _build_planning_context(), _build_run_reply(), _build_week_dates(), _build_wotd_status() (+57 more)

### Community 3 - "run_analysis_from_config"
Cohesion: 0.10
Nodes (22): ABC, ConfigParser, create_config_template(), fetch_outside_competitions_from_config(), get_weight_analysis_context(), main(), parse_height_to_cm(), Any (+14 more)

### Community 4 - "TriathlonCoachDataExtractor"
Cohesion: 0.07
Nodes (43): GarminEncoder, main(), Any, DataExtractor, _daterange(), _deep_get(), _dg(), _merge_missing() (+35 more)

### Community 5 - "Technology Stack"
Cohesion: 0.04
Nodes (46): AI & LLM Providers, AI Orchestration & Observability, CLI Interface, Code Analysis, Code Quality, Configuration & Environment, Core Dependencies, Core Python Framework (+38 more)

### Community 6 - "Changelog"
Cohesion: 0.04
Nodes (45): [0.1.0] - Previous, [1.0.0] - 2025-10-14, [1.1.0] - 2025-10-17, [2.0.0] - 2025-11-02, [2.1.0] - 2025-11-22, [2.2.0] - 2026-01-25, 2-Stage Agent Pipeline, ACWR v2 Implementation (+37 more)

### Community 7 - "AgentRole"
Cohesion: 0.17
Nodes (15): AgentRole, Enum, create_data_summarizer_node(), AgentType, Any, _parse_json_safely(), Formatter Node (analysis.html / Physiology & Metrics tab).  Asks the LLM for a s, _strip_fences() (+7 more)

### Community 8 - "analysis_workflow.py"
Cohesion: 0.24
Nodes (15): combined_summarizer_node(), extract_combined_data(), formatter_node(), plot_resolution_node(), Any, synthesis_node(), create_analysis_workflow(), create_simple_sequential_workflow() (+7 more)

### Community 9 - "LangSmithCostExtractor"
Cohesion: 0.17
Nodes (13): LangSmithCostExtractor, NodeCostSummary, Any, WorkflowCostSummary, ProgressIntegratedCostTracker, Any, WorkflowCostTracker, WorkflowExecution (+5 more)

### Community 10 - "PlotStorage"
Cohesion: 0.08
Nodes (12): create_plotting_tools(), LangGraphPlottingTool, PlotMetadata, PlotStorage, Any, ProductionSecureExecutor, run_plot_code_get_html(), HTMLPlotEmbedder (+4 more)

### Community 11 - "PlanParser"
Cohesion: 0.11
Nodes (18): Match, clean_corrupted_json(), PlanParser, date, datetime, Initialize PlanParser.          Args:             zones: The athlete's resolved, Parse the 28-day plan markdown or JSON into a list of ParsedWorkout objects., Split plan text into (date_str, block_text) tuples.          Uses a sliding wind (+10 more)

### Community 12 - "TrainingAnalysisState"
Cohesion: 0.09
Nodes (28): Command, MessagesState, Protocol, extract_activity_data(), data_integration_node(), Any, extract_metrics_data(), ConsoleInteractionProvider (+20 more)

### Community 13 - "GarminCalendarSyncer"
Cohesion: 0.13
Nodes (16): GarminCalendarSyncer, _HR_TARGET_TYPE(), Any, GarminCalendarSyncer: creates Garmin Connect workout objects and schedules worko, Upload a workout to Garmin's workout library with NO calendar date.          The, # NOTE: no schedule_workout() call here — caller decides when to schedule, Schedule an already-uploaded workout on today's calendar date.          This is, Delete all workouts from the Garmin library whose name starts with `prefix`. (+8 more)

### Community 14 - "_make_syncer"
Cohesion: 0.12
Nodes (15): _make_suggestion(), _make_syncer(), Tests for GarminCalendarSyncer — guards against workout accumulation on the watc, Workouts must NOT be scheduled on a date — they go to the library only., Exactly one workout template must be uploaded per pipeline run., Guard: all 'Coach:' workouts are deleted before upload., If library has >100 workouts, all pages must be fetched and cleaned., Guard: old calendar-dated workouts are always cleared. (+7 more)

### Community 15 - "Garmin AI Coach — Project Context & Memory"
Cohesion: 0.08
Nodes (25): ⏰ 6:20 AM Time-Gated WOTD Generation & Fallback, 🏃 Athlete Profile & Preferences (Arnab — updated 2026-07-13), Auto-Recalibration (every 10 runs), Empirically Calibrated Zone Percentages (set 2026-07-13), Garmin AI Coach — Project Context & Memory, 🛠️ GitHub Actions SSH Deployment Pipeline, Goals (in priority order), Key Rules & Guidelines (+17 more)

### Community 16 - "LangSmithConfig"
Cohesion: 0.21
Nodes (4): dict, configure_langsmith_for_user(), LangSmithConfig, TestLangGraphFoundation

### Community 17 - "combined_analyst_node.py"
Cohesion: 0.37
Nodes (20): activity_expert_node(), combined_analyst_node(), metrics_expert_node(), configure_node_tools(), create_cost_entry(), create_plot_entries(), execute_node_with_error_handling(), log_node_completion() (+12 more)

### Community 18 - ".get_llm"
Cohesion: 0.16
Nodes (16): AIMode, Config, get_config(), Enum, reload_config(), AISettings, Any, parametrize (+8 more)

### Community 19 - "test_withings_credential_store.py"
Cohesion: 0.07
Nodes (55): PathLike, _bws_binary(), credential_path(), _digest(), _digest_path(), _find_secret(), push_to_vault(), Path (+47 more)

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
Cohesion: 0.20
Nodes (13): _compose_referenced_keys(), _parse_env_template(), parametrize, Path, Guard: no real secret may live in a tracked file., .env is rendered wholesale from the template, so gaps are silent.      A key ref, Every sentinel in the template must be a declared key.      Each @bws line adds, test_every_template_sentinel_is_a_known_secret_key() (+5 more)

### Community 25 - "generate_workout_of_the_day"
Cohesion: 0.09
Nodes (42): _call_ai_for_workout(), _classify_recovery(), _extract_sleep_summary(), _fetch_hrv(), _fetch_run_dynamics(), _fetch_training_readiness(), generate_workout_of_the_day(), _push_wotd() (+34 more)

### Community 26 - "logseq_writer.py"
Cohesion: 0.18
Nodes (12): BaseHTTPRequestHandler, HealthHandler, _is_property_line(), journal_path(), main(), make_handler(), date, Path (+4 more)

### Community 27 - "test_render_env.py"
Cohesion: 0.06
Nodes (54): build_secret_map(), main(), Map a Bitwarden project name to its id, or raise LookupError., Index secrets by key, scoped to a project and refusing ambiguous keys.      A ma, Return the rendered .env text, or raise KeyError listing unmet sentinels.      T, render(), resolve_project_id(), _resolve_project_mode() (+46 more)

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

### Community 36 - "feedback_adr.py"
Cohesion: 0.14
Nodes (22): _apply_supersession(), _classify_feedback(), _default_classification(), _dump_front_matter(), FeedbackADR, _mirror_to_logseq(), _parse_adr(), _parse_front_matter() (+14 more)

### Community 37 - "2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data"
Cohesion: 0.29
Nodes (6): 2026-08-05 — 6:20 AM Time-Gated WOTD Generation and Fallback Sleep Data, 2026-08-08 Resilience Fix & Model Alignment, Consequences, Context, Decision, Status

### Community 38 - "test_shell_scripts_parse.py"
Cohesion: 0.15
Nodes (14): _bash(), parametrize, Path, r"""Guards that every committed shell script is syntactically valid.  `startup.s, Guard the guard: a bad glob would make every test below vacuous., `bash -n` parses without executing -- catches unterminated strings., `log "msg"` must print msg, not an empty string., die() must interpolate its argument, not print a hardcoded word. (+6 more)

### Community 39 - "test_deploy_image_pipeline.py"
Cohesion: 0.12
Nodes (16): _deploy_script(), _mount_targets(), parametrize, Guards on the image-based deploy pipeline.  CI publishes ghcr.io/<repo>:latest o, A restarting container must abort the deploy, not pass silently., The running container must prove it is the commit just published., /version can only be meaningful if CI bakes the SHA in at build time., The fix removed source mounts; it must not have removed data mounts. (+8 more)

### Community 40 - "startup.sh"
Cohesion: 0.53
Nodes (4): die(), log(), ok(), startup.sh script

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

### Community 52 - "Production consumes the published image instead of building on the host"
Cohesion: 0.33
Nodes (5): Consequences, Context, Decision, Production consumes the published image instead of building on the host, Verification

### Community 53 - "AdaptiveRunningCoach"
Cohesion: 0.15
Nodes (19): AdaptiveRunningCoach, Any, Path, Dynamically adjusts and suggests the next run.          Redistributes missed mil, calibration_for(), Path, Return the persisted zone calibration, or factory defaults.      Consumers that, Activity (+11 more)

### Community 54 - ".env.template declares every key docker-compose.yml reads"
Cohesion: 0.33
Nodes (5): Consequences, Context, Decision, .env.template declares every key docker-compose.yml reads, Verification

### Community 55 - "Withings credential durability via Bitwarden"
Cohesion: 0.33
Nodes (5): Alternatives considered, Consequences, Context, Decision, Withings credential durability via Bitwarden

### Community 56 - "GarminConnectClient"
Cohesion: 0.14
Nodes (10): main(), mfa_callback(), Garmin, main(), GarminConnectClient, test_client_property_raises_if_not_connected(), test_connect_failure(), test_connect_successful() (+2 more)

### Community 57 - "record_feedback"
Cohesion: 0.24
Nodes (19): load_feedback_adrs(), Load all feedback ADRs, newest first., Classify a free-text note, persist it as an ADR and retire what it replaces., record_feedback(), _llm(), fixture, Tests for athlete daily feedback ADRs and their use in WOTD generation., test_cannot_supersede_across_categories() (+11 more)

### Community 58 - "create_initial_state"
Cohesion: 0.11
Nodes (20): create_initial_state(), Any, asyncio, test_metrics_summarizer_node_basic(), test_metrics_summarizer_with_empty_data(), test_physiology_summarizer_node_basic(), test_physiology_summarizer_with_empty_data(), basic_test_state() (+12 more)

### Community 59 - "test_chat_api_feedback.py"
Cohesion: 0.12
Nodes (6): data_dir(), FakeLLM, fixture, API tests for daily feedback capture and the Garmin-gated workout mirror., test_delete_feedback_removes_entry(), test_recent_feedback_is_newest_first()

### Community 60 - "Decision"
Cohesion: 0.15
Nodes (12): 1. Storage — server volume, not the repository, 2026-09-28 — Daily Athlete Feedback as Recency-Weighted ADRs, 2. Classification — one fast LLM call at submit time, 3. Supersession — true ADR semantics, 4. Recency weighting — mirrors the existing run baseline, 5. Authority — advisory but bounded (Rule 12), 6. Timing — auto-detected, never asked, 7. WOTD visibility — strictly gated on the Garmin push (+4 more)

### Community 61 - "feedback/__init__.py"
Cohesion: 0.22
Nodes (10): delete_feedback(), feedback_dir(), Path, Render weighted feedback as a prompt section for the WOTD AI., Delete one feedback ADR by id. Returns True if a file was removed., render_feedback_prompt_block(), Athlete-authored daily feedback, stored as recency-weighted ADRs., parametrize (+2 more)

### Community 62 - "load_weighted_feedback"
Cohesion: 0.39
Nodes (8): load_weighted_feedback(), Return active feedback from the recency window, newest first, weighted.      Wei, _seed(), test_entries_outside_window_are_dropped(), test_entry_count_is_capped(), test_prompt_block_is_ordered_and_carries_weights(), test_superseded_entries_excluded_from_weighting(), test_weights_decay_with_age_and_order_newest_first()

### Community 63 - "detect_timing"
Cohesion: 0.29
Nodes (7): detect_timing(), date, Infer whether a note is a pre-workout heads-up or a post-run report.      Derive, test_timing_is_issued_not_run_when_wotd_pushed_but_no_run(), test_timing_is_post_run_after_a_run_is_logged(), test_timing_is_pre_workout_when_nothing_pushed_yet(), test_yesterdays_run_does_not_mark_today_as_post_run()

### Community 64 - "logseq_client.py"
Cohesion: 0.06
Nodes (66): backfill(), One-off backfill of Garmin sleep/run metrics into the Logseq journal.  Writes vi, check_and_run(), _flush_pending_syncs(), _load_pending_syncs(), main(), date, Path (+58 more)

### Community 65 - "Scope secrets to one Bitwarden project, reduce the mandatory set to six, and actually run the renderer"
Cohesion: 0.40
Nodes (4): Consequences, Context, Decision, Scope secrets to one Bitwarden project, reduce the mandatory set to six, and actually run the renderer

### Community 67 - "compute_zones"
Cohesion: 0.18
Nodes (14): compute_zones(), Build the full zone set from a live LTHR and calibrated percentages.      A manu, Path, Build a parser from a live LTHR using the persisted calibration., _default_calibration(), Z1-Z5 must tile without gaps and every edge must derive from LTHR., PlanParser must not reintroduce its own age-derived max-HR zone table., The old bug produced Z2 = 100-120 bpm; assert we are nowhere near it. (+6 more)

### Community 68 - "test_dashboard_layout.py"
Cohesion: 0.29
Nodes (3): parametrize, Guards on the dashboard's location in the repository tree.  The dashboard shell, test_references_point_at_the_new_location()

### Community 69 - "Dashboard shell moves out of the repository root into frontend/"
Cohesion: 0.33
Nodes (5): Consequences, Context, Dashboard shell moves out of the repository root into frontend/, Decision, Verification

### Community 70 - "test_hr_zones.py"
Cohesion: 0.22
Nodes (15): get_hr_zones(), Any, Resolve LTHR and return the athlete's zones.      Args:         recalibrate: whe, Return the athlete's current LTHR from Garmin.      Priority:       1. ``get_use, resolve_lthr(), _client_with_profile_lthr(), Path, Zone consistency between WOTD and post-run coaching feedback.  Regression guard (+7 more)

### Community 72 - "Exception"
Cohesion: 0.25
Nodes (5): Exception, APIOverloadError, RetryableError, If the library API fails, upload should proceed (not crash)., If one delete call fails, the rest should still be attempted.

### Community 73 - "hr_zones.py"
Cohesion: 0.25
Nodes (5): HRZones, Single source of truth for the athlete's heart-rate zones.  Both WOTD generation, Resolved HR zones for the athlete, anchored on a live LTHR., Return Z1-Z5 as absolute bpm ranges.          Every boundary is anchored on LTHR, Plan Parser: converts the AI weekly planner markdown output into structured work

### Community 74 - "test_withings_token_guard.py"
Cohesion: 0.17
Nodes (11): fixture, The Withings sync must skip cleanly when its OAuth token is absent.  withings-sy, No token file -> one actionable warning, no Garmin login, no traceback., The skip must be a clean early return, not an error path., Pin the executable guard, not merely a comment mentioning the filename., Guard the guard: importorskip must not be masking a real import break., test_daemon_module_imports_cleanly(), test_guard_is_present_in_source() (+3 more)

### Community 76 - "A deploy must prove production is running the code it just published"
Cohesion: 0.25
Nodes (7): 1. The container must reach a stable running state, 2. The container must report the commit that was just published, A deploy must prove production is running the code it just published, Alternatives considered, Consequences, Context, Decision

## Knowledge Gaps
- **162 isolated node(s):** `garmin-ai-coach`, `Competition`, `Project Overview`, `Tech Stack & Architecture`, `Key Rules & Guidelines` (+157 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OutsideApiGraphQlClient` connect `OutsideApiGraphQlClient` to `run_analysis_from_config`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `TriathlonCoachDataExtractor` connect `TriathlonCoachDataExtractor` to `GarminConnectClient`, `run_analysis_from_config`, `AdaptiveRunningCoach`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Why does `write_props_dict()` connect `logseq_client.py` to `feedback_adr.py`, `AgentRole`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `TriathlonCoachDataExtractor` (e.g. with `GarminEncoder` and `GarminConnectClient`) actually correct?**
  _`TriathlonCoachDataExtractor` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `TrainingAnalysisState` (e.g. with `ConsoleInteractionProvider` and `InteractionProvider`) actually correct?**
  _`TrainingAnalysisState` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PlotStorage` (e.g. with `LangGraphPlottingTool` and `HTMLPlotEmbedder`) actually correct?**
  _`PlotStorage` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `garmin-ai-coach`, `Competition`, `Project Overview` to the rest of the system?**
  _162 weakly-connected nodes found - possible documentation gaps or missing edges._