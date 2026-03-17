"""
Job Hunting Agent — Gradio frontend (Gradio 6 compatible)
Run: python app.py
"""

import os
import json
import gradio as gr
from dotenv import load_dotenv
from job_agent import (
    run_agent, view_applications,
    search_jobs, fetch_ats_jobs,
    track_application, TOOL_FN_MAP
)

load_dotenv()

MEMORY_WINDOW = 10
CHAT_LOG_PATH = "chat_log.json"


def save_chat_log(history_display):
    with open(CHAT_LOG_PATH, "w") as f:
        json.dump({"display": history_display}, f)


def load_chat_log():
    if os.path.exists(CHAT_LOG_PATH):
        try:
            with open(CHAT_LOG_PATH) as f:
                return json.load(f).get("display", "")
        except Exception:
            return ""
    return ""


def trim_history(history):
    if len(history) > MEMORY_WINDOW:
        history = history[-MEMORY_WINDOW:]
        while history and not (
            isinstance(history[0].get("content"), str) and
            history[0].get("role") == "user"
        ):
            history = history[1:]
    return history


def get_tracker_text():
    return view_applications("all")


def chat(user_message, history_display, agent_history):
    if not user_message.strip():
        return history_display, agent_history, "", "", get_tracker_text()

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

    history_display = (history_display + f"\n\nYou: {user_message}\n\nAgent: {answer}").strip()
    # chat is intentionally not persisted across refreshes

    tool_display = "\n\n---\n\n".join(tool_log) if tool_log else "No tools called"
    return history_display, agent_history, "", tool_display, get_tracker_text()


def clear_chat():
    if os.path.exists(CHAT_LOG_PATH):
        os.remove(CHAT_LOG_PATH)
    return "", [], "", "", get_tracker_text()


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
                    placeholder="e.g. fetch jobs at anthropic / write a cover letter for ramp software engineer",
                    label="Message", scale=5
                )
                send_btn  = gr.Button("Send", variant="primary", scale=1)
                clear_btn = gr.Button("Clear", scale=1)

            with gr.Row():
                btn_search    = gr.Button("Search new grad AI 2026")
                btn_citadel   = gr.Button("Fetch Citadel jobs")
                btn_recursion = gr.Button("Fetch Recursion jobs")
                btn_ramp      = gr.Button("Fetch Ramp jobs (Lever)")

            tool_log_display = gr.Textbox(label="Tool Log", lines=6, interactive=False)

        with gr.Tab("Application Tracker"):
            gr.Markdown("### Track Application")
            with gr.Row():
                t_company = gr.Textbox(label="Company", placeholder="SystImmune")
                t_role    = gr.Textbox(label="Role",    placeholder="Applied AI Engineer I")
                t_status  = gr.Dropdown(
                    ["applied","phone_screen","interview","offer","rejected","withdrawn"],
                    value="applied", label="Status"
                )
                t_notes = gr.Textbox(label="Notes")
            track_btn = gr.Button("Add / Update", variant="primary")
            track_out = gr.Textbox(label="Result", lines=2)
            gr.Markdown("### All Applications")
            tracker_out = gr.Textbox(label="", lines=15, interactive=False)
            track_btn.click(quick_track, [t_company, t_role, t_status, t_notes], [track_out, tracker_out])

        with gr.Tab("ATS Slugs"):
            gr.Markdown("""
### Greenhouse slugs
`recursionpharmaceuticals` `genentech` `citadel` `palantir` `openai` `anthropic` `stripe` `twosigma` `deshaw`

### Lever slugs
`ramp` `notion` `scale-ai` `tempus-ex` `jane-street`

> If a slug 404s, the tool auto-retries known aliases then suggests the other platform.
            """)

    # Wire chat events after tracker_out is defined
    chat_outputs = [chat_display, agent_history, msg, tool_log_display, tracker_out]

    send_btn.click(chat, [msg, chat_display, agent_history], chat_outputs)
    msg.submit(chat,     [msg, chat_display, agent_history], chat_outputs)
    clear_btn.click(clear_chat, [], chat_outputs)

    btn_search.click(
        lambda d, ah: chat("search for AI ML engineer new grad 2026", d, ah),
        [chat_display, agent_history], chat_outputs
    )
    btn_citadel.click(
        lambda d, ah: chat("fetch jobs at citadel", d, ah),
        [chat_display, agent_history], chat_outputs
    )
    btn_recursion.click(
        lambda d, ah: chat("fetch jobs at recursionpharmaceuticals", d, ah),
        [chat_display, agent_history], chat_outputs
    )
    btn_ramp.click(
        lambda d, ah: chat("fetch jobs at ramp / lever", d, ah),
        [chat_display, agent_history], chat_outputs
    )

    # chat clears on refresh — no load
    demo.load(get_tracker_text, outputs=tracker_out)


if __name__ == "__main__":
    demo.launch()