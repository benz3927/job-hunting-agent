"""
auto_submit.py v3 — Playwright job application auto-filler
───────────────────────────────────────────────────────────
Uses exact field IDs discovered by inspection.
Uses page.fill('#id') which works with React forms.
Does NOT submit — leaves browser open for you to review + submit.
"""

import os, time, yaml
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv
load_dotenv()

PROFILE_PATH = Path("profile.yaml")
RESUME_PDF   = Path("BenjaminZhaoResume.pdf")


def load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f) or {}


def _detect_platform(url: str) -> str:
    url = url.lower()
    if "greenhouse.io" in url or "grnh.se" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    return "unknown"


def _fill(page, selector: str, value: str):
    """Fill using page.fill() — works with React. Skip silently if not found."""
    try:
        page.wait_for_selector(selector, timeout=3000, state="visible")
        page.click(selector)
        page.fill(selector, value)
    except Exception:
        pass


def _select(page, selector: str, label: str):
    """Select dropdown option by visible label text."""
    try:
        page.wait_for_selector(selector, timeout=3000, state="visible")
        page.select_option(selector, label=label)
    except Exception:
        pass


def _type_into(page, selector: str, value: str):
    """Click and type — for fields where fill() doesn't trigger events."""
    try:
        page.wait_for_selector(selector, timeout=3000, state="visible")
        page.click(selector)
        page.keyboard.press("Control+a")
        page.keyboard.type(value)
    except Exception:
        pass


def _upload_file(page, selector: str, path: str):
    try:
        page.wait_for_selector(selector, timeout=3000)
        page.set_input_files(selector, path)
        time.sleep(1)
    except Exception:
        pass


def _generate_why_company(company: str, role: str, profile: dict) -> str:
    """Generate 'Why this company?' answer via Claude."""
    try:
        import anthropic as ac
        client = ac.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        resp = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=500,
            messages=[{"role": "user", "content":
                f"""Write a sincere 250-300 word answer to "Why do you want to work at {company}?"
for this candidate applying for {role}.

CANDIDATE:
- {profile.get('resume_summary', '')}
- Projects: {[p['name'] for p in profile.get('projects', [])]}
- Awards: {profile.get('awards', [])}

Rules:
- Be specific to {company}'s actual mission and work, not generic
- Connect their real projects/experience concretely
- Do NOT use: excited, passionate, thrilled, eager to learn, looking forward
- 250-300 words, flowing prose, no bullets
- Do NOT start with "I want to work at {company}"
"""}])
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"[auto_submit] Why-company generation failed: {e}")
        return ""


def _inspect_and_fill(page, profile: dict, cover_letter: str, company: str, role: str):
    """
    Generic label-based filler — discovers question IDs by matching label text,
    then fills using page.fill('#id') which works with React.
    """
    # Build label → field_id map
    label_map = {}
    try:
        labels = page.query_selector_all("label[for]")
        for lbl in labels:
            text = lbl.inner_text().strip().lower()
            for_id = lbl.get_attribute("for")
            if for_id:
                label_map[text] = for_id
    except Exception:
        pass

    def fill_by_label(patterns: list[str], value: str):
        for pattern in patterns:
            for text, fid in label_map.items():
                if pattern.lower() in text:
                    _fill(page, f"#{fid}", value)
                    return True
        return False

    def select_by_label(patterns: list[str], option_label: str):
        for pattern in patterns:
            for text, fid in label_map.items():
                if pattern.lower() in text:
                    _select(page, f"#{fid}", option_label)
                    return True
        return False

    def type_by_label(patterns: list[str], value: str):
        for pattern in patterns:
            for text, fid in label_map.items():
                if pattern.lower() in text:
                    _type_into(page, f"#{fid}", value)
                    return True
        return False

    p = profile
    first = p.get("name", "Benjamin Zhao").split()[0]
    last  = p.get("name", "Benjamin Zhao").split()[-1]

    # ── Standard fields (known IDs on Greenhouse) ─────────────────────────────
    _fill(page, "#first_name",     first)
    _fill(page, "#last_name",      last)
    _fill(page, "#preferred_name", first)
    _fill(page, "#email",          p.get("email", ""))
    _fill(page, "#phone",          p.get("phone", ""))

    # Phone via label fallback
    fill_by_label(["phone"], p.get("phone", ""))

    # ── Resume upload ─────────────────────────────────────────────────────────
    if RESUME_PDF.exists():
        _upload_file(page, "#resume", str(RESUME_PDF.resolve()))

    # ── Cover letter upload ───────────────────────────────────────────────────
    if cover_letter:
        # Try file upload
        tmp = Path("/tmp/cover_letter_ben.txt")
        tmp.write_text(cover_letter)
        _upload_file(page, "#cover_letter", str(tmp))
        # Try textarea
        fill_by_label(["cover letter", "additional information", "anything else"], cover_letter)
        type_by_label(["cover letter text"], cover_letter)

    # ── Website / LinkedIn / GitHub ───────────────────────────────────────────
    linkedin = p.get("linkedin", "")
    if linkedin:
        li_url = f"https://{linkedin}" if not linkedin.startswith("http") else linkedin
        fill_by_label(["linkedin"], li_url)
        _fill(page, "#question_14798602008", li_url)  # Anthropic-specific

    github = p.get("github", "")
    if github:
        gh_url = github if github.startswith("http") else f"https://{github}"
        fill_by_label(["website", "github", "portfolio"], gh_url)
        _fill(page, "#question_14798593008", gh_url)  # Anthropic-specific

    # ── Current company ───────────────────────────────────────────────────────
    fill_by_label(["currently working", "current company", "company"], "Hamilton College")
    _fill(page, "#question_15038390008", "Hamilton College")  # Anthropic-specific

    # ── Start date ────────────────────────────────────────────────────────────
    fill_by_label(["earliest you would want to start", "start date", "start working"], "June 2026")
    _fill(page, "#question_14798595008", "June 2026")

    # ── "Why this company?" ───────────────────────────────────────────────────
    why = _generate_why_company(company, role, p)
    if why:
        type_by_label(["why anthropic", "why do you want", "motivation", "why this"], why)
        # Anthropic-specific ID
        try:
            el = page.query_selector("#question_14798598008")
            if el:
                page.click("#question_14798598008")
                page.fill("#question_14798598008", why)
        except Exception:
            pass

    # ── Dropdowns ─────────────────────────────────────────────────────────────
    # In-person 25%
    select_by_label(["in-person", "office 25", "hybrid"], "Yes")
    _select(page, "#question_14798594008", "Yes")

    # AI Policy
    select_by_label(["ai policy"], "Yes")
    _select(page, "#question_14798597008", "Yes")

    # Visa sponsorship — No
    select_by_label(["require visa sponsorship", "visa sponsorship"], "No")
    _select(page, "#question_14798599008", "No")
    _select(page, "#question_14798600008", "No")

    # 5+ years experience — No
    select_by_label(["5+ years", "5 or more years"], "No")
    _select(page, "#question_14845346008", "No")

    # Relocation
    select_by_label(["open to relocation", "relocation"], "Yes")
    _select(page, "#question_14798603008", "Yes")

    # Working address
    fill_by_label(["address from which", "working address", "plan on working"], "Princeton, NJ 08540")
    _fill(page, "#question_14798604008", "Princeton, NJ 08540")

    # Interviewed before — No
    select_by_label(["interviewed at", "interviewed before"], "No")
    _select(page, "#question_14798605008", "No")

    # Applied in past 3 months — No
    select_by_label(["applied for this role", "past 3 months", "applied before"], "No")
    _select(page, "#question_14845347008", "No")


def _fill_greenhouse(page, profile: dict, cover_letter: str, company: str, role: str) -> dict:
    # Wait for form
    try:
        page.wait_for_selector("#first_name, input[id='first_name']", timeout=12000)
    except PlaywrightTimeout:
        return {"ok": False, "method": "greenhouse", "message": "Form did not load"}

    time.sleep(1)
    _inspect_and_fill(page, profile, cover_letter, company, role)

    print("\n✅ Form filled! A few fields still need you:")
    print("   • Pillar selection (Platform / Consumer / Research / Enterprise...)")
    print("   • Country phone code (flag dropdown next to phone)")
    print("   • Voluntary self-ID (gender, race, disability) — your choice")
    print("   • Review 'Why Anthropic?' answer looks good")
    print("\n   Then click Submit Application.\n")

    return {"ok": True, "method": "greenhouse",
            "message": "Form filled — review and click Submit"}


def _fill_lever(page, profile: dict, cover_letter: str, company: str, role: str) -> dict:
    try:
        page.wait_for_selector("input[name='name'], input[id='name']", timeout=10000)
    except PlaywrightTimeout:
        return {"ok": False, "method": "lever", "message": "Form did not load"}

    time.sleep(1)
    p = profile

    _fill(page, "input[name='name']",  p.get("name", ""))
    _fill(page, "input[name='email']", p.get("email", ""))
    _fill(page, "input[name='phone']", p.get("phone", ""))
    _fill(page, "input[name='org']",   "Hamilton College")

    linkedin = p.get("linkedin", "")
    if linkedin:
        url = f"https://{linkedin}" if not linkedin.startswith("http") else linkedin
        _fill(page, "input[name='urls[LinkedIn]']", url)

    if RESUME_PDF.exists():
        _upload_file(page, "input[type='file']", str(RESUME_PDF.resolve()))

    if cover_letter:
        try:
            el = page.query_selector("textarea[name='comments'], textarea")
            if el:
                page.click("textarea[name='comments'], textarea")
                page.fill("textarea[name='comments']", cover_letter)
        except Exception:
            pass

    print("\n✅ Lever form filled! Review and click Submit.\n")
    return {"ok": True, "method": "lever", "message": "Form filled — review and click Submit"}


def auto_submit(job_url: str, cover_letter: str = "",
                headless: bool = False) -> dict:
    return auto_submit_with_context(job_url, cover_letter, "the company", "the role", headless)


def auto_submit_with_context(job_url: str, cover_letter: str,
                              company: str, role: str,
                              headless: bool = False) -> dict:
    if not job_url:
        return {"ok": False, "method": "manual", "message": "No URL"}

    platform = _detect_platform(job_url)
    if platform == "unknown":
        import webbrowser
        webbrowser.open(job_url)
        return {"ok": False, "method": "manual", "message": "Opened in browser"}

    if not RESUME_PDF.exists():
        return {"ok": False, "method": platform,
                "message": f"Resume PDF not found at {RESUME_PDF}"}

    profile = load_profile()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless, slow_mo=60)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.goto(job_url, timeout=25000, wait_until="networkidle")
            time.sleep(2)

            if platform == "greenhouse":
                result = _fill_greenhouse(page, profile, cover_letter, company, role)
            else:
                result = _fill_lever(page, profile, cover_letter, company, role)

            if result["ok"]:
                # Stay open 5 min for you to review + submit
                page.wait_for_timeout(300_000)
            else:
                page.wait_for_timeout(15_000)

            browser.close()
            return result

    except Exception as e:
        return {"ok": False, "method": platform, "message": f"Playwright error: {e}"}


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not url:
        print("Usage: python auto_submit.py <job_url>")
        sys.exit(1)
    result = auto_submit_with_context(url, "See attached cover letter.", "Anthropic", "Data Scientist")
    print(result)