# BuildFindr — planning.md

> BuildFindr is Project 2 (the multi-tool agent) reskinned onto the Jetson domain
> from Project 1. It fulfills the FitFindr spec one-for-one: search a catalog →
> reason about a match against the user's own state → emit a shareable artifact.
> Instead of thrifted clothes and a wardrobe, it works over Jetson **projects** and
> the user's **parts bin (inventory)**, and it can optionally call Project 1's RAG
> to ground setup steps in already-ingested documentation.

---

## Tools

### Tool 1: search_projects

**What it does:** Searches the mock project catalog (`data/projects.json`) for Jetson builds whose keywords match the user's request, with optional difficulty and cost-ceiling filters. Pure Python — no network call.

**Input parameters:**
- `description` (str): keywords describing the desired project, e.g. `"object detection camera"`.
- `difficulty` (str | None): one of `"Easy"`, `"Moderate"`, `"Difficult"`, `"Expert"` (case-insensitive), or `None` to skip the filter.
- `max_cost` (float | None): inclusive USD ceiling on `est_cost`, or `None` to skip.

**What it returns:** A `list[dict]`, best match first. Each dict has `id`, `title`, `description`, `difficulty`, `components` (list), `est_cost` (float), `skill_tags` (list), `source_url`. Returns `[]` when nothing matches.

**What happens if it fails or returns nothing:** Never raises. On an empty result the agent first retries with the filters removed (see Planning Loop), and only then reports a no-match message.

---

### Tool 2: plan_build

**What it does:** Given a chosen project and the user's hardware inventory, asks the LLM to say which required components the user already has, which they still need to buy, and a realistic 4–6 step build approach.

**Input parameters:**
- `project` (dict): a project dict from `search_projects()`.
- `inventory` (dict): an inventory dict shaped `{"items": [...]}`. May be empty.

**What it returns:** A non-empty `str` (the build plan). If the inventory is empty it returns general getting-started guidance instead of a personalized gap analysis.

**What happens if it fails or returns nothing:** The empty-inventory case is handled inside the tool (general advice). A hard infrastructure failure (missing key, network) is caught by the planning loop, which sets `session["error"]` and stops before the build card.

---

### Tool 3: create_build_card

**What it does:** Turns a build plan into a short, shareable "build card" — the kind of caption a maker posts to LinkedIn or X when kicking off a build.

**Input parameters:**
- `plan` (str): the build-plan string from `plan_build()`.
- `project` (dict): the project dict (for title/cost/difficulty).

**What it returns:** A 2–4 sentence `str` caption. Uses a high temperature so repeated calls vary.

**What happens if it fails or returns nothing:** If `plan` is empty/whitespace it returns a descriptive error string (never raises) rather than captioning nothing.

---

### Additional Tools

### Tool 4: consult_docs (the bridge to Project 1)

**What it does:** Optionally queries Project 1's RAG (`rag.ask()`) to ground setup detail in the documentation already ingested for the Jetson Assistant. This is what makes BuildFindr an *advancement* of Project 1 rather than a separate app.

**Input parameters:**
- `question` (str): a natural-language setup question, built by the agent from the selected project's title.

**What it returns:** A `dict`: `{"answer": str, "sources": list, "available": bool, "grounded": bool}`. `available` is whether the RAG was reachable; `grounded` is whether it answered (vs. declined).

**What happens if it fails or returns nothing:** Fully graceful. If Project 1 isn't wired in (no `rag` module on the path), it returns `available=False` and the agent proceeds on the catalog alone. If the RAG is reachable but declines ("I don't have enough information on that"), `grounded=False` — a documented, non-fatal degradation.

---

## Planning Loop

The loop reads the **search result** to decide whether to keep going, and reads the **filters that were applied** to decide whether to retry:

1. Parse the query into `description`, `difficulty`, `max_cost` (regex + keyword rules, deterministic — no LLM).
2. Call `search_projects(description, difficulty, max_cost)`.
3. **If results is empty AND a difficulty or price filter was applied:** retry once as `search_projects(description, None, None)`, and append a human-readable note to `session["adjustments"]` describing what was dropped.
4. **If results is still empty:** set `session["error"]` to a "try broader keywords" message and `return` early. `plan_build` is **not** called on empty input.
5. Otherwise set `selected_project = results[0]` and store it (and the full result list) in the session.
6. Call `plan_build(selected_project, inventory)` → `session["build_plan"]`.
7. Call `consult_docs(...)` → `session["docs"]` (non-fatal; wrapped so it can never end the run).
8. Call `create_build_card(build_plan, selected_project)` → `session["build_card"]`.
9. Return the session.

The behavior therefore **differs by input**: an impossible query exits at step 4 with `build_card == None`; a real query runs all the way to step 8; a real query with over-tight filters takes the step-3 retry branch and records an adjustment.

---

## State Management

A single `session` dict (created by `_new_session`) is the source of truth for one interaction. Each tool's output is written back into it and read by the next step — nothing is re-entered or hardcoded between steps:

- `query` → raw input.
- `parsed` → `{description, difficulty, max_cost}` from step 1.
- `search_results` / `selected_project` → from `search_projects`; `selected_project` is the exact dict handed to `plan_build` **and** `create_build_card`.
- `inventory` → the wardrobe-equivalent, passed into `plan_build`.
- `build_plan` → output of `plan_build`, fed verbatim into `create_build_card`.
- `docs` → output of `consult_docs`.
- `build_card` → final shareable artifact.
- `adjustments` → notes about any loosened filters (surfaced in the UI).
- `error` → set on any early exit; the UI checks this first.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_projects | No project matches the query | Retry once with difficulty/price filters dropped and tell the user what was relaxed; if still empty, return a specific "try keywords like object detection / robot / camera / LiDAR" message and stop before `plan_build`. |
| plan_build | Inventory is empty | Tool itself returns general getting-started guidance (core parts to buy, skill level, first steps) instead of a gap analysis. |
| plan_build | LLM/network/key failure | Loop catches it, sets `session["error"]` ("found the project but couldn't generate a plan — check GROQ_API_KEY"), and stops. |
| create_build_card | Plan is empty/whitespace | Tool returns a descriptive error string; no exception, no fabricated caption. |
| consult_docs | Project 1 RAG not connected, or it declines | Returns `available=False` / `grounded=False`; the UI notes the plan came from the catalog and the run continues normally. |

---

## Architecture

```mermaid
flowchart TD
    Q[User query] --> P[Parse: description, difficulty, max_cost]
    P --> S[search_projects]
    S -->|results = []| R{filters applied?}
    R -->|yes| S2[retry: drop filters]
    R -->|no| ERR[ERROR: no match -> return]
    S2 -->|still empty| ERR
    S2 -->|found| SEL
    S -->|results found| SEL[Session: selected_project = results 0]
    SEL --> PB[plan_build selected_project, inventory]
    PB -->|infra error| ERR2[ERROR: plan failed -> return]
    PB --> ST[Session: build_plan]
    ST --> CD[consult_docs  - optional, non-fatal]
    CD --> DS[Session: docs]
    DS --> BC[create_build_card build_plan, selected_project]
    BC --> FC[Session: build_card]
    FC --> OUT[Return session]
    ERR --> OUT
    ERR2 --> OUT
```

State (the `session` dict) is threaded through every node; the two `ERROR` nodes are the early-exit branches that leave `build_card` as `None`.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:** Give Claude one tool spec block at a time from this file. For `search_projects`, hand it the Tool 1 block plus `utils/data_loader.load_projects()` and ask for keyword scoring + difficulty/price filters + the empty-list contract; verify it filters on all three params and returns `[]` (not an error) before trusting it. For `plan_build` and `create_build_card`, hand the Tool 2/3 blocks and require the empty-inventory and empty-plan branches respectively; test each in isolation with `python -c`. For `consult_docs`, give the Tool 4 block and stress that it must never raise when `rag` is missing.

**Milestone 4 — Planning loop and state management:** Give Claude this Planning Loop section, the State Management section, and the Mermaid diagram together, and ask it to implement `run_agent` matching the numbered branches — specifically the step-3 retry and the step-4 early return. Verify by running `python agent.py`: the happy path must populate `build_card`, and the no-results path must leave `build_card == None` with a message in `error`.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I want an object detection camera project under $200. I already have a Jetson Nano and a USB webcam."

**Step 1 — Parse:** `_parse_query` extracts `description="object detection camera project I already have a Jetson Nano and a USB webcam"`, `difficulty=None`, `max_cost=200.0`.

**Step 2 — Search:** `search_projects(description, None, 200.0)` filters to projects ≤ $200, scores by keyword overlap ("object", "detection", "camera"), and returns matches led by **Face Mask Detection with PyTorch and TensorRT ($150)** / **Safety Helmet Detection ($160)**. Top result is stored as `selected_project`.

**Step 3 — Plan build:** `plan_build(selected_project, example_inventory)` sees the user owns a Jetson Nano + camera, reports those cover the core needs, flags the microSD if missing, and lays out steps (flash JetPack → set up the detector repo → convert to TensorRT → run on the camera feed).

**Step 4 — Consult docs (optional):** `consult_docs("How do I set up and build the Face Mask Detection ... project on a Jetson?")`. If Project 1 is wired in, it returns grounded setup snippets and sources; if not, `available=False` and the UI notes the plan is catalog-only.

**Step 5 — Build card:** `create_build_card(build_plan, selected_project)` returns something like: *"Kicking off a real-time face-mask detector on my Jetson Nano this weekend — ~$150 of parts and a TensorRT pipeline doing the heavy lifting. Camera's already wired; let's see how many FPS I can squeeze out."*

**Final output to user:** Four panels — the selected project (with cost, parts, and a link to the original), the personalized build plan, the docs grounding (or a note that it was catalog-only), and the shareable build card.
