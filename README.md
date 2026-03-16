# Job Hunting Agent

An agentic job search tool built with the Anthropic SDK native tool use API. The agent decides which tools to call based on user input, executes them, and loops until it has a final answer — no LangChain or external agent framework required.

## Architecture

- **Framework**: Anthropic SDK native tool use (`client.messages.create` with `tools=` parameter)
- **Tool registration**: Each tool is defined as a JSON schema dict; the model selects and invokes tools based on descriptions
- **Agent loop**: Runs until `stop_reason == "end_turn"` — on `tool_use`, executes tools and feeds results back into the conversation
- **Memory**: Sliding window of last 10 messages for short-term context; `applications.json` for persistent application tracking
- **Trigger**: CLI input loop (`job_agent.py`) or Gradio web UI (`app.py`)

## Tools

| Tool | What it does |
|---|---|
| `search_jobs` | Google Jobs via SerpAPI — broad job search |
| `fetch_ats_jobs` | Hits Greenhouse/Lever public APIs directly for live company listings |
| `score_job_fit` | LLM scores 0–100 fit against your profile with gap analysis |
| `tailor_resume` | Rewrites resume summary + top bullets for a specific JD |
| `track_application` | Saves application status to `applications.json` |
| `view_applications` | Displays tracker table, filterable by status |

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file:
```
ANTHROPIC_API_KEY=your_key
SERPAPI_API_KEY=your_key   # free tier at serpapi.com (100 searches/month)
```

Edit `profile.yaml` with your experience, then run:

```bash
# CLI
python job_agent.py

# Gradio web UI
python app.py
```

## Example prompts

```
> search for AI engineer new grad 2026 biotech
> fetch jobs at recursion
> fetch jobs at ramp / lever
> fetch jobs at citadel
> score my fit for [paste full job description]
> tailor my resume for [paste full job description]
> track SystImmune / Applied AI Engineer I / applied
> show all my applications
```

## ATS Slugs

**Greenhouse**: `recursion` `genentech` `citadel` `palantir` `openai` `anthropic` `twosigma`

**Lever**: `ramp` `stripe` `notion` `scale-ai` `tempus-ex` `jane-street`
