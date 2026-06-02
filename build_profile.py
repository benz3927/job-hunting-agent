#!/usr/bin/env python3
"""
build_profile.py — Turn ANY resume PDF into a profile.yaml for the job-hunting agent.

Usage:
    python build_profile.py resume.pdf                 # writes profile.yaml
    python build_profile.py resume.pdf -o me.yaml      # custom output path
    python build_profile.py resume.pdf --print         # print to stdout only

The PDF is sent natively to Claude, which extracts a structured profile that
matches the schema the rest of the agent (job_agent.py, auto_submit.py) reads:
name/email/phone/linkedin/github, education, skills, projects, experience,
awards, target_roles, target_locations, target_industries, salary_target_usd,
resume_summary, and a generated cover_letter_sample.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

MODEL = os.environ.get("PROFILE_MODEL", "claude-sonnet-4-6")

# Field order for a clean, human-readable YAML file.
FIELD_ORDER = [
    "name", "email", "phone", "linkedin", "github",
    "education", "skills", "projects", "experience", "awards",
    "target_roles", "target_locations", "target_industries",
    "salary_target_usd", "resume_summary", "cover_letter_sample",
]

SYSTEM = "You are a precise resume parser. You output only valid JSON, no prose."

PROMPT = """Read the attached resume PDF and produce a JSON object describing the
candidate. Use ONLY information present in the resume; never invent facts. If a
field is unknown, omit it (for strings) or use an empty list.

Return JSON with EXACTLY these top-level keys:

{
  "name": str,
  "email": str,
  "phone": str,
  "linkedin": str,          // bare url, e.g. "linkedin.com/in/xxx", "" if none
  "github": str,            // bare url, "" if none
  "education": [
    {"degree": str, "school": str, "location": str,
     "gpa": str|null, "graduation": str, "coursework": [str]}
  ],
  "skills": {               // group skills into sensible category keys.
                            // keys are flexible (e.g. languages, frameworks,
                            // tools, cloud, other) — use what fits the resume.
    "<category>": [str]
  },
  "projects": [
    {"name": str, "org": str|null, "dates": str, "bullets": [str]}
  ],
  "experience": [
    {"title": str, "org": str, "dates": str, "bullets": [str]}
  ],
  "awards": [str],          // each "Award name - date/context"

  // The following are INFERRED from the resume's content, not copied verbatim.
  "target_roles": [str],        // 4-8 realistic roles this person should target
  "target_locations": [str],    // include "Remote" + any cities they mention
  "target_industries": [str],   // 3-6 industries matching their background
  "salary_target_usd": int,     // a reasonable target given level/field, USD
  "resume_summary": str,        // 3-5 sentence elevator pitch, third person

  "cover_letter_sample": str    // see rules below
}

RULES for cover_letter_sample:
- One clean general-purpose cover letter, ~250-320 words, plain English.
- No em-dashes. No "I am excited to" openings. Lead with substance.
- Reference the candidate's strongest, most concrete projects/experience.
- End with "Sincerely, <name>".

Keep bullets faithful to the resume wording but tightened. Output JSON only.
"""


def pdf_to_block(pdf_path: Path) -> dict:
    data = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": data},
    }


def extract_profile(pdf_path: Path) -> dict:
    import anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set (check your .env).")

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": [
            pdf_to_block(pdf_path),
            {"type": "text", "text": PROMPT},
        ]}],
    )
    text = resp.content[0].text.strip()

    # Strip ```json fences if present, then parse.
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().strip("`").strip()
    # Slice to outermost braces as a safety net.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: Claude did not return valid JSON: {e}\n\n{text[:1000]}")


def ordered(profile: dict) -> dict:
    out = {k: profile[k] for k in FIELD_ORDER if k in profile}
    for k, v in profile.items():  # keep any extra keys at the end
        if k not in out:
            out[k] = v
    return out


def to_yaml(profile: dict) -> str:
    header = "# === Job Hunting Agent - Candidate Profile ===\n"
    header += "# Auto-generated from a resume PDF by build_profile.py\n\n"
    body = yaml.safe_dump(
        ordered(profile),
        sort_keys=False, allow_unicode=True, default_flow_style=False, width=100,
    )
    return header + body


def main():
    ap = argparse.ArgumentParser(description="Build profile.yaml from a resume PDF.")
    ap.add_argument("pdf", help="Path to the resume PDF")
    ap.add_argument("-o", "--out", default="profile.yaml", help="Output path")
    ap.add_argument("--print", action="store_true", dest="to_stdout",
                    help="Print to stdout instead of writing a file")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"ERROR: file not found: {pdf_path}")

    print(f"[build_profile] Parsing {pdf_path.name} with {MODEL} ...", file=sys.stderr)
    profile = extract_profile(pdf_path)
    text = to_yaml(profile)

    if args.to_stdout:
        print(text)
    else:
        Path(args.out).write_text(text)
        print(f"[build_profile] Wrote {args.out} "
              f"({len(profile.get('projects', []))} projects, "
              f"{len(profile.get('experience', []))} jobs).", file=sys.stderr)


if __name__ == "__main__":
    main()
