# CLAUDE.md — working notes for this repo

This file is read automatically at the start of every session. It records how I
work, what the project is, and the rules that don't change. Keep it short and
factual. Update it when something here stops being true.

## How to talk to me

- Be concise and direct. Cut words that don't change the meaning.
- Be grounded. No glazing, no flattery, no "great question." State what's true,
  including when something won't work or when I'm wrong.
- Don't pad with caveats or summaries I didn't ask for. Lead with the answer.
- I code in Python, R, and Linux shell. Default to those.

## What this project is

A job-hunting agent (Anthropic SDK, native tool use). It searches jobs, scores
fit against `profile.yaml`, tailors resumes, writes cover letters, auto-fills
ATS forms, and tracks applications. Entry points: `job_agent.py` (CLI),
`app.py` (Gradio), `inbox_app.py` (Flask approval inbox).

- `profile.yaml` is the single source of truth for the candidate. The agent
  reads it; everything tailors off it.
- `build_profile.py` regenerates `profile.yaml` from any resume PDF — run it
  when the resume changes, don't hand-edit unless it's a small fix.

## Cover letter rules (non-negotiable)

- No em-dashes. Use periods or commas. This applies everywhere a letter is
  generated.
- Plain English. Lead with substance, not "I am excited to."
- Banned phrases: excited to, passionate about, eager to learn, eager to grow,
  I would love to, thrilled, looking forward to, be part of your team.
- Concrete projects with numbers in the middle paragraph. Sign off "Sincerely,".

## Job prioritization (what to surface first)

Ranking lives in `tiers.py`. Priority order:

1. Federal Reserve and government research (Tier A): the Fed banks, Board of
   Governors, BLS, Census, national labs, NBER, RAND, Brookings. Always shown.
2. Structured early-career programs, especially development and rotational
   programs: technical / technology / engineering / accelerated / leadership
   development programs, rotational analyst programs. Big established firms
   (IBM, Capital One, the banks/insurers in Tier B) run these. Prioritize the
   PROGRAM postings, not just any role at the company.
3. Then strong individual roles (DS, ML, quant, research) by fit and location.

`_program_bonus` in `tiers.py` is the lever for #2. ATS sourcing is still just
Greenhouse and Lever. Not ADP.

## When in doubt

Ask one sharp question rather than guessing on anything that touches the resume,
the cover letter voice, or which jobs get prioritized.
