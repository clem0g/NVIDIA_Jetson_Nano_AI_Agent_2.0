"""
app.py

Gradio interface for BuildFindr. handle_query() calls run_agent() and maps the
session dict to the output panels.

Run with:
    python app.py
Then open the localhost URL shown in your terminal (usually http://localhost:7860).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_inventory, get_empty_inventory

# Styling carried over from the Jetson Assistant (Project 1) so the two tools
# read as one product.
NVIDIA_CSS = """
:root {
  --bg: #0b0f19; --card: #151a27; --ink: #e0e0e0; --muted: #8b949e;
  --accent: #76b900; --accent-hi: #8cf000; --accent-glow: rgba(118, 185, 0, 0.4);
  --line: #2d3748;
}
* { box-sizing: border-box; }
body, .gradio-container {
  background: var(--bg) !important; color: var(--ink) !important;
  font-family: 'Inter', 'Segoe UI', Roboto, Helvetica, sans-serif !important;
  -webkit-font-smoothing: antialiased;
}
.gradio-container { max-width: 860px !important; margin: 0 auto !important; padding: 48px 20px 72px !important; }
footer { display: none !important; }
#title {
  text-align: center; font-size: 40px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 10px;
  background: linear-gradient(90deg, #ffffff, var(--accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
#subtitle { text-align: center; color: var(--muted); font-size: 16px; line-height: 1.5; margin: 0 0 36px; }
#q-input textarea, #q-input input {
  background: #000000 !important; color: #ffffff !important;
  border: 1px solid var(--line) !important; border-radius: 22px !important;
  padding: 16px 22px !important; font-size: 16px !important;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4) !important;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
}
#q-input textarea:focus, #q-input input:focus {
  border-color: var(--accent) !important; outline: none !important;
  box-shadow: 0 0 25px var(--accent-glow), inset 0 0 10px rgba(118, 185, 0, 0.1) !important;
}
#ask-row { justify-content: center; margin-top: 18px; }
#ask-btn {
  background: var(--accent) !important; color: #000000 !important; border: none !important;
  border-radius: 22px !important; padding: 13px 34px !important; font-size: 16px !important;
  font-weight: 600 !important; min-width: 150px; box-shadow: 0 0 15px var(--accent-glow) !important;
  transition: all 0.2s ease !important; cursor: pointer;
}
#ask-btn:hover { background: var(--accent-hi) !important; box-shadow: 0 0 25px var(--accent-glow) !important; transform: translateY(-2px); }
.card {
  background: var(--card) !important; border: 1px solid var(--line) !important; border-radius: 18px !important;
  padding: 22px 28px !important; margin-top: 22px !important; box-shadow: 0 10px 30px rgba(0,0,0,0.5) !important;
}
.card h3 { margin: 0 0 14px; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em; color: var(--accent); }
#project-md, #plan-md, #card-md, #docs-md { font-size: 15px; line-height: 1.65; }
#card-md { font-style: italic; color: #d7ffb0; }
#project-md a, #docs-md a { color: var(--accent); text-decoration: none; }
#project-md a:hover, #docs-md a:hover { color: var(--accent-hi); text-decoration: underline; }
#project-md code { color: #a5d6ff; }
"""

SUBTITLE = ("Describe a Jetson project — include a budget or difficulty if you want to filter.<br>"
            "BuildFindr finds a match, plans it against your parts bin, and writes you a build card.")
PLACEHOLDER = "e.g. object detection camera project under $200"

EXAMPLE_QUERIES = [
    "object detection camera project under $200",
    "beginner security camera under $150",
    "lidar robot mapping with ROS",
    "generative AI project",
    "underwater sonar submarine drone under $20",  # deliberate no-results test
]


def _format_project(p: dict) -> str:
    comps = ", ".join(p.get("components", [])) or "n/a"
    tags = ", ".join(p.get("skill_tags", [])) or "n/a"
    return (
        f"### {p['title']}\n"
        f"**Difficulty:** {p['difficulty']}  ·  **Est. cost:** ${p['est_cost']:.0f}\n\n"
        f"{p['description']}\n\n"
        f"**Needs:** {comps}\n\n"
        f"**Tags:** {tags}\n\n"
        f"[View the original project ↗]({p['source_url']})"
    )


def _format_docs(docs: dict) -> str:
    if not docs:
        return "_Knowledge-base grounding wasn't run for this query._"
    if docs.get("available") and docs.get("grounded"):
        body = docs.get("answer", "").strip()
        srcs = docs.get("sources") or []
        if srcs:
            lines = "\n".join(
                (f"- [{s['source']}]({s['url']})" if s.get("url") else f"- {s['source']}")
                for s in srcs
            )
            body += "\n\n**From your ingested docs:**\n" + lines
        return body
    if docs.get("available") and not docs.get("grounded"):
        return ("_Your Jetson Assistant docs didn't have specifics on this build, "
                "so the plan above comes from the catalog._")
    return ("_Connect your Jetson Assistant knowledge base (set `JETSON_ASSISTANT_PATH`) "
            "to ground setup steps in your ingested documentation._")


def handle_query(user_query: str, inventory_choice: str):
    """Return (project_md, plan_md, docs_md, card_md) for the four panels."""
    user_query = (user_query or "").strip()
    if not user_query:
        return ("Type a project idea above — for example, *lidar robot mapping with ROS*.",
                "", "", "")

    inventory = (get_empty_inventory()
                 if inventory_choice.startswith("Empty")
                 else get_example_inventory())

    session = run_agent(user_query, inventory)

    if session["error"]:
        return (f"⚠️ {session['error']}", "", "", "")

    project_md = _format_project(session["selected_project"])
    if session["adjustments"]:
        project_md = "> " + " ".join(session["adjustments"]) + "\n\n" + project_md

    plan_md = session["build_plan"] or ""
    docs_md = _format_docs(session["docs"])
    card_md = session["build_card"] or ""
    return project_md, plan_md, docs_md, card_md


def build_interface():
    with gr.Blocks(css=NVIDIA_CSS, title="BuildFindr", theme=gr.themes.Base()) as demo:
        gr.Markdown("# BuildFindr", elem_id="title")
        gr.Markdown(SUBTITLE, elem_id="subtitle")

        q = gr.Textbox(label="", placeholder=PLACEHOLDER, lines=1, elem_id="q-input")
        inv = gr.Radio(
            choices=["Example parts bin", "Empty parts bin (new maker)"],
            value="Example parts bin",
            label="Your hardware",
        )
        with gr.Row(elem_id="ask-row"):
            btn = gr.Button("Find a build", elem_id="ask-btn")

        with gr.Group(elem_classes="card"):
            gr.Markdown("### Top project found")
            project = gr.Markdown(elem_id="project-md")
        with gr.Group(elem_classes="card"):
            gr.Markdown("### Your build plan")
            plan = gr.Markdown(elem_id="plan-md")
        with gr.Group(elem_classes="card"):
            gr.Markdown("### Setup notes from your docs")
            docs = gr.Markdown(elem_id="docs-md")
        with gr.Group(elem_classes="card"):
            gr.Markdown("### Pontential LinkedIn Post")
            card = gr.Markdown(elem_id="card-md")

        gr.Examples(examples=EXAMPLE_QUERIES, inputs=q, label="Try these")

        outputs = [project, plan, docs, card]
        btn.click(handle_query, inputs=[q, inv], outputs=outputs)
        q.submit(handle_query, inputs=[q, inv], outputs=outputs)

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
