# BuildFindr — a multi-tool Jetson build agent

BuildFindr is Project 2 (the multi-tool agent) built as an **advancement of Project 1**, my Jetson Assistant RAG chatbot. It fulfills the FitFindr spec one-for-one — search a catalog, reason about a match against the user's own state, emit a shareable artifact — but over the NVIDIA Jetson domain instead of thrifted clothing:

| FitFindr | BuildFindr |
|---|---|
| `listings.json` | `data/projects.json` (24 Jetson projects) |
| user's wardrobe | user's **parts bin** (`data/inventory_schema.json`) |
| `search_listings` | `search_projects` |
| `suggest_outfit` | `plan_build` |
| `create_fit_card` | `create_build_card` |
| — | `consult_docs` → calls Project 1's RAG (the bridge) |

Given a query like *"object detection camera project under $200"*, BuildFindr finds a matching project, plans it against the hardware you already own, optionally grounds the setup steps in the docs ingested by Project 1, and writes a shareable build card.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your Groq key (same key as Project 1)
```

```bash
python utils/data_loader.py        # sanity-check the data loads
pytest tests/                      # all tests pass (LLM tests auto-skip without a key)
python agent.py                    # CLI: happy path + no-results path
python app.py                      # web UI at the URL shown in the terminal
```

## Tool Inventory

**`search_projects(description: str, difficulty: str | None = None, max_cost: float | None = None) -> list[dict]`**
Filters `data/projects.json` by optional difficulty and cost ceiling, then scores by keyword overlap against each project's title, description, tags, and components. Returns project dicts (`id`, `title`, `description`, `difficulty`, `components`, `est_cost`, `skill_tags`, `source_url`), best match first; `[]` if nothing matches. Pure Python, no network.

**`plan_build(project: dict, inventory: dict) -> str`**
Asks Groq's `llama-3.3-70b-versatile` which of the project's components the user already owns, what they still need to buy, and a 4–6 step build approach. Returns the plan as a string; returns general getting-started advice when the inventory is empty.

**`create_build_card(plan: str, project: dict) -> str`**
Turns the plan into a 2–4 sentence shareable caption (high temperature, so it varies per call). Returns a descriptive error string if `plan` is empty.

**`consult_docs(question: str) -> dict`**
Optional bridge to Project 1. Returns `{"answer": str, "sources": list, "available": bool, "grounded": bool}` from `rag.ask()` when the Jetson Assistant repo is on the path; otherwise degrades gracefully.

## How the Planning Loop Works

`run_agent(query, inventory)` is not a fixed pipeline — it branches on what each step returns:

1. Parse the query into `description` / `difficulty` / `max_cost` with regex + keyword rules (deterministic, no LLM).
2. Call `search_projects`.
3. **If the result is empty and a difficulty or price filter was applied,** retry once with the filters removed and record a note in `session["adjustments"]`.
4. **If it is still empty,** set `session["error"]` and return early — `plan_build` is never called on empty input.
5. Otherwise `selected_project = results[0]`.
6. `plan_build(selected_project, inventory)` → `build_plan`.
7. `consult_docs(...)` → `docs` (non-fatal).
8. `create_build_card(build_plan, selected_project)` → `build_card`.

Different inputs take different paths: an impossible query exits at step 4 with `build_card == None`; an over-filtered query takes the step-3 retry; a normal query runs all eight steps.

## State Management

A single `session` dict created by `_new_session` is the source of truth. Each tool writes its output back into the session, and the next step reads it — there is no re-entry and no hardcoding between steps. `selected_project` set in step 5 is the exact dict passed to both `plan_build` and `create_build_card`; `build_plan` from step 6 is fed verbatim into step 8. `adjustments` and `error` drive what the UI shows.

## Error Handling (per tool)

- **search_projects — no match:** retry with filters dropped, then a specific keyword-suggestion message; the agent stops before `plan_build`.
- **plan_build — empty inventory:** the tool returns general getting-started guidance instead of a gap analysis.
- **plan_build / create_build_card — API or key failure:** caught by the loop, which sets `session["error"]` and stops cleanly.
- **create_build_card — empty plan:** returns a descriptive error string, no exception.
- **consult_docs — Project 1 not connected or it declines:** returns `available`/`grounded` `False`; the UI notes the plan is catalog-only and the run continues.

**Concrete example (from testing):**

```bash
python -c "from tools import search_projects; print(search_projects('underwater sonar submarine', None, 5))"
# []   -> empty list, no exception

python -c "from agent import run_agent; from utils.data_loader import get_example_inventory; s = run_agent('underwater sonar submarine drone under \$20', get_example_inventory()); print(s['error']); print('card:', s['build_card'])"
# I couldn't find a Jetson project matching '...'. Try broader keywords like 'object detection', 'robot', 'camera', or 'LiDAR'.
# card: None
```

The agent communicated the failure and did **not** call `plan_build` or `create_build_card` on empty input.

## The Bridge to Project 1 (advancement)

BuildFindr is designed as an advancement of Project 1. The `consult_docs` tool calls `rag.ask()` from the Jetson Assistant to ground setup steps in the ingested documentation, surfacing source-linked snippets in the "Setup notes from your docs" panel.

**Current status:** The bridge connects successfully (Project 1's RAG is reachable and `rag.py` loads correctly), but the retrieval step is slow and the RAG currently returns declined responses for most project-specific queries. This is a known limitation of the Project 1 knowledge base — the ingested chunks are sparse on the specific build steps BuildFindr queries for, and the `RELEVANCE_CUTOFF` gate in `retrieve.py` filters them out. The fix is to run `ingest_electromaker.py` (included in this repo) to bulk-ingest the full build write-ups from all 34 Electromaker project pages, then re-chunk and re-index.

Until that is done, `consult_docs` degrades gracefully: it returns `available=False`, the "Setup notes" panel displays a catalog-only note, and the rest of the agent (project match, build plan, build card) runs normally without interruption. The `consult_docs` tool is intentionally non-fatal — no failure mode in it can stop a run.

To enable full grounding once the knowledge base is expanded:
1. Drop `ingest_electromaker.py` into your Project 1 repo root and run it.
2. Re-index: `python pipeline.py chunk` then `python index.py`.
3. Set `JETSON_ASSISTANT_PATH` and `JETSON_ASSISTANT_PYTHON` in `.env` to point at Project 1.

## Spec Reflection

**One way the spec helped:** The FitFindr tool contract (three fixed signatures + a planning loop that branches on results) gave me an exact skeleton to map the Jetson domain onto. Because the shape was fixed, I could reskin `listings→projects` and `wardrobe→inventory` without redesigning the agent, and the grader still sees the structure it expects.

**One way the implementation diverged:** I added a fourth tool, `consult_docs`, that the base spec doesn't require, specifically to tie Project 2 back to Project 1. Rather than make it a hard dependency, I implemented it as an optional, gracefully-degrading bridge so the project still satisfies the standalone requirements while doubling as the "advancement."

## AI Usage

**Instance 1 — the tools.** I gave Claude the Tool 1–4 spec blocks from `planning.md` plus the `data_loader` function names and asked it to implement `tools.py` one tool at a time. It produced keyword-overlap scoring for `search_projects` and the two LLM prompts. I overrode two things: I tightened `search_projects` so a filter-only query (no keywords) still returns matches instead of an empty list, and I added a shared `_chat` helper plus a stopword set (including `"jetson"`/`"nano"`, since every project contains those words and they were drowning out real keyword signal).

**Instance 2 — the planning loop and the bridge.** I gave Claude the Planning Loop + State Management sections and the Mermaid diagram and asked it to implement `run_agent` with the step-3 retry and step-4 early return. I changed the error-handling split: instead of letting the LLM tools raise, I made each tool own its *domain* failure mode internally (empty inventory, empty plan, no results) and had the loop wrap calls in `try/except` only for *infrastructure* errors (missing key, network). I also wrote `consult_docs` to read `JETSON_ASSISTANT_PATH` and `sys.path`-insert it so wiring Project 1 in is a one-line `.env` change rather than a code edit.
