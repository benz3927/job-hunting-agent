"""
tiers.py  —  Tiering + scoring layer for Job Hunting Inbox
───────────────────────────────────────────────────────────
Drop this file next to inbox_app.py and wire in the 3 hooks
described at the bottom. It does NOT replace your triage —
it adds a tier (A / B / C) and a numeric score on top.

Tier A  →  Daily watch   (Fed, gov research) — always shown, never date-filtered
Tier B  →  Attainable    (curated brand names) — your tight ~25 list
Tier C  →  Everything else (the long tail) — hidden behind a click
"""

import re

# ── Tier A: check-every-day targets ───────────────────────────────────────────
# Hard but realistic dream stuff + gov research. Matched on company substring.
TIER_A_COMPANIES = {
    "federal reserve", "minneapolis fed", "fed reserve", "reserve bank",
    "board of governors", "frb",
    "census", "bureau of labor", "bls", "bureau of economic",
    "national lab", "argonne", "oak ridge", "lawrence", "sandia", "los alamos",
    "nber", "rand corporation", "brookings", "peterson institute",
}

# ── Tier B: attainable & good (curated) ───────────────────────────────────────
# Brand-name but reachable for a strong MS grad. Matched on company substring.
TIER_B_COMPANIES = {
    # big tech / finance with real new-grad programs
    "ibm", "capital one", "blackrock", "stripe", "american express", "amex",
    "fidelity", "charles schwab", "state street", "pnc", "t. rowe", "t rowe",
    # major banks & insurers
    "goldman sachs", "jpmorgan", "jp morgan", "morgan stanley", "wells fargo",
    "bank of america", "citi", "citigroup", "us bank", "u.s. bank", "bny",
    "prudential", "metlife", "massmutual", "mass mutual", "new york life",
    "northwestern mutual", "guardian", "aig", "corebridge", "travelers",
    "the hartford", "nationwide", "principal financial", "lincoln financial",
    # brand-name non-finance
    "disney", "walt disney", "fedex", "federal express", "microsoft", "amazon",
    "google", "nbcuniversal", "warner bros", "comcast", "verizon", "at&t",
    "johnson & johnson", "j&j", "procter", "p&g", "ge ", "honeywell",
    "caterpillar", "john deere", "deloitte", "accenture", "kpmg", "ey ", "pwc",
    # healthcare / pharma / payers
    "cvs", "unitedhealth", "optum", "humana", "cigna", "anthem", "elevance",
    "aetna", "kaiser", "mayo clinic", "cleveland clinic", "regeneron",
    "merck", "pfizer", "bristol", "genentech", "moderna", "novartis",
    "children's hospital", "mass general", "mgh", "northwell", "rwjbarnabas",
    "cedars-sinai", "tufts", "northwestern university", "princeton university",
}

# ── Location scoring ──────────────────────────────────────────────────────────
# NJ best → NY metro → rest of Northeast → remote → elsewhere
LOC_NJ = {"new jersey", "nj", "princeton", "trenton", "jersey city", "hoboken",
          "newark", "new brunswick", "toms river", "morristown", "paramus",
          "livingston", "oldwick", "cranbury"}
LOC_NY_METRO = {"new york", "nyc", "manhattan", "brooklyn", "queens",
                "long island", "melville", "white plains", "yonkers",
                "rye brook", "tarrytown"}
LOC_NORTHEAST = {"pennsylvania", "philadelphia", "philly", "pittsburgh",
                 "harrisburg", "massachusetts", "boston", "cambridge",
                 "somerville", "connecticut", "stamford", "hartford",
                 "new haven", "greenwich", "rhode island", "providence",
                 "washington dc", "washington, dc", "dc", "maryland",
                 "baltimore", "bethesda", "delaware", "newark, de",
                 "vermont", "maine", "new hampshire", "albany"}
LOC_REMOTE = {"remote", "anywhere", "distributed", "wfh", "work from home",
              "remote-friendly"}


def _company_tier(company: str) -> str:
    c = company.lower()
    if any(name in c for name in TIER_A_COMPANIES):
        return "A"
    if any(name in c for name in TIER_B_COMPANIES):
        return "B"
    return "C"


def _location_score(location: str) -> int:
    if not location:
        return 0
    l = location.lower()
    if any(x in l for x in LOC_NJ):        return 40   # home turf
    if any(x in l for x in LOC_NY_METRO):  return 32
    if any(x in l for x in LOC_NORTHEAST): return 24
    if any(x in l for x in LOC_REMOTE):    return 28
    return 0


def _program_bonus(role: str) -> int:
    r = role.lower()
    prog = ("development program", "rotational program", "analyst program",
            "associate program", "leadership development", "new grad program",
            "early career")
    return 15 if any(p in r for p in prog) else 0


def _role_strength(role: str) -> int:
    r = role.lower()
    strong = ("data scientist", "quantitative", "quant ", "research analyst",
              "machine learning", "ml engineer", "research scientist",
              "applied scientist", "statistician", "economist", "research engineer")
    ok = ("data analyst", "business analyst", "analytics", "research")
    if any(s in r for s in strong): return 20
    if any(s in r for s in ok):     return 8
    return 0


def score_and_tier(job: dict) -> dict:
    """Annotate a job in place with 'tier' (A/B/C) and 'tier_score' (int).
    Higher score = more interesting. Safe to call repeatedly."""
    company = job.get("company", "")
    role    = job.get("role", "")
    loc     = job.get("location", "")

    tier = _company_tier(company)
    score = 0
    if   tier == "A": score += 100
    elif tier == "B": score += 50

    score += _location_score(loc)
    score += _program_bonus(role)
    score += _role_strength(role)

    # nudge by existing triage if present
    tri = job.get("triage", "")
    if   tri == "Strong": score += 12
    elif tri == "Maybe":  score += 4
    elif tri == "Skip":   score -= 30

    job["tier"] = tier
    job["tier_score"] = score
    return job


def tier_jobs(jobs: list, tight_limit: int = 25) -> dict:
    """Return jobs split into the three views.
    - 'daily'  : all Tier A (never capped)
    - 'tight'  : top `tight_limit` Tier B by score
    - 'rest'   : everything else (Tier C + overflow B)
    """
    for j in jobs:
        score_and_tier(j)

    a = sorted([j for j in jobs if j.get("tier") == "A"],
               key=lambda x: -x["tier_score"])
    b = sorted([j for j in jobs if j.get("tier") == "B"],
               key=lambda x: -x["tier_score"])
    c = sorted([j for j in jobs if j.get("tier") == "C"],
               key=lambda x: -x["tier_score"])

    tight = b[:tight_limit]
    rest  = b[tight_limit:] + c
    return {"daily": a, "tight": tight, "rest": sorted(rest, key=lambda x: -x["tier_score"])}


# ── Quick self-test against a few sample rows from your inbox ──────────────────
if __name__ == "__main__":
    samples = [
        {"company": "Minneapolis Fed", "role": "Research Assistant", "location": "Minneapolis, MN", "triage": "Strong"},
        {"company": "IBM", "role": "Associate AI & Analytics – Data Scientist", "location": "New York, NY", "triage": "Maybe"},
        {"company": "Capital One", "role": "Data & Analytics Development Program", "location": "McLean, VA", "triage": "Maybe"},
        {"company": "Corebridge Financial", "role": "ERM Business Data Analyst", "location": "Jersey City, NJ", "triage": "Maybe"},
        {"company": "Gotion Inc.", "role": "Data Analyst", "location": "Manteno, IL", "triage": "Maybe"},
        {"company": "Children's Hospital of Philadelphia", "role": "Research Data Analyst I", "location": "Philadelphia, PA", "triage": "Maybe"},
        {"company": "RemoteHunter", "role": "Junior Data Analyst (Remote)", "location": "United States", "triage": "Maybe"},
    ]
    out = tier_jobs(samples, tight_limit=25)
    print("\n— DAILY (Tier A) —")
    for j in out["daily"]:
        print(f"  [{j['tier_score']:>3}] {j['company']} — {j['role']}")
    print("\n— TIGHT (top Tier B) —")
    for j in out["tight"]:
        print(f"  [{j['tier_score']:>3}] {j['company']} — {j['role']}  ({j['location']})")
    print("\n— REST —")
    for j in out["rest"]:
        print(f"  [{j['tier_score']:>3}] {j['company']} — {j['role']}  ({j['location']})")