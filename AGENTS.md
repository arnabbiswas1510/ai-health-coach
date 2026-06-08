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

## Memory & Decisions
* Add project-specific technical decisions and active work tasks here to keep the agent aligned across sessions.
