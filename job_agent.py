"""
Job Hunting Agent — Anthropic SDK native tool use (no LangChain).
Trigger: CLI input loop (`python job_agent.py`)
Memory:  sliding window of last 10 messages + file-backed application tracker
"""

import os
import sys
import json
import yaml
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import anthropic

# ── Config ───────────────────────────────────────────────────────────────────
PROFILE_PATH  = Path("profile.yaml")
TRACKER_PATH  = Path("applications.json")
MODEL         = "claude-sonnet-4-20250514"
MAX_TOKENS    = 1024
MEMORY_WINDOW = 10
SERPAPI_KEY   = os.environ.get("SERPAPI_API_KEY", "")
client        = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {"error": f"{PROFILE_PATH} not found — fill in profile.yaml"}
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f)

def load_tracker() -> list:
    if not TRACKER_PATH.exists():
        return []
    with open(TRACKER_PATH) as f:
        return json.load(f)

def save_tracker(data: list):
    with open(TRACKER_PATH, "w") as f:
        json.dump(data, f, indent=2)

# ── Tool implementations ──────────────────────────────────────────────────────

def search_jobs(query: str) -> str:
    if not SERPAPI_KEY:
        return (
            "SERPAPI_API_KEY not set.\n"
            "Add to .env: SERPAPI_API_KEY=your_key\n"
            "Free key at https://serpapi.com (100 searches/month)."
        )
    try:
        r = requests.get(
            "https://serpapi.com/search",
            params={"engine": "google_jobs", "q": query,
                    "api_key": SERPAPI_KEY, "num": 10},
            timeout=15,
        )
        r.raise_for_status()
        jobs = r.json().get("jobs_results", [])
        if not jobs:
            return "No results. Try a broader query."
        lines = []
        for i, j in enumerate(jobs[:8], 1):
            lines.append(
                f"{i}. {j.get('title','?')} @ {j.get('company_name','?')} "
                f"— {j.get('location','?')}\n"
                f"   {j.get('description','')[:160].strip()}..."
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def fetch_ats_jobs(company_slug: str, platform: str = "greenhouse") -> str:
    """Fetch live job listings from Greenhouse or Lever ATS public APIs."""
    try:
        if platform == "greenhouse":
            url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
        elif platform == "lever":
            url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        else:
            return f"Unknown platform '{platform}'. Use 'greenhouse' or 'lever'."

        r = requests.get(url, timeout=15)
        if r.status_code == 404:
            return f"Slug '{company_slug}' not found on {platform}. Try a different slug or platform."
        r.raise_for_status()
        data = r.json()

        if platform == "greenhouse":
            jobs = data.get("jobs", [])
        else:
            jobs = data if isinstance(data, list) else []

        if not jobs:
            return f"No open roles at {company_slug} on {platform}."

        # Filter for relevant roles
        keywords = [
            "machine learning", "ml ", "ai ", "artificial intelligence",
            "data scientist", "data engineer", "applied scientist",
            "quantitative", "quant", "software engineer", "nlp",
            "deep learning", "research engineer", "research scientist",
            "python", "statistician", "analyst"
        ]
        relevant = []
        all_roles = []
        for j in jobs:
            title = j.get("title", "")
            if platform == "greenhouse":
                location = j.get("location", {}).get("name", "N/A")
                link = j.get("absolute_url", "")
            else:
                location = j.get("categories", {}).get("location", "N/A")
                link = j.get("hostedUrl", "")
            entry = f"- {title} | {location}\n  {link}"
            all_roles.append(entry)
            if any(k in title.lower() for k in keywords):
                relevant.append(entry)

        if relevant:
            header = f"{company_slug} ({platform}) — {len(relevant)} relevant role(s):\n"
            return header + "\n".join(relevant)
        else:
            header = f"{company_slug} ({platform}) — no ML/AI/data roles found. All {len(all_roles)} open roles:\n"
            return header + "\n".join(all_roles[:15])

    except Exception as e:
        return f"ATS fetch failed: {e}"


def score_job_fit(job_description: str) -> str:
    try:
        profile = load_profile()
        resp = client.messages.create(
            model=MODEL, max_tokens=600,
            messages=[{"role": "user", "content":
                f"""You are a senior technical recruiter. Score this candidate's fit.

CANDIDATE PROFILE:
{yaml.dump(profile, default_flow_style=False)}

JOB DESCRIPTION:
{job_description[:3000]}

Respond EXACTLY in this format:
FIT SCORE: <0-100>

RATIONALE: <1 paragraph>

GAPS:
- <gap 1>
- <gap 2>
- <gap 3>
"""}]
        )
        return resp.content[0].text
    except Exception as e:
        return f"Scoring failed: {e}"


def tailor_resume(job_description: str) -> str:
    try:
        profile = load_profile()
        resp = client.messages.create(
            model=MODEL, max_tokens=800,
            messages=[{"role": "user", "content":
                f"""You are a professional resume writer. Using ONLY the experience in the
candidate profile, produce:
1. A tailored 3-sentence resume summary for this job
2. Top 5 most relevant bullet points from their experience
3. Keywords from the JD to naturally weave in

Do NOT invent experience. Flag genuine gaps honestly.

CANDIDATE PROFILE:
{yaml.dump(profile, default_flow_style=False)}

JOB DESCRIPTION:
{job_description[:3000]}
"""}]
        )
        return resp.content[0].text
    except Exception as e:
        return f"Tailoring failed: {e}"


def track_application(company: str, role: str, status: str, notes: str = "") -> str:
    valid = {"applied", "phone_screen", "interview", "offer", "rejected", "withdrawn"}
    if status not in valid:
        return f"Invalid status '{status}'. Choose from: {', '.join(valid)}"
    entry = {
        "company": company, "role": role, "status": status,
        "notes": notes, "updated": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    apps = load_tracker()
    for i, a in enumerate(apps):
        if a["company"].lower() == company.lower() and a["role"].lower() == role.lower():
            apps[i] = entry
            save_tracker(apps)
            return f"Updated: {company} — {role} → {status}"
    apps.append(entry)
    save_tracker(apps)
    return f"Tracked: {company} — {role} ({status})"


def view_applications(status_filter: str = "all") -> str:
    apps = load_tracker()
    if not apps:
        return "No applications tracked yet."
    if status_filter != "all":
        apps = [a for a in apps if a.get("status") == status_filter]
    if not apps:
        return f"No applications with status '{status_filter}'."
    lines = [f"{'COMPANY':<22} {'ROLE':<35} {'STATUS':<15} {'UPDATED':<17} NOTES"]
    lines.append("─" * 95)
    for a in sorted(apps, key=lambda x: x.get("updated", ""), reverse=True):
        lines.append(
            f"{a.get('company','?'):<22} {a.get('role','?')[:34]:<35} "
            f"{a.get('status','?'):<15} {a.get('updated','?'):<17} "
            f"{a.get('notes','')[:30]}"
        )
    return "\n".join(lines)


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_jobs",
        "description": "Search for job listings using Google Jobs. Good for broad searches across companies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query e.g. 'AI engineer biotech 2026 new grad'"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_ats_jobs",
        "description": (
            "Fetch live job listings directly from a specific company's ATS (Greenhouse or Lever). "
            "More reliable than search for specific companies. "
            "Greenhouse slugs: recursion, genentech, citadel, palantir, openai, anthropic, stripe. "
            "Lever slugs: ramp, notion, scale-ai, tempus-ex, jane-street."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_slug": {"type": "string", "description": "Company ATS slug e.g. 'recursion', 'ramp', 'stripe'"},
                "platform": {"type": "string", "enum": ["greenhouse", "lever"], "description": "ATS platform (default: greenhouse)"}
            },
            "required": ["company_slug"]
        }
    },
    {
        "name": "score_job_fit",
        "description": "Score how well the candidate profile matches a job description. Returns 0-100 score, rationale, and gaps.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_description": {"type": "string", "description": "Full job description text"}
            },
            "required": ["job_description"]
        }
    },
    {
        "name": "tailor_resume",
        "description": "Rewrite the candidate resume summary and highlight relevant bullets for a specific job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_description": {"type": "string", "description": "Full job description text"}
            },
            "required": ["job_description"]
        }
    },
    {
        "name": "track_application",
        "description": "Add or update a job application in the local tracker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company":  {"type": "string"},
                "role":     {"type": "string"},
                "status":   {"type": "string", "enum": ["applied", "phone_screen", "interview", "offer", "rejected", "withdrawn"]},
                "notes":    {"type": "string"}
            },
            "required": ["company", "role", "status"]
        }
    },
    {
        "name": "view_applications",
        "description": "View tracked job applications, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "enum": ["all", "applied", "phone_screen", "interview", "offer", "rejected", "withdrawn"]
                }
            },
            "required": []
        }
    }
]

TOOL_FN_MAP = {
    "search_jobs":       lambda i: search_jobs(i["query"]),
    "fetch_ats_jobs":    lambda i: fetch_ats_jobs(i["company_slug"], i.get("platform", "greenhouse")),
    "score_job_fit":     lambda i: score_job_fit(i["job_description"]),
    "tailor_resume":     lambda i: tailor_resume(i["job_description"]),
    "track_application": lambda i: track_application(i["company"], i["role"], i["status"], i.get("notes", "")),
    "view_applications": lambda i: view_applications(i.get("status_filter", "all")),
}

SYSTEM = """You are a job-hunting assistant helping a candidate find, evaluate, and track jobs.
The candidate is a 2026 new grad (Math + Econ, Hamilton College) with ML/AI engineering experience.
Target areas: biotech AI, healthcare AI, tech, fintech/quant.
Use fetch_ats_jobs for specific companies, search_jobs for broad searches.
Be concise in final answers."""

# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(user_input: str, history: list) -> tuple:
    history.append({"role": "user", "content": user_input})

    while True:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=TOOLS,
            messages=history,
        )

        history.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    print(f"  [tool] {block.name}({json.dumps(block.input)[:80]})")
                    result = TOOL_FN_MAP[block.name](block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            history.append({"role": "user", "content": tool_results})
            continue

        final = next((b.text for b in resp.content if hasattr(b, "text")), "")
        return final, history


# ── CLI ───────────────────────────────────────────────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════╗
║           Job Hunting Agent  v2.1                    ║
║  Tools: search · fetch · score · tailor · track      ║
║  Type 'quit' to exit, 'apps' to view tracker         ║
╚══════════════════════════════════════════════════════╝
Examples:
  > search for AI engineer new grad 2026 fintech
  > fetch jobs at recursion
  > fetch jobs at ramp / lever
  > fetch jobs at citadel
  > score my fit for [paste job description]
  > tailor my resume for [paste job description]
  > track Citadel / Quant Researcher / applied
  > show all my applications
"""


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in .env or environment.")

    print(BANNER)
    history = []

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break
        if user_input.lower() in ("apps", "applications"):
            print(view_applications("all"))
            continue

        # Trim history but never start on orphaned tool_result
        if len(history) > MEMORY_WINDOW:
            history = history[-MEMORY_WINDOW:]
            while history and not (
                isinstance(history[0].get("content"), str) and
                history[0].get("role") == "user"
            ):
                history = history[1:]

        try:
            answer, history = run_agent(user_input, history)
            print(f"\n{answer}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()