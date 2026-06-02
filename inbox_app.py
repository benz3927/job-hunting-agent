"""
Job Hunting Inbox  v2.1  —  Flask Approval UI  (light theme)
──────────────────────────────────────────────
Visual refresh from v2.0:
  - Light, calm productivity-tool look (off-white bg, white cards, soft shadows)
  - Muted accent colors + pale tinted badges instead of neon-on-black
  - Email digest restyled to match (white card, light table)
  - NO logic changes: all routes, filtering, tiering, scheduler identical to v2.0

Original v2.0 changes (unchanged here):
  - tiering layer (tiers.py): every job gets a tier (A/B/C) + tier_score
  - tabs: Daily Watch · Top 25 · Everything
  - default tab "tight"; _within_days parses "Mar 19"/"May 29"; score on fetch+render

Run:  python inbox_app.py
UI:   http://localhost:5050
"""

import os, json, re, uuid, webbrowser, smtplib, threading
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template_string, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

from job_agent import (
    fetch_board_data, fetch_ats_jobs, fetch_job_description,
    score_job_fit, tailor_resume, generate_cover_letter,
    track_application, quick_score_batch,
    distance_from_princeton, city_livability,
    distance_label, livability_label,
)

# NEW: tiering / scoring layer
from tiers import tier_jobs, score_and_tier

try:
    from auto_submit import auto_submit_with_context as auto_submit, _detect_platform
    AUTO_SUBMIT_AVAILABLE = True
except ImportError:
    AUTO_SUBMIT_AVAILABLE = False

INBOX_PATH   = Path("inbox.json")
EMAIL_FROM   = os.environ.get("EMAIL_FROM", "")
EMAIL_TO     = os.environ.get("EMAIL_TO", "")
EMAIL_PASS   = os.environ.get("EMAIL_PASSWORD", "")
PORT         = 5050
TIGHT_LIMIT  = 25
TRIAGE_ORDER = {"Strong": 0, "Maybe": 1, "": 2, "Skip": 3}

app = Flask(__name__)
_batch_state = {"running":False,"total":0,"done":0,"current":"","errors":[],"completed":[]}
_batch_lock  = threading.Lock()

ATS_WATCHLIST = [
    # tech / AI
    {"slug":"anthropic",              "platform":"greenhouse"},
    {"slug":"openai",                 "platform":"greenhouse"},
    {"slug":"palantir",               "platform":"greenhouse"},
    {"slug":"recursionpharmaceuticals","platform":"greenhouse"},
    {"slug":"genentech",              "platform":"greenhouse"},
    {"slug":"stripe",                 "platform":"greenhouse"},
    {"slug":"ramp",                   "platform":"lever"},
    {"slug":"scale-ai",               "platform":"lever"},
    {"slug":"jane-street",            "platform":"lever"},
    {"slug":"notion",                 "platform":"lever"},
    {"slug":"tempus-ex",              "platform":"lever"},
    # quant / finance — known for strong new-grad programs
    {"slug":"citadel",                "platform":"greenhouse"},
    {"slug":"twosigma",               "platform":"greenhouse"},
    {"slug":"deshaw",                 "platform":"greenhouse"},
    # companies with well-known rotational / development programs
    {"slug":"blackrock",              "platform":"greenhouse"},
    {"slug":"capitalonetech",         "platform":"greenhouse"},  # TDP
    {"slug":"microsoft",              "platform":"greenhouse"},  # EXPLORE, MSFP
    {"slug":"amazon",                 "platform":"greenhouse"},  # BDSP, rotational
    {"slug":"jpmorgan",               "platform":"greenhouse"},  # tech analyst program
    {"slug":"goldmansachs",           "platform":"greenhouse"},  # new analyst
    {"slug":"mckinsey",               "platform":"greenhouse"},
    {"slug":"bcg",                    "platform":"greenhouse"},
]

ROLE_KEYWORDS = {
    # core data / ML
    "data scientist", "data science", "data analyst", "data analysis",
    "data engineer", "data engineering", "analytics engineer",
    "machine learning", "ml engineer", "ml researcher", "deep learning", "reinforcement learning",
    "ai engineer", "ai researcher", "ai scientist", "artificial intelligence",
    "applied scientist", "applied ai", "applied ml", "research scientist", "research engineer",
    "nlp", "natural language", "llm", "language model",
    # quant / finance
    "quantitative", "quant researcher", "quant analyst", "quant developer", "quant trader",
    "algorithmic", "algo trader", "risk analyst", "financial analyst", "finance analyst",
    "investment analyst", "portfolio analyst", "strategy analyst", "trading",
    # biotech / life sciences
    "bioinformatics", "computational biology", "genomics", "proteomics", "drug discovery",
    "molecular", "biostatistician", "clinical data", "life sciences analyst", "research analyst",
    # software / platform
    "software engineer", "software developer", "backend engineer", "full stack", "platform engineer",
    # stats / BI
    "statistician", "statistical analyst", "business analyst", "business intelligence",
    "bi analyst", "bi engineer", "product analyst", "growth analyst", "operations analyst",
    # generic entry signals
    "new grad", "entry level", "junior", "associate engineer", "associate scientist",
    "associate analyst", "early career",
    # ── development / rotational programs ─────────────────────────────────────
    "rotational program", "development program", "associate program",
    "technology development program", "leadership development program",
    "analyst development program", "technology analyst program",
    "software development program", "technology associate",
    "early career program", "new grad program", "early careers",
    "associate developer", "rotational analyst", "technology analyst",
    "technology leadership", "technology development", "leadership development",
    "analyst program", "associate program",
}

# Titles containing any of these are always treated as entry-level,
# even if a senior/staff/lead word also appears elsewhere in the string.
PROGRAM_SIGNALS = {
    "development program", "rotational program", "analyst program",
    "associate program", "early career program", "technology analyst program",
    "technology development program", "leadership development program",
    "analyst development program", "software development program",
}

# Broad matcher for the dedicated "Programs" tab. Surfaces structured
# development / rotational / early-career programs across ALL company tiers
# (not just Tier B), since most of these sit at Tier C companies.
PROGRAM_TAB_SIGNALS = (
    "development program", "rotational program", "rotational analyst",
    "rotation program", "rotational", "technical development",
    "technology development", "engineering development", "accelerated development",
    "leadership development", "management development", "analyst development",
    "analyst program", "associate program", "graduate program",
    "new grad program", "early career", "early careers", "emerging talent",
)

def is_program_role(role: str) -> bool:
    r = (role or "").lower()
    return any(s in r for s in PROGRAM_TAB_SIGNALS)

PHD_SIGNALS = {
    " phd", "ph.d", "phd intern", "phd student", "doctoral", "postdoc",
    "post-doc", "post doc", "- phd", "(phd)", "/ phd",
    "ms intern", "- ms ", "(ms)", "ms student", "m.s. intern",
    "master's student", "masters student", "msc intern", "m.eng intern",
    "graduate student", "bs/ms", "bs /ms",
}

SENIOR_SIGNALS = {
    "senior","sr."," sr ","staff ","principal"," manager","director","head of",
    " vp ","vice president"," lead ","founding engineer","president","executive",
    "partner","managing director","chief ",
}
ENTRY_SIGNALS = {
    "new grad","new-grad","entry level","entry-level","junior",
    "early career","associate","intern","0-2 years","0-1 year",
    # programs
    "rotational program","development program","analyst program",
    "associate program","technology analyst","technology associate",
    "early careers",
}
GOOD_LOCATIONS = {
    "united states","u.s.","usa","remote","north america",
    "new york","nyc","ny,"," ny ","manhattan","san francisco","sf,","bay area",
    "seattle","boston","chicago","austin","denver","los angeles","washington dc","dc,",
    "cambridge","philadelphia","atlanta","miami","pittsburgh","raleigh","durham",
    "canada","toronto","vancouver","montreal","ontario",
    "london","united kingdom"," uk,","england",
    "switzerland","zurich","zürich","geneva","germany","munich","münchen","berlin",
    "ireland","dublin","france","paris","netherlands","amsterdam","sweden","stockholm",
    "australia","sydney","melbourne",
}
BAD_LOCATIONS = {
    "india","bengaluru","bangalore","hyderabad","pune","mumbai","chennai","delhi","noida",
    "singapore","mexico","mexico city","brazil","são paulo","sao paulo",
    "philippines","manila","indonesia","jakarta","malaysia","kuala lumpur","vietnam",
    "poland","warsaw","romania","bucharest","luxembourg",
}

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
]

STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
    "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
    "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri",
    "MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey",
    "NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio",
    "OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina",
    "SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont",
    "VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
    "DC":"Washington DC",
}


def _strip_html(text):
    if not text: return ""
    return re.sub(r"\s+"," ",re.sub(r"<[^>]+>","",text)).strip()

def _is_relevant_role(title): return any(kw in title.lower() for kw in ROLE_KEYWORDS)

def _is_entry_level(title):
    t = title.lower()
    # Programs always pass regardless of any other signals
    if any(s in t for s in PROGRAM_SIGNALS): return True
    if any(s in t for s in ENTRY_SIGNALS): return True
    if any(s in t for s in SENIOR_SIGNALS): return False
    return True

def _is_good_location(loc):
    if not loc or loc.strip() in ("?","N/A","LOCATION","na","n/a",""): return True
    l = loc.lower()
    if any(b in l for b in BAD_LOCATIONS): return False
    if any(g in l for g in GOOD_LOCATIONS): return True
    if re.search(r'\b[A-Z]{2}\b', loc): return True
    return True

def _is_phd_role(title: str) -> bool:
    t = title.lower()
    return any(sig in t for sig in PHD_SIGNALS)

def _should_include(title, location):
    return _is_relevant_role(title) and _is_entry_level(title) and _is_good_location(location) and not _is_phd_role(title)


# ── Filtering helpers ─────────────────────────────────────────────────────────

def _is_remote(job):
    loc = job.get("location","").lower()
    return any(w in loc for w in ("remote","anywhere","distributed","wfh","work from home"))

def _is_princeton_area(job):
    miles = job.get("distance_miles", -1)
    if miles == 0: return True
    if miles < 0:  return False
    return miles <= 50

STATE_CITIES: dict[str, list[str]] = {
    "NY": ["new york", "nyc", "manhattan", "brooklyn", "queens", "bronx", "albany", "buffalo"],
    "NJ": ["new jersey", "princeton", "hoboken", "jersey city", "newark", "trenton", "new brunswick"],
    "PA": ["philadelphia", "philly", "pittsburgh", "harrisburg"],
    "CA": ["san francisco", "los angeles", "san jose", "san diego", "bay area", "silicon valley",
           "palo alto", "mountain view", "sunnyvale", "santa clara", "berkeley", "oakland", "irvine"],
    "WA": ["seattle", "redmond", "bellevue", "kirkland"],
    "MA": ["boston", "cambridge", "somerville"],
    "IL": ["chicago"],
    "TX": ["austin", "dallas", "houston", "san antonio"],
    "CO": ["denver", "boulder"],
    "GA": ["atlanta"],
    "FL": ["miami", "orlando", "tampa"],
    "NC": ["raleigh", "durham", "charlotte"],
    "VA": ["arlington", "mclean", "reston", "tysons"],
    "MD": ["baltimore", "bethesda", "rockville"],
    "DC": ["washington dc", "washington, dc", "district of columbia"],
    "OR": ["portland"],
    "MN": ["minneapolis", "saint paul"],
    "OH": ["columbus", "cleveland", "cincinnati"],
    "MI": ["detroit", "ann arbor"],
    "MO": ["st. louis", "kansas city"],
    "TN": ["nashville", "memphis"],
    "UT": ["salt lake city"],
    "AZ": ["phoenix", "scottsdale", "tempe"],
    "NV": ["las vegas", "reno"],
    "WI": ["milwaukee", "madison"],
    "IN": ["indianapolis"],
    "CT": ["hartford", "stamford", "new haven"],
}

def _location_has_any_state(job, states: list[str]) -> bool:
    if not states: return True
    loc = job.get("location","")
    loc_lower = loc.lower()
    for state in states:
        if re.search(rf'[\s,(\[]{re.escape(state)}[\s,)\]]', " " + loc + " "):
            return True
        full = STATE_NAMES.get(state,"")
        if full and full.lower() in loc_lower:
            return True
        for city in STATE_CITIES.get(state, []):
            if city in loc_lower:
                return True
    return False

# ── Months for the "Mar 19" / "May 29" date format ────────────────────────────
_MONTHS = {"jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"}

def _within_days(job, days: int) -> bool:
    date_str = job.get("date_posted","") or job.get("date_added","")
    if not date_str or date_str.strip() in ("?","N/A",""):
        # Undated jobs (mostly speedyapply "?") — keep them. Flip to False to hide.
        return True

    ds = date_str.lower().strip()
    if any(w in ds for w in ("today","hour","just","minute")):
        return True
    if "day" in ds:
        m = re.search(r"\d+", ds)
        return (int(m.group()) if m else 1) <= days
    if "week" in ds:
        m = re.search(r"\d+", ds)
        return (int(m.group()) if m else 1) * 7 <= days
    if "month" in ds:
        return False

    # ISO format first: 2026-03-19
    try:
        return (date.today() - datetime.strptime(date_str[:10], "%Y-%m-%d").date()).days <= days
    except (ValueError, TypeError):
        pass

    # "Mar 19" / "May 29" — assume current year; if that lands in the future,
    # it must be last year (e.g. checking "Dec 30" in early Jan).
    if ds[:3] in _MONTHS:
        try:
            parsed = datetime.strptime(f"{date_str.strip()} {date.today().year}", "%b %d %Y").date()
            if parsed > date.today():
                parsed = parsed.replace(year=parsed.year - 1)
            return (date.today() - parsed).days <= days
        except ValueError:
            pass

    # Unparseable — keep it rather than silently dropping.
    return True

def apply_filters(jobs, days, loc_filter, states: list[str]):
    if days == "2":
        jobs = [j for j in jobs if _within_days(j, 2)]
    elif days == "7":
        jobs = [j for j in jobs if _within_days(j, 7)]
    if loc_filter == "remote":
        jobs = [j for j in jobs if _is_remote(j)]
    elif loc_filter == "princeton":
        jobs = [j for j in jobs if _is_princeton_area(j)]
    elif loc_filter == "states" and states:
        jobs = [j for j in jobs if _location_has_any_state(j, states)]
    return jobs


# ── Inbox storage ─────────────────────────────────────────────────────────────

def load_inbox():
    if not INBOX_PATH.exists(): return []
    try: return json.loads(INBOX_PATH.read_text())
    except: return []

def save_inbox(jobs): INBOX_PATH.write_text(json.dumps(jobs, indent=2))

def inbox_stats(jobs):
    counts = {"new":0,"approved":0,"skipped":0,"pending":0,"strong":0,"maybe":0,
              "daily":0,"tight":0,"rest":0,"programs":0}
    new_jobs = [j for j in jobs if j.get("status") == "new"]
    for j in jobs:
        s = j.get("status","new")
        counts[s] = counts.get(s,0) + 1
        if s == "new":
            t = j.get("triage","")
            if t == "Strong": counts["strong"] += 1
            elif t == "Maybe": counts["maybe"] += 1
    # tier counts (only over "new")
    view = tier_jobs(new_jobs, tight_limit=TIGHT_LIMIT)
    counts["daily"] = len(view["daily"])
    counts["tight"] = len(view["tight"])
    counts["rest"]  = len(view["rest"])
    counts["programs"] = sum(1 for j in new_jobs if is_program_role(j.get("role","")))
    return counts

def _exists(inbox, company, role):
    c,r = company.lower().strip(), role.lower().strip()
    return any(j.get("company","").lower().strip()==c and j.get("role","").lower().strip()==r for j in inbox)

def _make_job(company, role, location, link, source):
    miles = distance_from_princeton(location)
    liv   = city_livability(location)
    job = {
        "id":               str(uuid.uuid4())[:8],
        "company":          _strip_html(company)[:50],
        "role":             _strip_html(role)[:80],
        "location":         _strip_html(location)[:40],
        "link":             link,
        "source":           source,
        "date_added":       str(date.today()),
        "date_posted":      "",
        "status":           "new",
        "triage":           "",
        "distance_miles":   miles,
        "distance_label":   distance_label(miles) if miles >= 0 else "",
        "livability_score": liv,
        "livability_label": livability_label(liv) if liv >= 0 else "",
        "cover_letter":     "",
        "resume_bullets":   "",
        "fit_score":        "",
        "auto_submitted":   False,
        "tier":             "",
        "tier_score":       0,
    }
    score_and_tier(job)   # NEW: annotate tier + tier_score on creation
    return job

# ── Job fetching ──────────────────────────────────────────────────────────────

def fetch_all_new_jobs(clear_html_junk=False):
    inbox = load_inbox()
    if clear_html_junk:
        before = len(inbox)
        inbox  = [j for j in inbox if "<" not in j.get("company","") and "<" not in j.get("role","")]
        if before - len(inbox): print(f"[Inbox] Cleaned {before-len(inbox)} HTML-junk entries")

    added = 0; filtered_out = 0; new_entries = []

    try:
        for j in fetch_board_data(force=True).get("jobs",[]):
            co  = _strip_html(j.get("company",""))
            ro  = _strip_html(j.get("role",""))
            loc = _strip_html(j.get("location","?"))
            if not co or not ro: continue
            if not _should_include(ro, loc): filtered_out += 1; continue
            if _exists(inbox, co, ro): continue
            entry = _make_job(co, ro, loc, j.get("link",""), j.get("source","Board"))
            entry["date_posted"] = j.get("date","")
            score_and_tier(entry)   # re-score now that date_posted is set
            new_entries.append(entry)
            added += 1
    except Exception as e:
        print(f"[Inbox] Board fetch error: {e}")

    for ats in ATS_WATCHLIST:
        slug, platform = ats["slug"], ats["platform"]
        try:
            result  = fetch_ats_jobs(slug, platform)
            company = slug.replace("-"," ").title()
            lines   = result.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("- ") and " | " in line:
                    parts      = line[2:].split(" | ",1)
                    role_title = _strip_html(parts[0].strip())
                    location   = _strip_html(parts[1].strip()) if len(parts)>1 else "?"
                    link = ""
                    if i+1 < len(lines):
                        nxt = lines[i+1].strip()
                        if nxt.startswith("http"): link=nxt; i+=1
                    if not _should_include(role_title, location): filtered_out+=1; i+=1; continue
                    if not _exists(inbox, company, role_title):
                        new_entries.append(_make_job(company, role_title, location, link, f"ATS/{platform}"))
                        added += 1
                i += 1
        except Exception as e:
            print(f"[Inbox] ATS fetch error ({slug}): {e}")

    if new_entries:
        quick_score_batch(new_entries, max_workers=10)
        for e in new_entries:
            score_and_tier(e)   # triage may have changed tier_score nudge
        inbox.extend(new_entries)

    save_inbox(inbox)
    strong = sum(1 for e in new_entries if e.get("triage")=="Strong")
    print(f"[Inbox] Done — {added} added ({strong} Strong), {filtered_out} filtered out")
    return added

# ── Approval / materials ──────────────────────────────────────────────────────

def _guess_slug(company):
    return company.lower().replace(" ","").replace("-","").replace(".","")

def generate_materials(job):
    slug = _guess_slug(job["company"])
    jd = None
    for platform in ("greenhouse","lever"):
        candidate = fetch_job_description(slug, job["role"], platform)
        if candidate and not any(x in candidate.lower() for x in
                ("not found","failed","no close match","no open")):
            jd = candidate; break
    if not jd:
        jd = f"ROLE: {job['role']}\nCOMPANY: {job['company']}\nLOCATION: {job.get('location','?')}\n(Full JD not available)"
    cl  = generate_cover_letter(jd, job["company"], job["role"])
    rb  = tailor_resume(jd)
    raw = score_job_fit(jd)
    score = ""
    for line in raw.splitlines():
        if "FIT SCORE" in line.upper(): score = line.split(":",1)[-1].strip(); break
    return cl, rb, score


def _do_approve(job_id):
    inbox = load_inbox()
    job   = next((j for j in inbox if j["id"]==job_id), None)
    if not job: return False, False
    try:
        cover_letter, resume_bullets, fit_score = generate_materials(job)
    except Exception:
        return False, False

    link = job.get("link","")
    auto_submitted = False
    if link and AUTO_SUBMIT_AVAILABLE:
        platform = _detect_platform(link)
        if platform in ("greenhouse","lever"):
            result = auto_submit(link, cover_letter, job['company'], job['role'], headless=False)
            auto_submitted = result.get("ok", False)

    job["status"]         = "approved" if auto_submitted else "pending"
    job["cover_letter"]   = cover_letter
    job["resume_bullets"] = resume_bullets
    job["fit_score"]      = fit_score
    job["auto_submitted"] = auto_submitted
    save_inbox(inbox)

    try:
        track_application(job["company"], job["role"],
                          "applied" if auto_submitted else "pending",
                          f"Inbox {date.today()} · score {fit_score}" +
                          (" · auto-submitted" if auto_submitted else " · needs manual submit"))
    except Exception: pass

    if link and not auto_submitted:
        try: webbrowser.open(link)
        except Exception: pass

    return True, auto_submitted


def _run_batch(job_ids):
    with _batch_lock:
        _batch_state.update({"running":True,"total":len(job_ids),"done":0,
                              "current":"","errors":[],"completed":[]})
    inbox     = load_inbox()
    id_to_job = {j["id"]:j for j in inbox}
    for job_id in job_ids:
        job   = id_to_job.get(job_id)
        label = f"{job['company']} — {job['role'][:40]}" if job else job_id
        with _batch_lock: _batch_state["current"] = label
        success, _ = _do_approve(job_id)
        with _batch_lock:
            _batch_state["done"] += 1
            if success: _batch_state["completed"].append(job_id)
            else:       _batch_state["errors"].append(label)
    with _batch_lock:
        _batch_state["running"] = False
        _batch_state["current"] = ""

# ── Email digests ─────────────────────────────────────────────────────────────

def send_top10_digest(label="Morning"):
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASS]):
        return "Email not configured."
    inbox = load_inbox()

    # digest leads with Tier A (daily watch), then top Tier B by score
    new_jobs = [j for j in inbox if j.get("status") == "new" and j.get("triage") != "Skip"]
    view = tier_jobs(new_jobs, tight_limit=TIGHT_LIMIT)
    top10 = (view["daily"] + view["tight"])[:10]

    if not top10:
        return "No new jobs to send."

    rows = []
    for i, j in enumerate(top10, 1):
        tier = j.get("tier", "")
        if tier == "A":
            badge = '<span style="background:#f3e8ff;color:#7c3aed;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700">🔥 Daily</span>'
        elif tier == "B":
            badge = '<span style="background:#dcfce7;color:#15803d;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700">⭐ Top</span>'
        else:
            badge = ""
        score = j.get("tier_score", "")
        score_html = f'<span style="background:#dbeafe;color:#1d4ed8;padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:700">🎯 {score}</span>' if score else ""
        link = j.get("link", "")
        link_html = f'<a href="{link}" style="color:#2563eb;font-size:.8rem;font-weight:700">Apply →</a>' if link else ""
        date_str = j.get("date_posted", "") or j.get("date_added", "")
        rows.append(f"""
        <tr style="border-bottom:1px solid #e4e7ec">
          <td style="padding:10px 8px;color:#6b7280;font-size:.8rem;text-align:center">{i}</td>
          <td style="padding:10px 12px">
            <div style="font-size:.7rem;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">{j['company']}</div>
            <div style="font-weight:700;font-size:.9rem;margin-top:2px;color:#1f2733">{j['role']}</div>
            <div style="font-size:.74rem;color:#6b7280;margin-top:3px">📍 {j.get('location','?')} &nbsp;·&nbsp; 📅 {date_str}</div>
          </td>
          <td style="padding:10px 8px;text-align:center">{badge}</td>
          <td style="padding:10px 8px;text-align:center">{score_html}</td>
          <td style="padding:10px 8px;text-align:center">{link_html}</td>
        </tr>""")

    pending_count = sum(1 for j in inbox if j.get("status") == "pending")
    app_link = f"http://localhost:{PORT}"

    html_body = f"""<html>
    <body style="background:#f6f7f9;color:#1f2733;font-family:system-ui,sans-serif;padding:24px;max-width:820px;margin:0 auto">
      <h2 style="margin-bottom:4px;color:#1f2733">📋 {label} Job Digest — {date.today()}</h2>
      <p style="color:#6b7280;margin-bottom:4px">Top {len(top10)} — Daily Watch first, then your best matches</p>
      {"" if not pending_count else f'<p style="color:#ea580c;margin-bottom:4px">⚠️ {pending_count} application(s) still need manual submit</p>'}
      <p style="margin-bottom:20px"><a href="{app_link}" style="color:#2563eb;font-weight:700">→ Open Job Inbox</a></p>
      <table style="width:100%;border-collapse:collapse;background:#ffffff;border:1px solid #e4e7ec;border-radius:10px;overflow:hidden;font-size:.85rem;box-shadow:0 1px 3px rgba(16,24,40,.05)">
        <thead>
          <tr style="background:#f1f3f5">
            <th style="padding:10px 8px;color:#6b7280;font-size:.7rem;text-transform:uppercase;text-align:center">#</th>
            <th style="padding:10px 12px;color:#6b7280;font-size:.7rem;text-transform:uppercase;text-align:left">Role</th>
            <th style="padding:10px 8px;color:#6b7280;font-size:.7rem;text-transform:uppercase;text-align:center">Tier</th>
            <th style="padding:10px 8px;color:#6b7280;font-size:.7rem;text-transform:uppercase;text-align:center">Score</th>
            <th style="padding:10px 8px;color:#6b7280;font-size:.7rem;text-transform:uppercase;text-align:center">Link</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📋 {label} Jobs — Top {len(top10)} · {date.today()}"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASS)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        return f"✅ Sent {label} digest to {EMAIL_TO} ({len(top10)} jobs)"
    except Exception as e:
        return f"Email failed: {e}"


def send_email_digest():
    """Legacy full digest — kept for the /digest endpoint button."""
    return send_top10_digest("Manual")

# ── HTML template ─────────────────────────────────────────────────────────────

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Inbox</title>
<style>
:root{--bg:#f6f7f9;--card:#ffffff;--border:#e4e7ec;--green:#16a34a;--red:#dc2626;
  --blue:#2563eb;--yellow:#d97706;--purple:#7c3aed;--orange:#ea580c;
  --text:#1f2733;--muted:#6b7280;--r:10px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;min-height:100vh}

.hdr{background:var(--card);border-bottom:1px solid var(--border);padding:12px 24px;
  display:flex;align-items:center;gap:12px;flex-wrap:wrap;position:sticky;top:0;z-index:100;
  box-shadow:0 1px 3px rgba(16,24,40,.04)}
.hdr h1{font-size:1.1rem;font-weight:800;white-space:nowrap}
.stat{background:#f1f3f5;border:1px solid var(--border);border-radius:6px;
  padding:4px 10px;font-size:.78rem;white-space:nowrap;color:var(--text)}
.stat b{font-size:.9rem}
.hdr-actions{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}

.filter-bar{background:#fbfcfd;border-bottom:1px solid var(--border);padding:10px 24px;
  display:flex;flex-direction:column;gap:10px}
.filter-row{display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap}
.filter-label{font-size:.72rem;color:var(--muted);white-space:nowrap;font-weight:700;
  text-transform:uppercase;letter-spacing:.05em;padding-top:5px;min-width:70px}
.pill-group{display:flex;flex-wrap:wrap;gap:5px}
.pill{padding:4px 11px;border-radius:20px;border:1px solid var(--border);
  background:#fff;color:var(--muted);font-size:.76rem;cursor:pointer;
  transition:all .15s;white-space:nowrap;user-select:none}
.pill:hover{border-color:#c4cad3;color:var(--text)}
.pill.on{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:700}
.pill.on-green{background:var(--green);border-color:var(--green);color:#fff;font-weight:700}
.pill.on-orange{background:var(--orange);border-color:var(--orange);color:#fff;font-weight:700}
.state-pill{padding:3px 8px;border-radius:12px;border:1px solid var(--border);
  background:#fff;color:var(--muted);font-size:.7rem;cursor:pointer;
  transition:all .15s;white-space:nowrap;user-select:none}
.state-pill:hover{border-color:#c4cad3;color:var(--text)}
.state-pill.on{background:var(--purple);border-color:var(--purple);color:#fff;font-weight:700}
.state-clear{font-size:.7rem;color:var(--blue);background:none;border:none;
  cursor:pointer;padding:3px 6px;text-decoration:underline}

.bulk-bar{background:#eef2ff;border-bottom:1px solid var(--border);padding:9px 24px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-height:44px}
.bulk-bar.hidden{display:none}
.sel-count{font-size:.82rem;color:var(--muted)}.sel-count b{color:var(--text)}
.progress-wrap{background:var(--card);border-bottom:1px solid var(--border);padding:10px 24px;display:none}
.progress-wrap.show{display:block}
.progress-label{font-size:.78rem;color:var(--muted);margin-bottom:5px}
.progress-label b{color:var(--text)}
.progress-track{background:#e4e7ec;border-radius:99px;height:7px;overflow:hidden}
.progress-fill{background:var(--green);height:100%;border-radius:99px;transition:width .3s;width:0%}

.btn{padding:6px 13px;border-radius:7px;border:none;cursor:pointer;font-size:.78rem;
  font-weight:700;transition:opacity .15s,transform .1s;line-height:1}
.btn:hover{opacity:.88}.btn:active{transform:scale(.97)}
.btn-green{background:var(--green);color:#fff}
.btn-gray{background:#eef0f3;color:var(--text);border:1px solid var(--border)}
.btn-blue{background:var(--blue);color:#fff}.btn-yellow{background:var(--yellow);color:#fff}
.btn-purple{background:var(--purple);color:#fff}.btn-orange{background:var(--orange);color:#fff}
.btn-sm{padding:4px 9px;font-size:.74rem}
.btn:disabled{opacity:.45;cursor:not-allowed;transform:none}

.tabs{display:flex;gap:2px;padding:12px 24px 0;border-bottom:1px solid var(--border);flex-wrap:wrap;background:var(--card)}
.tab{padding:7px 14px;border-radius:8px 8px 0 0;cursor:pointer;font-size:.8rem;
  color:var(--muted);border:1px solid transparent;border-bottom:none;background:transparent}
.tab:hover{color:var(--text)}
.tab.active{background:var(--bg);color:var(--text);font-weight:700;
  border-color:var(--border);border-bottom-color:var(--bg);margin-bottom:-1px}
.tab-sep{width:1px;background:var(--border);margin:4px 6px 0}

.main{padding:18px 24px 40px}
.result-info{font-size:.78rem;color:var(--muted);margin-bottom:12px}
.result-info b{color:var(--text)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(370px,1fr));gap:12px}
.empty{grid-column:1/-1;text-align:center;padding:60px;color:var(--muted);font-size:1rem}

.card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:14px;display:flex;flex-direction:column;gap:9px;
  box-shadow:0 1px 2px rgba(16,24,40,.03);transition:border-color .2s,box-shadow .2s,opacity .2s}
.card:hover{border-color:#cbd2d9;box-shadow:0 2px 8px rgba(16,24,40,.06)}
.card.approved{border-left:3px solid var(--green)}.card.pending{border-left:3px solid var(--orange)}
.card.skipped{opacity:.55}.card.selected{border-color:var(--purple);background:#faf8ff}
.card.loading{opacity:.6;pointer-events:none}.card.done-anim{border-left:3px solid var(--green)}
.card.tier-a{border-left:3px solid var(--purple)}
.card.tier-b{border-left:3px solid var(--green)}
.card.triage-strong{border-left:3px solid var(--green)}
.card.triage-maybe{border-left:3px solid var(--yellow)}
.card.triage-skip{opacity:.62}
.card-check{display:flex;align-items:center;gap:8px}
.card-check input[type=checkbox]{width:15px;height:15px;cursor:pointer;accent-color:var(--purple)}
.card-check label{font-size:.73rem;color:var(--muted);cursor:pointer;user-select:none}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.co-name{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.role-name{font-size:.95rem;font-weight:700;margin-top:2px;line-height:1.3;color:var(--text)}
.badges{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0}
.badge{padding:2px 7px;border-radius:4px;font-size:.68rem;font-weight:700;white-space:nowrap}
.b-ats{background:#dbeafe;color:#1d4ed8}.b-board{background:#dcfce7;color:#15803d}
.b-google{background:#fef3c7;color:#b45309}
.t-daily{background:#f3e8ff;color:#7c3aed;border-radius:4px;padding:2px 7px;font-size:.68rem;font-weight:700}
.t-top{background:#dcfce7;color:#15803d;border-radius:4px;padding:2px 7px;font-size:.68rem;font-weight:700}
.t-strong{background:#dcfce7;color:#15803d;border-radius:4px;padding:2px 7px;font-size:.68rem;font-weight:700}
.t-maybe{background:#fef3c7;color:#b45309;border-radius:4px;padding:2px 7px;font-size:.68rem;font-weight:700}
.t-skip{background:#fee2e2;color:#b91c1c;border-radius:4px;padding:2px 7px;font-size:.68rem;font-weight:700}
.meta{font-size:.75rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.score-pill{background:#dbeafe;color:#1d4ed8;border-radius:4px;padding:1px 6px;font-weight:700}
.tier-pill{background:#ede9fe;color:#6d28d9;border-radius:4px;padding:1px 6px;font-weight:700;font-size:.68rem}
.dist-pill{background:#eef2ff;color:#4338ca;border-radius:4px;padding:1px 6px;font-size:.68rem}
.liv-pill{border-radius:4px;padding:1px 6px;font-size:.68rem;font-weight:600}
.card-actions{display:flex;gap:5px;flex-wrap:wrap}
.mat{display:none;border-top:1px solid var(--border);padding-top:10px;margin-top:1px;flex-direction:column;gap:9px}
.mat.open{display:flex}
.mat h4{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
.mat pre{font-size:.76rem;white-space:pre-wrap;line-height:1.5;background:#f6f7f9;
  border-radius:6px;padding:9px;max-height:200px;overflow-y:auto;border:1px solid var(--border);color:var(--text)}
.copy-btn{font-size:.68rem;float:right;cursor:pointer;color:var(--blue);background:none;border:none}
.copy-btn:hover{text-decoration:underline}
.toast{position:fixed;bottom:18px;right:18px;padding:9px 16px;border-radius:8px;
  font-weight:700;font-size:.82rem;display:none;z-index:999;box-shadow:0 4px 16px rgba(16,24,40,.18)}
.spin{display:inline-block;width:11px;height:11px;border:2px solid rgba(255,255,255,.4);
  border-top-color:#fff;border-radius:50%;animation:sp .5s linear infinite;vertical-align:middle}
@keyframes sp{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div class="hdr">
  <h1>📋 Job Inbox</h1>
  <div class="stat" style="color:#7c3aed;border-color:#ddd6fe">🔥 Daily <b>{{ stats.daily }}</b></div>
  <div class="stat" style="color:#15803d;border-color:#bbf7d0">⭐ Top {{ tight_limit }} <b>{{ stats.tight }}</b></div>
  <div class="stat">📂 Rest <b>{{ stats.rest }}</b></div>
  <div class="stat" style="color:#ea580c;border-color:#fed7aa">📬 To Submit <b>{{ stats.pending }}</b></div>
  <div class="stat">✅ Applied <b>{{ stats.approved }}</b></div>
  {% if auto_submit_on %}<div class="stat" style="color:#15803d;border-color:#bbf7d0">⚡ Auto-submit ON</div>{% endif %}
  <div class="hdr-actions">
    <button class="btn btn-blue" onclick="fetchJobs(this)">🔄 Fetch</button>
    <button class="btn btn-yellow" onclick="sendDigest(this)">📧 Digest</button>
  </div>
</div>

<div class="filter-bar">
  <div class="filter-row">
    <span class="filter-label">📅 Posted</span>
    <div class="pill-group">
      <span class="pill {% if days=='all' %}on{% endif %}" onclick="setDays('all')">All time</span>
      <span class="pill {% if days=='7' %}on{% endif %}"   onclick="setDays('7')">Past 7 days</span>
      <span class="pill {% if days=='2' %}on{% endif %}"   onclick="setDays('2')">Past 2 days</span>
    </div>
  </div>
  <div class="filter-row">
    <span class="filter-label">📍 Location</span>
    <div class="pill-group">
      <span class="pill {% if loc_filter=='all' %}on{% endif %}"       onclick="setLoc('all')">All</span>
      <span class="pill {% if loc_filter=='remote' %}on-green{% endif %}"
        style="{% if loc_filter=='remote' %}background:var(--green);border-color:var(--green);color:#fff;font-weight:700{% endif %}"
        onclick="setLoc('remote')">🏠 Remote</span>
      <span class="pill {% if loc_filter=='princeton' %}on-orange{% endif %}"
        style="{% if loc_filter=='princeton' %}background:var(--orange);border-color:var(--orange);color:#fff;font-weight:700{% endif %}"
        onclick="setLoc('princeton')">📍 Princeton &lt;50 mi</span>
    </div>
  </div>
  <div class="filter-row">
    <span class="filter-label" style="color:{% if selected_states %}var(--purple){% else %}var(--muted){% endif %}">🗺 States</span>
    <div class="pill-group" id="state-pills">
      {% for st in all_states %}
      <span class="state-pill {% if st in selected_states %}on{% endif %}"
        onclick="toggleState('{{ st }}')" title="{{ state_names[st] }}">{{ st }}</span>
      {% endfor %}
      {% if selected_states %}
      <button class="state-clear" onclick="clearStates()">✕ clear</button>
      {% endif %}
    </div>
  </div>
</div>

<div class="bulk-bar hidden" id="bulk-bar">
  <span class="sel-count">Selected: <b id="sel-count">0</b></span>
  <button class="btn btn-gray btn-sm" onclick="selectAll()">Select All</button>
  <button class="btn btn-gray btn-sm" onclick="deselectAll()">Deselect All</button>
  <button class="btn btn-purple" id="bulk-btn" onclick="bulkApply(this)">
    🚀 Apply Selected (<span id="bulk-count">0</span>)
  </button>
</div>

<div class="progress-wrap" id="progress-wrap">
  <div class="progress-label">
    Applying: <b id="progress-current">...</b> &nbsp;·&nbsp;
    <b id="progress-done">0</b> / <b id="progress-total">0</b> done
  </div>
  <div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div>
</div>

<div class="tabs">
  <div class="tab {{ 'active' if tab=='daily' }}"  onclick="setTab('daily')" style="color:#7c3aed">🔥 Daily Watch ({{ stats.daily }})</div>
  <div class="tab {{ 'active' if tab=='tight' }}"  onclick="setTab('tight')" style="color:#15803d">⭐ Top {{ tight_limit }} ({{ stats.tight }})</div>
  <div class="tab {{ 'active' if tab=='rest' }}"   onclick="setTab('rest')">📂 Everything ({{ stats.rest }})</div>
  <div class="tab {{ 'active' if tab=='programs' }}" onclick="setTab('programs')" style="color:#b45309">🎓 Programs ({{ stats.programs }})</div>
  <div class="tab-sep"></div>
  <div class="tab {{ 'active' if tab=='strong' }}" onclick="setTab('strong')">🟢 Strong ({{ stats.strong }})</div>
  <div class="tab {{ 'active' if tab=='maybe' }}"  onclick="setTab('maybe')">🟡 Maybe ({{ stats.maybe }})</div>
  <div class="tab-sep"></div>
  <div class="tab {{ 'active' if tab=='pending' }}"  onclick="setTab('pending')" style="color:#ea580c">📬 To Submit ({{ stats.pending }})</div>
  <div class="tab {{ 'active' if tab=='approved' }}" onclick="setTab('approved')">✅ Applied ({{ stats.approved }})</div>
  <div class="tab {{ 'active' if tab=='skipped' }}"  onclick="setTab('skipped')">⏭ Skipped ({{ stats.skipped }})</div>
</div>

<div class="main">
<div class="result-info">
  Showing <b>{{ jobs|length }}</b> job{{ 's' if jobs|length != 1 }}
  {% if tab == 'daily' %} · <b>🔥 always-watch targets</b>
  {% elif tab == 'tight' %} · <b>⭐ your best matches</b>
  {% elif tab == 'programs' %} · <b>🎓 development &amp; rotational programs (all tiers)</b>
  {% elif tab == 'rest' %} · <b>📂 the long tail</b>{% endif %}
  {% if days != 'all' %} · <b>past {{ days }} days</b>{% endif %}
  {% if loc_filter == 'remote' %} · <b>🏠 remote only</b>
  {% elif loc_filter == 'princeton' %} · <b>📍 Princeton area</b>
  {% endif %}
  {% if selected_states %} · <b>{{ selected_states | join(', ') }}</b>{% endif %}
</div>

<div class="grid" id="grid">
{% if jobs %}
  {% for j in jobs %}
  <div class="card {{ j.status }}
    {%- if j.status == 'new' %}
      {%- if j.tier == 'A' %} tier-a
      {%- elif j.tier == 'B' %} tier-b
      {%- elif j.triage == 'Skip' %} triage-skip
      {%- endif %}
    {%- endif %}" id="card-{{ j.id }}">

    {% if j.status == 'new' %}
    <div class="card-check">
      <input type="checkbox" id="chk-{{ j.id }}" onchange="onCheck('{{ j.id }}', this)">
      <label for="chk-{{ j.id }}">Select for bulk apply</label>
    </div>
    {% endif %}

    <div class="card-top">
      <div>
        <div class="co-name">{{ j.company }}</div>
        <a class="role-name" href="{{ j.link if j.link else 'https://www.google.com/search?q=' ~ (j.company ~ ' ' ~ j.role ~ ' job application') }}" target="_blank" style="color:inherit;text-decoration:none" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">{{ j.role }}</a>
      </div>
      <div class="badges">
        <span class="badge {% if 'ATS' in j.source %}b-ats{% elif 'Google' in j.source %}b-google{% else %}b-board{% endif %}">
          {{ j.source.split('/')[0] }}
        </span>
        {% if j.tier == 'A' %}<span class="t-daily">🔥 Daily</span>
        {% elif j.tier == 'B' %}<span class="t-top">⭐ Top</span>
        {% endif %}
        {% if j.triage == 'Strong' %}<span class="t-strong">🟢 Strong</span>
        {% elif j.triage == 'Maybe' %}<span class="t-maybe">🟡 Maybe</span>
        {% elif j.triage == 'Skip' %}<span class="t-skip">🔴 Skip</span>
        {% endif %}
      </div>
    </div>

    <div class="meta">
      <span>📍 {{ j.location }}</span>
      {% if j.distance_label %}<span class="dist-pill">✈️ {{ j.distance_label }}</span>{% endif %}
      {% if j.livability_label %}<span class="liv-pill"
        style="background:{% if j.livability_score >= 85 %}#dcfce7;color:#15803d
               {%- elif j.livability_score >= 75 %}#ecfccb;color:#4d7c0f
               {%- elif j.livability_score >= 65 %}#fef3c7;color:#b45309
               {%- else %}#fee2e2;color:#b91c1c{% endif %}">
        {{ j.livability_label }}
      </span>{% endif %}
    </div>
    <div class="meta">
      <span>📅 {{ j.date_posted if j.date_posted else j.date_added }}</span>
      {% if j.tier_score %}<span class="tier-pill">📊 {{ j.tier_score }}</span>{% endif %}
      {% if j.fit_score %}<span class="score-pill">🎯 {{ j.fit_score }}</span>{% endif %}
      {% if j.status == 'pending' %}<span style="color:#ea580c;font-weight:700;font-size:.73rem">📬 Needs submit</span>{% endif %}
      {% if j.auto_submitted %}<span style="color:#15803d;font-weight:700;font-size:.73rem">⚡ Auto-submitted</span>{% endif %}
    </div>

    <div class="card-actions">
      {% if j.status == 'new' %}
        <button class="btn btn-green btn-sm" id="approve-{{ j.id }}"
          onclick="applyNow('{{ j.id }}', this)">🚀 Apply Now</button>
        <button class="btn btn-gray btn-sm" onclick="skip('{{ j.id }}', this)">⏭ Skip</button>
      {% elif j.status == 'pending' %}
        <button class="btn btn-orange btn-sm" onclick="markApplied('{{ j.id }}', this)">✅ Mark Applied</button>
        <button class="btn btn-gray btn-sm" onclick="skip('{{ j.id }}', this)">↩ Undo</button>
      {% elif j.status == 'approved' %}
        <button class="btn btn-gray btn-sm" onclick="skip('{{ j.id }}', this)">↩ Undo</button>
      {% else %}
        <button class="btn btn-gray btn-sm" onclick="skip('{{ j.id }}', this)">↩ Restore</button>
      {% endif %}

      {% if j.cover_letter or j.resume_bullets %}
        <button class="btn btn-gray btn-sm" onclick="toggleMat('{{ j.id }}')">📄 Materials</button>
      {% endif %}
    </div>

    {% if j.cover_letter or j.resume_bullets %}
    <div class="mat" id="mat-{{ j.id }}">
      {% if j.cover_letter %}
      <div>
        <h4>Cover Letter <button class="copy-btn" onclick="copyText('cl-{{ j.id }}')">copy</button></h4>
        <pre id="cl-{{ j.id }}">{{ j.cover_letter }}</pre>
      </div>
      {% endif %}
      {% if j.resume_bullets %}
      <div>
        <h4>Resume Bullets <button class="copy-btn" onclick="copyText('rb-{{ j.id }}')">copy</button></h4>
        <pre id="rb-{{ j.id }}">{{ j.resume_bullets }}</pre>
      </div>
      {% endif %}
    </div>
    {% endif %}

  </div>
  {% endfor %}
{% else %}
  <div class="empty">No jobs match your filters.<br><br>Try adjusting the date or location filters above.</div>
{% endif %}
</div></div>

<div class="toast" id="toast"></div>
<script>
function getP(){ return new URLSearchParams(window.location.search) }
function nav(overrides){
  const p = getP()
  for(const [k,v] of Object.entries(overrides)){
    if(v===null||v===''){ p.delete(k) } else { p.set(k,v) }
  }
  location.href = '/?' + p.toString()
}
function setTab(t){ nav({tab:t}) }
function setDays(d){ nav({days:d}) }
function setLoc(l){ nav({loc:l}) }

function toggleState(st){
  const p = getP()
  const cur = (p.get('states')||'').split(',').filter(Boolean)
  const idx = cur.indexOf(st)
  if(idx >= 0){ cur.splice(idx,1) } else { cur.push(st) }
  if(cur.length > 0){
    nav({states: cur.join(','), loc:'states'})
  } else {
    nav({states:null, loc:'all'})
  }
}
function clearStates(){ nav({states:null, loc:'all'}) }

function toast(msg,color='#16a34a'){
  const t=document.getElementById('toast')
  t.textContent=msg;t.style.background=color;t.style.color='#fff'
  t.style.display='block';clearTimeout(t._t);t._t=setTimeout(()=>t.style.display='none',3500)
}
function toggleMat(id){ document.getElementById('mat-'+id).classList.toggle('open') }
function copyText(id){
  navigator.clipboard.writeText(document.getElementById(id).textContent).then(()=>toast('Copied!'))
}

const selected=new Set()
function onCheck(id,el){
  const card=document.getElementById('card-'+id)
  if(el.checked){selected.add(id);card.classList.add('selected')}
  else{selected.delete(id);card.classList.remove('selected')}
  updateBulkBar()
}
function updateBulkBar(){
  const n=selected.size
  document.getElementById('sel-count').textContent=n
  document.getElementById('bulk-count').textContent=n
  document.getElementById('bulk-bar').classList.toggle('hidden',n===0)
}
function selectAll(){
  document.querySelectorAll('input[type=checkbox]').forEach(cb=>{
    if(!cb.checked){cb.checked=true;onCheck(cb.id.replace('chk-',''),cb)}
  })
}
function deselectAll(){
  document.querySelectorAll('input[type=checkbox]').forEach(cb=>{
    if(cb.checked){cb.checked=false;onCheck(cb.id.replace('chk-',''),cb)}
  })
}

async function applyNow(id,btn){
  const card=document.getElementById('card-'+id)
  card.classList.add('loading');btn.innerHTML='<span class="spin"></span> Submitting...';btn.disabled=true
  try{
    const r=await fetch('/approve/'+id,{method:'POST'})
    const d=await r.json()
    if(d.ok){
      toast(d.auto_submitted?'⚡ Auto-submitted!':'📬 Materials ready — submit manually')
      card.classList.remove('loading');card.classList.add('done-anim')
      setTimeout(()=>location.reload(),900)
    }else{
      toast('Error: '+d.error,'#dc2626')
      card.classList.remove('loading');btn.innerHTML='🚀 Apply Now';btn.disabled=false
    }
  }catch(e){
    toast('Network error','#dc2626')
    card.classList.remove('loading');btn.innerHTML='🚀 Apply Now';btn.disabled=false
  }
}
async function markApplied(id,btn){
  btn.disabled=true
  const r=await fetch('/mark_applied/'+id,{method:'POST'})
  const d=await r.json()
  if(d.ok){toast('✅ Marked as applied!');setTimeout(()=>location.reload(),600)}
  else{toast('Error','#dc2626');btn.disabled=false}
}

let _pollTimer=null
async function bulkApply(btn){
  if(selected.size===0)return
  btn.disabled=true;btn.innerHTML='<span class="spin"></span> Starting...'
  const ids=Array.from(selected)
  const r=await fetch('/approve_batch',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})})
  const d=await r.json()
  if(!d.ok){toast('Batch start failed','#dc2626');btn.disabled=false;return}
  document.getElementById('progress-wrap').classList.add('show')
  document.getElementById('progress-total').textContent=ids.length
  deselectAll()
  _pollTimer=setInterval(pollBatch,1500)
}
async function pollBatch(){
  try{
    const r=await fetch('/batch_status')
    const d=await r.json()
    const pct=d.total>0?Math.round(d.done/d.total*100):0
    document.getElementById('progress-fill').style.width=pct+'%'
    document.getElementById('progress-done').textContent=d.done
    document.getElementById('progress-total').textContent=d.total
    document.getElementById('progress-current').textContent=d.current||'...'
    if(!d.running){
      clearInterval(_pollTimer)
      document.getElementById('progress-wrap').classList.remove('show')
      toast(d.errors.length>0?`Done! ${d.done} processed, ${d.errors.length} failed`:`✅ All ${d.done} done!`,
            d.errors.length>0?'#d97706':'#16a34a')
      const btn=document.getElementById('bulk-btn')
      if(btn){btn.disabled=false;btn.innerHTML='🚀 Apply Selected (<span id="bulk-count">0</span>)'}
      setTimeout(()=>location.reload(),1500)
    }
  }catch(e){}
}
async function skip(id,btn){
  btn.disabled=true
  const r=await fetch('/skip/'+id,{method:'POST'})
  const d=await r.json()
  if(d.ok){
    const card=document.getElementById('card-'+id)
    card.style.transition='opacity .25s';card.style.opacity='0'
    toast(d.new_status==='skipped'?'⏭ Skipped':'↩ Restored')
    setTimeout(()=>location.reload(),400)
  }
}
async function fetchJobs(btn){
  btn.innerHTML='<span class="spin"></span> Fetching...';btn.disabled=true
  try{
    const r=await fetch('/fetch',{method:'POST'})
    const d=await r.json()
    toast(d.message);setTimeout(()=>location.reload(),1200)
  }catch(e){toast('Fetch failed','#dc2626')}
  finally{btn.innerHTML='🔄 Fetch';btn.disabled=false}
}
async function sendDigest(btn){
  btn.innerHTML='<span class="spin"></span> Sending...';btn.disabled=true
  try{
    const r=await fetch('/digest',{method:'POST'})
    const d=await r.json()
    toast(d.message,d.ok?'#16a34a':'#d97706')
  }catch(e){toast('Error','#dc2626')}
  finally{btn.innerHTML='📧 Digest';btn.disabled=false}
}
</script>
</body></html>"""

# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    tab        = request.args.get("tab", "tight")   # NEW default: your working list
    days       = request.args.get("days", "all")
    loc_filter = request.args.get("loc", "all")
    states_raw = request.args.get("states", "")
    selected_states = [s.strip() for s in states_raw.split(",") if s.strip() in US_STATES]

    inbox = load_inbox()
    stats = inbox_stats(inbox)

    new_jobs = [j for j in inbox if j.get("status") == "new"]

    if tab in ("daily", "tight", "rest"):
        view = tier_jobs(new_jobs, tight_limit=TIGHT_LIMIT)
        jobs = view[tab]
    elif tab == "programs":
        for j in new_jobs:
            score_and_tier(j)   # ensure tier_score is current
        jobs = sorted([j for j in new_jobs if is_program_role(j.get("role",""))],
                      key=lambda x: -x.get("tier_score", 0))
    elif tab == "strong":
        jobs = sorted([j for j in new_jobs if j.get("triage")=="Strong"],
                      key=lambda x: -x.get("tier_score", 0))
    elif tab == "maybe":
        jobs = sorted([j for j in new_jobs if j.get("triage")=="Maybe"],
                      key=lambda x: -x.get("tier_score", 0))
    elif tab == "pending":
        jobs = [j for j in inbox if j.get("status")=="pending"]
    elif tab == "approved":
        jobs = [j for j in inbox if j.get("status")=="approved"]
    elif tab == "skipped":
        jobs = [j for j in inbox if j.get("status")=="skipped"]
    else:
        jobs = sorted(new_jobs, key=lambda x: -x.get("tier_score", 0))

    jobs = apply_filters(jobs, days, loc_filter, selected_states)

    return render_template_string(PAGE,
        jobs=jobs, stats=stats,
        tab=tab, days=days, loc_filter=loc_filter,
        selected_states=selected_states,
        all_states=US_STATES,
        state_names=STATE_NAMES,
        tight_limit=TIGHT_LIMIT,
        auto_submit_on=AUTO_SUBMIT_AVAILABLE)

@app.route("/fetch", methods=["POST"])
def api_fetch():
    added = fetch_all_new_jobs(clear_html_junk=True)
    return jsonify({"ok":True,"message":f"Added {added} new job(s) — refresh to see them"})

@app.route("/approve/<job_id>", methods=["POST"])
def api_approve(job_id):
    success, auto_submitted = _do_approve(job_id)
    if not success: return jsonify({"ok":False,"error":"Failed to generate materials"})
    return jsonify({"ok":True,"auto_submitted":auto_submitted})

@app.route("/mark_applied/<job_id>", methods=["POST"])
def api_mark_applied(job_id):
    inbox = load_inbox()
    for j in inbox:
        if j["id"] == job_id:
            j["status"] = "approved"
            try: track_application(j["company"],j["role"],"applied",f"Manually submitted {date.today()}")
            except Exception: pass
            break
    save_inbox(inbox)
    return jsonify({"ok":True})

@app.route("/approve_batch", methods=["POST"])
def api_approve_batch():
    with _batch_lock:
        if _batch_state["running"]: return jsonify({"ok":False,"error":"Batch already running"})
    data = request.get_json()
    ids  = data.get("ids",[])
    if not ids: return jsonify({"ok":False,"error":"No IDs"})
    threading.Thread(target=_run_batch,args=(ids,),daemon=True,name="batch-apply").start()
    return jsonify({"ok":True,"total":len(ids)})

@app.route("/batch_status")
def api_batch_status():
    with _batch_lock: return jsonify(dict(_batch_state))

@app.route("/skip/<job_id>", methods=["POST"])
def api_skip(job_id):
    inbox = load_inbox()
    new_status = "new"
    for j in inbox:
        if j["id"] == job_id:
            new_status = "skipped" if j["status"] in ("new","approved","pending") else "new"
            j["status"] = new_status; break
    save_inbox(inbox)
    return jsonify({"ok":True,"new_status":new_status})

@app.route("/digest", methods=["POST"])
def api_digest():
    msg = send_top10_digest("Manual")
    ok  = not any(w in msg.lower() for w in ("failed","not configured","error"))
    return jsonify({"ok":ok,"message":msg})

# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_scheduler():
    sched = BackgroundScheduler(daemon=True)
    # Fetch new jobs at 8am
    sched.add_job(fetch_all_new_jobs, "cron", hour=8, minute=0,
                  id="daily_fetch", replace_existing=True)
    # Top-10 digests at 8:05am, 12:00pm, 5:00pm
    sched.add_job(lambda: send_top10_digest("Morning"), "cron", hour=8,  minute=5,
                  id="digest_morning", replace_existing=True)
    sched.add_job(lambda: send_top10_digest("Midday"),  "cron", hour=12, minute=0,
                  id="digest_noon",    replace_existing=True)
    sched.add_job(lambda: send_top10_digest("Evening"), "cron", hour=17, minute=0,
                  id="digest_evening", replace_existing=True)
    sched.start()
    print("[Inbox] Scheduler started — fetch 8:00am · digests 8:05am / 12:00pm / 5:00pm")
    return sched

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n📋  Job Hunting Inbox  v2.1")
    print(f"    http://localhost:{PORT}")
    print(f"    Auto-submit: {'✓ Playwright ready' if AUTO_SUBMIT_AVAILABLE else '✗ pip install playwright && playwright install chromium'}")
    print(f"    Email: {'✓ configured' if EMAIL_FROM else '✗ set EMAIL_FROM/TO/PASSWORD in .env'}")
    print(f"    Tiers: 🔥 Daily Watch · ⭐ Top {TIGHT_LIMIT} · 📂 Everything")
    print(f"    Digests: 8:05am · 12:00pm · 5:00pm\n")

    threading.Thread(target=lambda: fetch_all_new_jobs(clear_html_junk=True),
                     daemon=True, name="initial-fetch").start()
    sched = start_scheduler()
    try:
        app.run(host="0.0.0.0",port=PORT,debug=False,use_reloader=False)
    finally:
        sched.shutdown()