# Job Hunting Agent

A LangChain ReAct agent with 5 registered tools for end-to-end job search automation.

## Setup

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY=your_key
export SERPAPI_API_KEY=your_key   # free tier: https://serpapi.com (100 searches/month)
```

Edit `profile.yaml` with your real experience, then:

```bash
python job_agent.py
```

## Tools

| Tool | What it does |
|---|---|
| `search_jobs` | Google Jobs via SerpAPI — returns titles, companies, locations |
| `score_job_fit` | LLM scores 0–100 fit against your profile; lists gaps |
| `tailor_resume` | Rewrites your summary + top bullets for a specific JD |
| `track_application` | Saves application status to `applications.json` |
| `view_applications` | Displays tracker table, filterable by status |

## Example prompts

```
> search for applied AI engineer jobs biotech
> score my fit for [paste full job description]
> tailor my resume for [paste full job description]
> track {"company":"SystImmune","role":"Applied AI Engineer I","status":"applied","notes":"submitted 2026-03-16"}
> show all my applications
> show rejected applications
```

## Architecture notes (for application question)

- **Framework**: LangChain `create_react_agent` + `AgentExecutor`
- **Tool registration**: `@tool` decorator — LangChain reads docstring as tool description
- **Memory**: `ConversationBufferWindowMemory(k=6)` for short-term context; `applications.json` for persistent state
- **Trigger**: CLI input loop; each user message triggers a new ReAct reasoning cycle
- **Verbose mode**: set `verbose=True` in AgentExecutor to watch the full Thought/Action/Observation chain
