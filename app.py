"""
Job Hunting Agent — Gradio frontend (Gradio 6 compatible)
Run: python app.py
"""

import os
import json
import gradio as gr
from dotenv import load_dotenv
from job_agent import (
    run_agent, view_applications, load_tracker,
    search_jobs, fetch_ats_jobs, score_job_fit,
    tailor_resume, track_application, TOOL_FN_MAP
)

load_dotenv()

MEMORY_WINDOW = 10

def trim_history(history):
    if len(history) > MEMORY_WINDOW:
        history = history[-MEMORY_WINDOW:]
        while history and not (
            isinstance(history[0].get("content"), str) and
            history[0].get("role") == "user"
        ):
            history = history[1:]
    return history


def chat(user_message, history_display, agent_history):
    if not user_message.strip():
        return history_display, agent_history, "", ""

    agent_history = trim_history(agent_history)
    tool_log = []
    original_map = dict(TOOL_FN_MAP)

    def make_logged(n, f):
        def logged(i):
            result = f(i)
            tool_log.append(f"[{n}] {json.dumps(i)[:80]}\nResult: {result[:200]}")
            return result
        return logged

    for name, fn in original_map.items():
        TOOL_FN_MAP[name] = make_logged(name, fn)

    try:
        answer, agent_history = run_agent(user_message, agent_history)
    except Exception as e:
        answer = f"Error: {e}"
    finally:
        TOOL_FN_MAP.update(original_map)

    history_display = history_display + f"\n\nYou: {user_message}\n\nAgent: {answer}"
    tool_display = "\n\n---\n\n".join(tool_log) if tool_log else "No tools called"
    return history_display.strip(), agent_history, "", tool_display


def get_tracker_text():
    return view_applications("all")

def quick_search(query):
    return search_jobs(query)

def quick_fetch(slug, platform):
    return fetch_ats_jobs(slug, platform)

def quick_score(jd):
    return score_job_fit(jd)

def quick_tailor(jd):
    return tailor_resume(jd)

def quick_track(company, role, status, notes):
    result = track_application(company, role, status, notes)
    return result, get_tracker_text()


with gr.Blocks(title="Job Hunting Agent") as demo:

    agent_history = gr.State([])

    gr.Markdown("# Job Hunting Agent")
    gr.Markdown("AI-powered job search — search, score fit, tailor resume, track applications.")

    with gr.Tabs():

        with gr.Tab("Chat"):
            chat_display = gr.Textbox(
                label="Conversation", lines=20, interactive=False,
                placeholder="Conversation will appear here..."
            )
            with gr.Row():
                msg = gr.Textbox(
                    placeholder="e.g. fetch jobs at recursion",
                    label="Message", scale=5
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)

            with gr.Row():
                btn_search = gr.Button("Search new grad AI 2026")
                btn_citadel = gr.Button("Fetch Citadel jobs")
                btn_recursion = gr.Button("Fetch Recursion jobs")
                btn_ramp = gr.Button("Fetch Ramp jobs (Lever)")

            tool_log_display = gr.Textbox(label="Tool Log", lines=6, interactive=False)

            send_btn.click(
                chat,
                [msg, chat_display, agent_history],
                [chat_display, agent_history, msg, tool_log_display]
            )
            msg.submit(
                chat,
                [msg, chat_display, agent_history],
                [chat_display, agent_history, msg, tool_log_display]
            )
            btn_search.click(
                lambda d, ah: chat("search for AI ML engineer new grad 2026", d, ah),
                [chat_display, agent_history],
                [chat_display, agent_history, msg, tool_log_display]
            )
            btn_citadel.click(
                lambda d, ah: chat("fetch jobs at citadel", d, ah),
                [chat_display, agent_history],
                [chat_display, agent_history, msg, tool_log_display]
            )
            btn_recursion.click(
                lambda d, ah: chat("fetch jobs at recursion", d, ah),
                [chat_display, agent_history],
                [chat_display, agent_history, msg, tool_log_display]
            )
            btn_ramp.click(
                lambda d, ah: chat("fetch jobs at ramp / lever", d, ah),
                [chat_display, agent_history],
                [chat_display, agent_history, msg, tool_log_display]
            )

        with gr.Tab("Quick Tools"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Search Jobs")
                    search_q = gr.Textbox(label="Query", placeholder="AI engineer biotech new grad 2026")
                    search_btn = gr.Button("Search", variant="primary")
                    search_out = gr.Textbox(label="Results", lines=12)
                    search_btn.click(quick_search, search_q, search_out)

                with gr.Column():
                    gr.Markdown("### Fetch Company ATS Jobs")
                    ats_slug = gr.Textbox(label="Company slug", placeholder="recursion, ramp, citadel")
                    ats_platform = gr.Radio(["greenhouse", "lever"], value="greenhouse", label="Platform")
                    ats_btn = gr.Button("Fetch", variant="primary")
                    ats_out = gr.Textbox(label="Results", lines=12)
                    ats_btn.click(quick_fetch, [ats_slug, ats_platform], ats_out)

            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Score Fit")
                    score_jd = gr.Textbox(label="Paste job description", lines=8)
                    score_btn = gr.Button("Score my fit", variant="primary")
                    score_out = gr.Textbox(label="Score + Gaps", lines=10)
                    score_btn.click(quick_score, score_jd, score_out)

                with gr.Column():
                    gr.Markdown("### Tailor Resume")
                    tailor_jd = gr.Textbox(label="Paste job description", lines=8)
                    tailor_btn = gr.Button("Tailor resume", variant="primary")
                    tailor_out = gr.Textbox(label="Tailored summary + bullets", lines=10)
                    tailor_btn.click(quick_tailor, tailor_jd, tailor_out)

        with gr.Tab("Application Tracker"):
            gr.Markdown("### Track Application")
            with gr.Row():
                t_company = gr.Textbox(label="Company", placeholder="SystImmune")
                t_role    = gr.Textbox(label="Role", placeholder="Applied AI Engineer I")
                t_status  = gr.Dropdown(
                    ["applied","phone_screen","interview","offer","rejected","withdrawn"],
                    value="applied", label="Status"
                )
                t_notes   = gr.Textbox(label="Notes")
            track_btn = gr.Button("Add / Update", variant="primary")
            track_out = gr.Textbox(label="Result", lines=2)
            gr.Markdown("### All Applications")
            tracker_out = gr.Textbox(label="", lines=15, interactive=False, value=get_tracker_text())
            track_btn.click(quick_track, [t_company, t_role, t_status, t_notes], [track_out, tracker_out])

        with gr.Tab("ATS Slugs"):
            gr.Markdown("""
### Greenhouse slugs
`recursion` `genentech` `citadel` `palantir` `openai` `anthropic` `twosigma` `deshaw`

### Lever slugs
`ramp` `stripe` `notion` `scale-ai` `tempus-ex` `jane-street`

> If a slug 404s, try with/without hyphens or switch platforms.
            """)

if __name__ == "__main__":
    demo.launch()