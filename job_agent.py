"""
Job Hunting Agent v3.4 — Multi-Agent + Daily Board + Triage + Distance + City Score
─────────────────────────────────────────────────────────────────────────────────────
Changes from v3.3:
  - distance_from_princeton() — miles from Princeton NJ to job location
  - city_livability_score() — 0-100 quality of life score per city
  - quick_score() factors in both distance and livability
  - quick_score_batch() still parallel (10 threads)
  - Remote = 0 miles, score 95
"""

import os, sys, json, yaml, re, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────
PROFILE_PATH  = Path("profile.yaml")
TRACKER_PATH  = Path("applications.json")
BOARD_CACHE   = Path(".board_cache.json")
MODEL         = "claude-sonnet-4-20250514"
MAX_TOKENS    = 4096
MEMORY_WINDOW = 20
SERPAPI_KEY   = os.environ.get("SERPAPI_API_KEY", "")
client        = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

SLUG_ALIASES = {
    "recursion":  ["recursionpharmaceuticals", "recursionpharma"],
    "twosigma":   ["two-sigma"],
    "deshaw":     ["de-shaw"],
    "janest":     ["jane-street"],
    "scaleai":    ["scale-ai"],
}

# ── Distance from Princeton NJ (miles) ───────────────────────────────────────
PRINCETON_DISTANCES: dict[str, int] = {
    "remote": 0, "anywhere": 0, "distributed": 0, "work from home": 0, "wfh": 0,
    "princeton": 0, "new jersey": 20, "nj": 20,
    # NJ/NY corridor
    "new york": 60, "nyc": 60, "manhattan": 60, "brooklyn": 65,
    "jersey city": 55, "hoboken": 55, "newark": 45,
    "new brunswick": 15, "trenton": 12,
    # Mid-Atlantic
    "philadelphia": 45, "philly": 45, "wilmington": 70,
    "washington dc": 190, "dc": 190, "baltimore": 150,
    "pittsburgh": 370, "harrisburg": 120,
    # Northeast
    "boston": 310, "cambridge": 315, "new haven": 160,
    "hartford": 200, "providence": 280, "albany": 200,
    # Southeast
    "raleigh": 490, "durham": 495, "charlotte": 570,
    "atlanta": 840, "miami": 1200, "orlando": 1060,
    "richmond": 310, "norfolk": 380,
    # Midwest
    "chicago": 760, "columbus": 480, "cleveland": 430,
    "detroit": 570, "minneapolis": 1100, "st. louis": 870,
    "kansas city": 1100, "indianapolis": 590, "milwaukee": 840,
    "cincinnati": 570,
    # South / Texas
    "austin": 1530, "dallas": 1440, "houston": 1530,
    "san antonio": 1600, "nashville": 900,
    # Mountain
    "denver": 1700, "salt lake city": 2100, "phoenix": 2350,
    # West Coast
    "seattle": 2850, "san francisco": 2880, "sf": 2880,
    "bay area": 2880, "silicon valley": 2880, "san jose": 2900,
    "los angeles": 2750, "la": 2750, "san diego": 2750,
    "portland": 2850, "palo alto": 2890,
    # Canada
    "toronto": 500, "montreal": 600, "vancouver": 2850, "ontario": 500,
    # UK / Europe
    "london": 3500, "dublin": 3600,
    "zurich": 4000, "zürich": 4000, "geneva": 4100,
    "munich": 4400, "münchen": 4400, "berlin": 4200,
    "paris": 3700, "amsterdam": 3700, "stockholm": 4200,
    # Asia / Pacific
    "tokyo": 6800, "seoul": 6900, "sydney": 10000, "melbourne": 10200,
}

# ── City livability score (0-100) ─────────────────────────────────────────────
# Factors: safety, cost of living balance, tech scene, quality of life
# Higher = better overall for a new grad moving there
CITY_SCORES: dict[str, int] = {
    "remote": 95,
    "princeton": 88, "new jersey": 75,
    # NJ/NY
    "new york": 74, "nyc": 74, "manhattan": 74, "brooklyn": 72,
    "jersey city": 73, "hoboken": 76, "newark": 55,
    # Mid-Atlantic
    "philadelphia": 68, "philly": 68, "wilmington": 70,
    "washington dc": 72, "dc": 72, "baltimore": 58,
    "pittsburgh": 80,  # underrated, very livable
    # Northeast
    "boston": 80, "cambridge": 83,
    "new haven": 68, "hartford": 62,
    # Southeast
    "raleigh": 86, "durham": 80,  # Research Triangle — great for data/ML
    "charlotte": 78, "nashville": 79,
    "atlanta": 68,  # traffic + crime in some areas
    "miami": 70,  # expensive, some crime
    "orlando": 72,
    # Midwest
    "chicago": 62,  # good city but gun violence is real concern
    "columbus": 76,
    "cleveland": 63,
    "detroit": 52,  # high crime
    "minneapolis": 74,
    "st. louis": 58,  # high crime rate
    "kansas city": 65,
    "indianapolis": 68,
    "milwaukee": 60,
    "cincinnati": 70,
    # South / Texas
    "austin": 82,  # great city, growing fast
    "dallas": 72,
    "houston": 70,
    "san antonio": 68,
    # Mountain
    "denver": 80,
    "salt lake city": 82,
    "phoenix": 72,
    # West Coast
    "seattle": 78,
    "san francisco": 65,  # high cost + safety concerns downtown
    "sf": 65, "bay area": 68, "silicon valley": 74, "palo alto": 80,
    "san jose": 74,
    "los angeles": 68,  # traffic, cost, uneven safety
    "la": 68, "san diego": 80,
    "portland": 68,
    # Canada
    "toronto": 82, "montreal": 83, "vancouver": 80,
    # UK / Europe (generally very safe, high quality)
    "london": 80, "dublin": 85,
    "zurich": 95, "zürich": 95, "geneva": 93,
    "munich": 90, "münchen": 90, "berlin": 82,
    "paris": 78, "amsterdam": 88, "stockholm": 92,
    # Asia / Pacific
    "tokyo": 90, "seoul": 85,
    "sydney": 88, "melbourne": 90,
}


def distance_from_princeton(location: str) -> int:
    """Return miles from Princeton NJ. Returns 0 for remote, -1 if unknown."""
    if not location:
        return -1
    loc = location.lower()
    if any(w in loc for w in ("remote", "anywhere", "distributed", "work from home", "wfh")):
        return 0
    for city, miles in PRINCETON_DISTANCES.items():
        if city in loc:
            return miles
    if re.search(r'\b[A-Z]{2}\b', location):
        return 1000  # domestic unknown — neutral
    return -1


def city_livability(location: str) -> int:
    """Return livability score 0-100. Returns -1 if unknown."""
    if not location:
        return -1
    loc = location.lower()
    if any(w in loc for w in ("remote", "anywhere", "distributed", "work from home", "wfh")):
        return 95
    for city, score in CITY_SCORES.items():
        if city in loc:
            return score
    return -1  # unknown


def distance_label(miles: int) -> str:
    if miles == 0:   return "Remote / Local 🏠"
    if miles < 100:  return f"~{miles} mi (nearby)"
    if miles < 500:  return f"~{miles} mi (driveable)"
    if miles < 1500: return f"~{miles} mi (domestic flight)"
    return f"~{miles} mi (international)"


def livability_label(score: int) -> str:
    if score < 0:   return ""
    if score >= 90: return f"⭐ {score}/100 livability"
    if score >= 80: return f"✅ {score}/100 livability"
    if score >= 70: return f"🟡 {score}/100 livability"
    return f"⚠️ {score}/100 livability"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {"error": f"{PROFILE_PATH} not found"}
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

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# ── Tool implementations ───────────────────────────────────────────────────────

def search_jobs(query: str) -> str:
    if not SERPAPI_KEY:
        return "SERPAPI_API_KEY not set."
    try:
        r = requests.get(
            "https://serpapi.com/search",
            params={"engine": "google_jobs", "q": query, "api_key": SERPAPI_KEY, "num": 10},
            timeout=15,
        )
        r.raise_for_status()
        jobs = r.json().get("jobs_results", [])
        if not jobs:
            return "No results. Try broader query."
        lines = []
        for i, j in enumerate(jobs[:8], 1):
            lines.append(
                f"{i}. {j.get('title','?')} @ {j.get('company_name','?')} — {j.get('location','?')}\n"
                f"   {j.get('description','')[:160].strip()}..."
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def fetch_ats_jobs(company_slug: str, platform: str = "greenhouse") -> str:
    def _get(slug, plat):
        url = (
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
            if plat == "greenhouse"
            else f"https://api.lever.co/v0/postings/{slug}?mode=json"
        )
        return requests.get(url, timeout=15), url

    try:
        r, url = _get(company_slug, platform)
        if r.status_code == 404:
            for alt in SLUG_ALIASES.get(company_slug.lower(), []):
                r2, _ = _get(alt, platform)
                if r2.status_code == 200:
                    r, company_slug = r2, alt
                    break
            else:
                other = "lever" if platform == "greenhouse" else "greenhouse"
                return f"Slug '{company_slug}' not found on {platform}. Try '{other}'."
        r.raise_for_status()
        data = r.json()
        jobs = data.get("jobs", []) if platform == "greenhouse" else (data if isinstance(data, list) else [])
        if not jobs:
            return f"No open roles at {company_slug} on {platform}."

        keywords = [
            "machine learning", "ml ", "ai ", "artificial intelligence",
            "data scientist", "data engineer", "applied scientist",
            "quantitative", "quant", "software engineer", "nlp",
            "deep learning", "research engineer", "research scientist",
            "python", "statistician", "analyst",
        ]
        relevant, all_roles = [], []
        for j in jobs:
            title    = j.get("title", "")
            location = j.get("location", {}).get("name", "N/A") if platform == "greenhouse" else j.get("categories", {}).get("location", "N/A")
            link     = j.get("absolute_url", "") if platform == "greenhouse" else j.get("hostedUrl", "")
            entry    = f"- {title} | {location}\n  {link}"
            all_roles.append(entry)
            if any(k in title.lower() for k in keywords):
                relevant.append(entry)

        if relevant:
            return f"{company_slug} ({platform}) — {len(relevant)} relevant role(s):\n" + "\n".join(relevant)
        return f"{company_slug} ({platform}) — no ML/data roles. All {len(all_roles)} open:\n" + "\n".join(all_roles[:15])
    except Exception as e:
        return f"ATS fetch failed: {e}"


def fetch_job_description(company_slug: str, role_query: str, platform: str = "greenhouse") -> str:
    try:
        def _get(slug, plat):
            url = (
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
                if plat == "greenhouse"
                else f"https://api.lever.co/v0/postings/{slug}?mode=json"
            )
            return requests.get(url, timeout=15)

        r = _get(company_slug, platform)
        if r.status_code == 404:
            for alt in SLUG_ALIASES.get(company_slug.lower(), []):
                r2 = _get(alt, platform)
                if r2.status_code == 200:
                    r, company_slug = r2, alt
                    break
            else:
                other = "lever" if platform == "greenhouse" else "greenhouse"
                return f"Slug '{company_slug}' not found. Try '{other}'."
        r.raise_for_status()
        data = r.json()
        jobs = data.get("jobs", []) if platform == "greenhouse" else (data if isinstance(data, list) else [])
        if not jobs:
            return f"No open roles at {company_slug}."

        query_lower = role_query.lower()
        best, best_score = None, 0
        for j in jobs:
            title = j.get("title", "").lower()
            score = sum(1 for w in query_lower.split() if w in title)
            if score > best_score:
                best_score, best = score, j

        if not best or best_score == 0:
            titles = [j.get("title", "?") for j in jobs[:10]]
            return "No close match. Available:\n" + "\n".join(f"- {t}" for t in titles)

        if platform == "greenhouse":
            title    = best.get("title", "?")
            location = best.get("location", {}).get("name", "N/A")
            link     = best.get("absolute_url", "")
            content  = strip_html(best.get("content", ""))
        else:
            title    = best.get("text", "?")
            location = best.get("categories", {}).get("location", "N/A")
            link     = best.get("hostedUrl", "")
            content  = strip_html("\n\n".join(
                f"{l.get('text','')}\n{l.get('content','')}"
                for l in best.get("lists", [])
            ))

        return f"ROLE: {title}\nLOCATION: {location}\nURL: {link}\n\nDESCRIPTION:\n{content[:4000]}"
    except Exception as e:
        return f"JD fetch failed: {e}"


def quick_score(title: str, company: str, location: str,
                miles: int = -1, livability: int = -1) -> str:
    """
    Fast triage factoring role fit, distance from Princeton NJ, and city livability.
    Returns 'Strong', 'Maybe', or 'Skip'.
    """
    try:
        profile = load_profile()

        if miles == 0:
            loc_context = "Location: Remote or local (ideal — no relocation needed)"
        elif miles > 0:
            qual = livability_label(livability) if livability >= 0 else ""
            loc_context = (
                f"Distance from Princeton NJ: ~{miles} miles  |  "
                f"City livability: {livability}/100{' (' + qual + ')' if qual else ''}"
            )
        else:
            loc_context = "Distance: unknown"

        resp = client.messages.create(
            model=MODEL, max_tokens=10,
            messages=[{"role": "user", "content":
                f"""You are triaging job applications. Reply with ONLY one word.

CANDIDATE: {profile.get('resume_summary', '')}
TARGET ROLES: {profile.get('target_roles', [])}
TARGET INDUSTRIES: {profile.get('target_industries', [])}
HOME BASE: Princeton, NJ — prefers NYC metro, remote, or willing to relocate for a strong role.

JOB: {title} at {company} ({location})
{loc_context}

Factor in BOTH role fit AND location quality. Remote/nearby = strong bonus.
International is fine for excellent roles. Low livability cities = slight penalty.
Reply ONLY one word: Strong, Maybe, or Skip."""}]
        )
        text = resp.content[0].text.strip().lower()
        if "strong" in text: return "Strong"
        if "skip"   in text: return "Skip"
        return "Maybe"
    except Exception:
        return "Maybe"


def quick_score_batch(jobs: list[dict], max_workers: int = 10) -> list[dict]:
    """Score jobs in parallel. Writes triage, distance_miles, distance_label,
    livability_score, livability_label into each dict."""
    to_score = [j for j in jobs if not j.get("triage")]
    if not to_score:
        return jobs

    print(f"  [Triage] Scoring {len(to_score)} jobs in parallel ({max_workers} threads)...",
          end="", flush=True)

    def _score(job):
        loc   = job.get("location", "")
        miles = distance_from_princeton(loc)
        liv   = city_livability(loc)
        job["distance_miles"]    = miles
        job["distance_label"]    = distance_label(miles) if miles >= 0 else ""
        job["livability_score"]  = liv
        job["livability_label"]  = livability_label(liv) if liv >= 0 else ""
        job["triage"] = quick_score(
            job.get("role", ""), job.get("company", ""), loc, miles, liv
        )
        return job

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_score, j): j for j in to_score}
        done = 0
        for f in as_completed(futures):
            done += 1
            if done % 20 == 0:
                print(f" {done}/{len(to_score)}", end="", flush=True)
            try:
                f.result()
            except Exception:
                pass

    print(" done.")
    return jobs


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
                f"""You are a professional resume writer. Using ONLY the experience in the profile, produce:
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


def generate_cover_letter(job_description: str, company: str, role: str) -> str:
    try:
        profile      = load_profile()
        style_sample = profile.get("cover_letter_sample", "")
        resp = client.messages.create(
            model=MODEL, max_tokens=800,
            messages=[{"role": "user", "content":
                f"""You are a professional cover letter writer. Write a concise, specific cover letter.

Rules:
- 3 paragraphs max
- DO NOT start with "I am excited to" — start with substance
- Opening: lead with who the candidate is and why THIS company/role specifically
- Middle: 2-3 most relevant projects/experiences with concrete details and numbers
- Closing: one specific sentence referencing what the company does, then sign off
- Do NOT use: "excited to", "passionate about", "eager to learn", "eager to grow",
  "I would love to", "thrilled", "looking forward to", "be part of your team"
- Do NOT invent experience
- Address: Dear {company} Hiring Team

CANDIDATE PROFILE:
{yaml.dump(profile, default_flow_style=False)}

STYLE REFERENCE — match this tone, structure, and specificity exactly:
{style_sample}

COMPANY: {company}
ROLE: {role}

JOB DESCRIPTION:
{job_description[:3000]}
"""}]
        )
        return resp.content[0].text
    except Exception as e:
        return f"Cover letter generation failed: {e}"


def track_application(company: str, role: str, status: str, notes: str = "") -> str:
    valid = {"applied", "pending", "phone_screen", "interview", "offer", "rejected", "withdrawn"}
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


# ── Daily Board ───────────────────────────────────────────────────────────────

BOARD_SOURCES = [
    {"name": "jobright · Data/ML New Grad 2026",
     "url": "https://raw.githubusercontent.com/jobright-ai/2026-Data-Analysis-New-Grad/master/README.md"},
    {"name": "speedyapply · AI/ML New Grad 2026",
     "url": "https://raw.githubusercontent.com/speedyapply/2026-AI-College-Jobs/main/README.md"},
    {"name": "SimplifyJobs · New Grad Positions",
     "url": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"},
]

BOARD_KEYWORDS = {
    "data scientist", "data analyst", "ml engineer", "machine learning",
    "quantitative", "quant", "applied scientist", "research scientist",
    "data engineer", "nlp", "ai engineer", "statistician", "research analyst",
    "analytics engineer",
}

def _md_extract(cell: str) -> tuple[str, str]:
    cell = re.sub(r"<[^>]+>", "", cell).strip()
    cell = re.sub(r"<\S*",    "", cell).strip()
    m = re.search(r'\[([^\]]+)\]\(([^)]+)\)', cell)
    return (m.group(1).strip(), m.group(2).strip()) if m else (cell.strip(), "")

def _is_relevant(title: str) -> bool:
    return any(kw in title.lower() for kw in BOARD_KEYWORDS)

def _parse_md_table(text: str, source_name: str, limit: int = 150) -> list[dict]:
    jobs, header_found, col_map = [], False, {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"): continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells: continue
        if not header_found:
            lower_cells = [c.lower() for c in cells]
            if any(kw in " ".join(lower_cells) for kw in ["company", "job", "title", "role"]):
                for i, c in enumerate(lower_cells):
                    if "company" in c:                                                  col_map["company"]  = i
                    elif "job" in c or "title" in c or "role" in c or "position" in c: col_map["role"]     = i
                    elif "location" in c or "city" in c:                               col_map["location"] = i
                    elif "date" in c or "posted" in c or "added" in c:                 col_map["date"]     = i
                if col_map: header_found = True
            continue
        if all(set(c.replace("-","").replace("|","").strip()) <= {""} for c in cells): continue
        if not col_map: continue

        def get_col(name, fallback="?"):
            idx = col_map.get(name)
            if idx is None or idx >= len(cells): return fallback, ""
            return _md_extract(cells[idx])

        company,  _    = get_col("company")
        role,     link = get_col("role")
        location, _    = get_col("location")
        date_str, _    = get_col("date")
        if company in ("?","") or role in ("?",""): continue
        if not _is_relevant(role): continue
        jobs.append({"company": company[:40], "role": role[:60],
                     "location": location[:30], "date": date_str[:12],
                     "link": link, "source": source_name})
        if len(jobs) >= limit: break
    return jobs


def _fetch_serpapi_jobs(queries: list[str], per_query: int = 5) -> list[dict]:
    if not SERPAPI_KEY: return []
    results = []
    for q in queries:
        try:
            r = requests.get("https://serpapi.com/search",
                params={"engine": "google_jobs", "q": q, "api_key": SERPAPI_KEY, "num": per_query},
                timeout=10)
            if r.status_code == 200:
                for j in r.json().get("jobs_results", []):
                    results.append({
                        "company":  j.get("company_name","?")[:40],
                        "role":     j.get("title","?")[:60],
                        "location": j.get("location","?")[:30],
                        "date":     j.get("detected_extensions",{}).get("posted_at","?")[:12],
                        "link": "", "source": "Google Jobs",
                    })
        except Exception: pass
    return results


def fetch_board_data(force: bool = False) -> dict:
    today = str(date.today())
    if not force and BOARD_CACHE.exists():
        try:
            cache = json.loads(BOARD_CACHE.read_text())
            if cache.get("date") == today: return cache
        except Exception: pass

    print("  Fetching job board data...", end="", flush=True)
    all_jobs: list[dict] = []
    for src in BOARD_SOURCES:
        try:
            r = requests.get(src["url"], timeout=12)
            if r.status_code == 200:
                all_jobs.extend(_parse_md_table(r.text, src["name"], limit=150))
                print(".", end="", flush=True)
        except Exception: pass

    serp = _fetch_serpapi_jobs([
        "data scientist new grad 2026 NYC",
        "quantitative analyst new grad 2026",
        "ML engineer entry level 2026",
        "Amazon new grad data scientist 2026",
        "Google new grad machine learning engineer 2026",
        "Meta new grad applied scientist 2026",
        "Microsoft new grad data scientist 2026",
        "Bloomberg quantitative new grad 2026",
        "Goldman Sachs quantitative analyst new grad 2026",
        "Two Sigma new grad data scientist 2026",
    ])
    all_jobs.extend(serp)
    if serp: print(".", end="", flush=True)
    print(" done.")

    result = {"date": today, "fetched_at": datetime.now().strftime("%H:%M"), "jobs": all_jobs}
    BOARD_CACHE.write_text(json.dumps(result, indent=2))
    return result


def display_board(force: bool = False):
    data       = fetch_board_data(force=force)
    jobs       = data.get("jobs", [])
    today      = data.get("date", "?")
    fetched_at = data.get("fetched_at", "?")
    was_cached = (data.get("date") == str(date.today())) and not force
    W = 100
    print("\n" + "═"*W)
    print(f"  📋  DAILY NEW GRAD JOB BOARD  ·  {today}  ·  {'cached '+fetched_at if was_cached else 'fresh'}  ·  {len(jobs)} listings")
    print("═"*W)
    if not jobs:
        print("  No listings fetched."); print("═"*W+"\n"); return
    by_source: dict[str, list] = {}
    for j in jobs: by_source.setdefault(j.get("source","Other"), []).append(j)
    for source, src_jobs in by_source.items():
        print(f"\n  ▸ {source}  ({len(src_jobs)} roles)")
        print(f"  {'#':<4} {'COMPANY':<24} {'ROLE':<42} {'LOCATION':<22} {'DATE':<10} LINK")
        print("  " + "─"*97)
        for idx, j in enumerate(src_jobs, 1):
            print(f"  {idx:<4} {j['company'][:23]:<24} {j['role'][:41]:<42} "
                  f"{j['location'][:21]:<22} {j.get('date','')[:9]:<10} {'→' if j.get('link') else ' '}")
    print("\n"+"═"*W)
    print("  Tip: 'score fit for <role> at <company>'  ·  'refresh board'  ·  'apps' → tracker")
    print("═"*W+"\n")


# ── Agent class ────────────────────────────────────────────────────────────────

class Agent:
    def __init__(self, name, system, tools, tool_fn_map):
        self.name, self.system, self.tools, self.tool_fn_map = name, system, tools, tool_fn_map

    def run(self, task: str, verbose: bool = True) -> str:
        messages = [{"role": "user", "content": task}]
        while True:
            resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                system=self.system,
                tools=self.tools if self.tools else anthropic.NOT_GIVEN,
                messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        if verbose: print(f"  [{self.name}→{block.name}] {json.dumps(block.input)[:90]}")
                        fn = self.tool_fn_map.get(block.name)
                        result = fn(block.input) if fn else f"Unknown tool: {block.name}"
                        tool_results.append({"type":"tool_result","tool_use_id":block.id,"content":result})
                messages.append({"role": "user", "content": tool_results})
                continue
            return next((b.text for b in resp.content if hasattr(b,"text")), "")


# ── Tool definitions ───────────────────────────────────────────────────────────

SEARCH_TOOLS = [
    {"name":"search_jobs","description":"Search job listings via Google Jobs.",
     "input_schema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}},
    {"name":"fetch_ats_jobs","description":"Fetch live ATS listings. Greenhouse: anthropic,openai,stripe,citadel,palantir,recursionpharmaceuticals,genentech. Lever: ramp,notion,scale-ai,jane-street,tempus-ex.",
     "input_schema":{"type":"object","properties":{"company_slug":{"type":"string"},"platform":{"type":"string","enum":["greenhouse","lever"]}},"required":["company_slug"]}},
]
EVAL_TOOLS = [
    {"name":"fetch_job_description","description":"Fetch full JD from ATS. Call FIRST before scoring/tailoring/cover letter.",
     "input_schema":{"type":"object","properties":{"company_slug":{"type":"string"},"role_query":{"type":"string"},"platform":{"type":"string","enum":["greenhouse","lever"]}},"required":["company_slug","role_query"]}},
    {"name":"score_job_fit","description":"Score 0-100 candidate fit.",
     "input_schema":{"type":"object","properties":{"job_description":{"type":"string"}},"required":["job_description"]}},
    {"name":"tailor_resume","description":"Produce tailored resume summary + bullets.",
     "input_schema":{"type":"object","properties":{"job_description":{"type":"string"}},"required":["job_description"]}},
    {"name":"generate_cover_letter","description":"Write 3-paragraph cover letter.",
     "input_schema":{"type":"object","properties":{"job_description":{"type":"string"},"company":{"type":"string"},"role":{"type":"string"}},"required":["job_description","company","role"]}},
]
TRACKER_TOOLS = [
    {"name":"track_application","description":"Add or update job application.",
     "input_schema":{"type":"object","properties":{"company":{"type":"string"},"role":{"type":"string"},"status":{"type":"string","enum":["applied","pending","phone_screen","interview","offer","rejected","withdrawn"]},"notes":{"type":"string"}},"required":["company","role","status"]}},
    {"name":"view_applications","description":"View tracked applications.",
     "input_schema":{"type":"object","properties":{"status_filter":{"type":"string","enum":["all","applied","pending","phone_screen","interview","offer","rejected","withdrawn"]}},"required":[]}},
]

SEARCH_FN_MAP  = {"search_jobs": lambda i: search_jobs(i["query"]),
                  "fetch_ats_jobs": lambda i: fetch_ats_jobs(i["company_slug"], i.get("platform","greenhouse"))}
EVAL_FN_MAP    = {"fetch_job_description": lambda i: fetch_job_description(i["company_slug"],i["role_query"],i.get("platform","greenhouse")),
                  "score_job_fit": lambda i: score_job_fit(i["job_description"]),
                  "tailor_resume": lambda i: tailor_resume(i["job_description"]),
                  "generate_cover_letter": lambda i: generate_cover_letter(i["job_description"],i["company"],i["role"])}
TRACKER_FN_MAP = {"track_application": lambda i: track_application(i["company"],i["role"],i["status"],i.get("notes","")),
                  "view_applications": lambda i: view_applications(i.get("status_filter","all"))}
TOOL_FN_MAP    = {**SEARCH_FN_MAP, **EVAL_FN_MAP, **TRACKER_FN_MAP}


def make_search_agent():
    return Agent("SearchAgent","You find job listings. Use search_jobs for broad queries; fetch_ats_jobs for specific companies.",SEARCH_TOOLS,SEARCH_FN_MAP)

def make_eval_agent():
    return Agent("EvalAgent","You evaluate job fit and produce application materials. ALWAYS call fetch_job_description first. Use company_slug (lowercase, no spaces). Be specific and honest.",EVAL_TOOLS,EVAL_FN_MAP)

def make_tracker_agent():
    return Agent("TrackerAgent","You manage the job application tracker accurately.",TRACKER_TOOLS,TRACKER_FN_MAP)

def make_orchestrator() -> Agent:
    sa, ea, ta = make_search_agent(), make_eval_agent(), make_tracker_agent()
    ORCH_TOOLS = [
        {"name":"search_agent","description":"Delegate: finding jobs, ATS listings.","input_schema":{"type":"object","properties":{"task":{"type":"string"}},"required":["task"]}},
        {"name":"eval_agent","description":"Delegate: scoring fit, resume tailoring, cover letters.","input_schema":{"type":"object","properties":{"task":{"type":"string"}},"required":["task"]}},
        {"name":"tracker_agent","description":"Delegate: tracking/viewing applications.","input_schema":{"type":"object","properties":{"task":{"type":"string"}},"required":["task"]}},
    ]
    return Agent("Orchestrator",
        """You are the orchestrator for a job-hunting assistant.
Candidate: 2026 new grad (Math+Econ, Hamilton College), ML/AI/GNN research, based in Princeton NJ.
Target: biotech AI, healthcare AI, fintech/quant, tech.
Agents: search_agent (jobs), eval_agent (fit/materials), tracker_agent (tracker).
Route tasks appropriately. Synthesize into clean final answers.""",
        ORCH_TOOLS,
        {"search_agent": lambda i: sa.run(i["task"]),
         "eval_agent":   lambda i: ea.run(i["task"]),
         "tracker_agent":lambda i: ta.run(i["task"])})


def run_agent(user_input: str, history: list) -> tuple[str, list]:
    return run_conversation(make_orchestrator(), user_input, history)

def run_conversation(orchestrator: Agent, user_input: str, history: list) -> tuple[str, list]:
    history.append({"role":"user","content":user_input})
    while True:
        resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
            system=orchestrator.system, tools=orchestrator.tools, messages=history)
        history.append({"role":"assistant","content":resp.content})
        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    print(f"  [Orchestrator→{block.name}] {json.dumps(block.input)[:80]}")
                    fn = orchestrator.tool_fn_map.get(block.name)
                    result = fn(block.input) if fn else f"Unknown tool: {block.name}"
                    tool_results.append({"type":"tool_result","tool_use_id":block.id,"content":result})
            history.append({"role":"user","content":tool_results})
            continue
        return next((b.text for b in resp.content if hasattr(b,"text")), ""), history

def trim_history(history: list) -> list:
    if len(history) > MEMORY_WINDOW: history = history[-MEMORY_WINDOW:]
    while history and not (isinstance(history[0].get("content"),str) and history[0].get("role")=="user"):
        history = history[1:]
    return history


BANNER = """
╔══════════════════════════════════════════════════════════════╗
║       Job Hunting Agent  v3.4  ·  Multi-Agent + Triage       ║
║  Distance & livability scoring from Princeton NJ             ║
║  Type 'help' for examples  ·  'quit' to exit                 ║
╚══════════════════════════════════════════════════════════════╝"""

HELP = """
Examples:
  > search AI engineer new grad 2026 fintech NYC
  > fetch jobs at anthropic
  > score my fit for data scientist at citadel
  > tailor my resume for ML engineer at openai
  > write cover letter for quant researcher at stripe
  > track Citadel / Quant Researcher / applied
  > apps            ← view all
  > apps rejected   ← filter by status
  > refresh board
"""

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in .env or environment.")
    print(BANNER)
    display_board()
    orchestrator = make_orchestrator()
    history: list = []
    while True:
        try: user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt): print("\nBye."); break
        if not user_input: continue
        cmd = user_input.lower()
        if cmd in ("quit","exit","q"): print("Bye."); break
        if cmd == "help": print(HELP); continue
        if cmd in ("apps","applications"): print(view_applications("all")); continue
        if cmd.startswith("apps "): print(view_applications(cmd.split(" ",1)[1].strip())); continue
        if cmd in ("refresh board","refresh"): display_board(force=True); continue
        history = trim_history(history)
        try:
            answer, history = run_conversation(orchestrator, user_input, history)
            print(f"\n{answer}\n")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()