"""
agent.py

The BuildFindr planning loop. Orchestrates the four tools in response to a
natural-language query, passing state between them via a session dict.

Usage:
    from agent import run_agent
    from utils.data_loader import get_example_inventory

    result = run_agent(
        query="object detection camera project under $200",
        inventory=get_example_inventory(),
    )
    print(result["build_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_projects, plan_build, create_build_card, consult_docs


# -- session state -------------------------------------------------------------

def _new_session(query: str, inventory: dict) -> dict:
    """Initialize a fresh session dict for one user interaction."""
    return {
        "query": query,             # original user query
        "parsed": {},               # extracted description / difficulty / max_cost
        "search_results": [],       # list of matching project dicts
        "selected_project": None,   # top result, passed into plan_build
        "inventory": inventory,     # user's hardware inventory dict
        "build_plan": None,         # string returned by plan_build
        "docs": None,               # dict returned by consult_docs (optional)
        "build_card": None,         # string returned by create_build_card
        "adjustments": [],          # notes about any filters we loosened
        "error": None,              # set if the interaction ended early
    }


# -- query parsing -------------------------------------------------------------

_DIFFICULTY_KEYWORDS = [
    (("expert",), "Expert"),
    (("advanced", "difficult", "hard", "challenging"), "Difficult"),
    (("moderate", "intermediate"), "Moderate"),
    (("easy", "simple", "beginner", "starter"), "Easy"),
]


def _parse_query(query: str) -> dict:
    """
    Pull a description, difficulty, and max_cost out of a free-text query using
    simple regex/keyword rules (deterministic -- no LLM needed for parsing).
    """
    text = query or ""
    low = text.lower()

    # max_cost: "$200", "under 200", "below $150", "up to 50 dollars"
    max_cost = None
    m = re.search(r"\$\s*(\d+(?:\.\d+)?)", low)
    if not m:
        m = re.search(
            r"(?:under|below|less than|max|up to|cheaper than)\s*\$?\s*(\d+(?:\.\d+)?)",
            low,
        )
    if m:
        max_cost = float(m.group(1))

    # difficulty: first keyword group that appears wins
    difficulty = None
    for words, label in _DIFFICULTY_KEYWORDS:
        if any(re.search(rf"\b{w}\b", low) for w in words):
            difficulty = label
            break

    # description: strip the price phrase so it doesn't pollute keyword scoring
    description = re.sub(
        r"(?:under|below|less than|max|up to|cheaper than)?\s*\$?\s*\d+(?:\.\d+)?\s*(?:dollars|usd|bucks)?",
        " ",
        text,
        flags=re.I,
    )
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description, "difficulty": difficulty, "max_cost": max_cost}


# -- planning loop -------------------------------------------------------------

def run_agent(query: str, inventory: dict) -> dict:
    """
    Run the BuildFindr planning loop for a single interaction.

    Branching logic:
      1. Parse the query into description / difficulty / max_cost.
      2. search_projects(...). If it returns nothing AND a filter was applied,
         retry once with the filters removed (and record the adjustment). If it
         is still empty, set session["error"] and return early.
      3. selected_project = results[0].
      4. plan_build(selected_project, inventory) -> build_plan.
      5. consult_docs(...) to (optionally) ground setup detail from Project 1.
         Non-fatal: failure just leaves docs marked unavailable.
      6. create_build_card(build_plan, selected_project) -> build_card.
      7. Return the session.

    Returns the session dict. Check session["error"] first -- if it is not None,
    the run ended early and build_plan / build_card will be None.
    """
    session = _new_session(query, inventory)

    if not query or not query.strip():
        session["error"] = "Please describe the kind of Jetson project you want to build."
        return session

    parsed = _parse_query(query)
    session["parsed"] = parsed

    # Step 1: search (infra errors handled here so a bad call can't crash the app).
    try:
        results = search_projects(
            parsed["description"], parsed["difficulty"], parsed["max_cost"]
        )
    except Exception as e:
        session["error"] = f"Search failed unexpectedly ({type(e).__name__}). Please try again."
        return session

    # Step 2: retry-with-loosened-constraints fallback.
    if not results:
        had_filters = parsed["difficulty"] is not None or parsed["max_cost"] is not None
        if had_filters:
            try:
                loosened = search_projects(parsed["description"], None, None)
            except Exception:
                loosened = []
            if loosened:
                dropped = []
                if parsed["difficulty"] is not None:
                    dropped.append(f"difficulty '{parsed['difficulty']}'")
                if parsed["max_cost"] is not None:
                    dropped.append(f"the ${parsed['max_cost']:.0f} budget cap")
                session["adjustments"].append(
                    "No exact match, so I dropped " + " and ".join(dropped)
                    + " and searched on your keywords alone."
                )
                results = loosened

    if not results:
        desc = parsed["description"] or "that"
        session["error"] = (
            f"I couldn't find a Jetson project matching '{desc}'. "
            "Try broader keywords like 'object detection', 'robot', 'camera', or 'LiDAR'."
        )
        return session

    # Step 3: select the top result and store it in session state.
    selected = results[0]
    session["search_results"] = results
    session["selected_project"] = selected

    # Step 4: plan the build against the user's inventory.
    try:
        session["build_plan"] = plan_build(selected, session["inventory"])
    except Exception as e:
        session["error"] = (
            f"I found '{selected['title']}' but couldn't generate a build plan "
            f"({type(e).__name__}). Check your GROQ_API_KEY and try again."
        )
        return session

    # Step 5: (optional) ground setup detail in the Project 1 knowledge base.
    try:
        session["docs"] = consult_docs(
            f"How do I set up and build the {selected['title']} project on a Jetson?"
        )
    except Exception:
        session["docs"] = None  # never fatal

    # Step 6: turn the plan into a shareable build card.
    try:
        session["build_card"] = create_build_card(session["build_plan"], selected)
    except Exception as e:
        session["error"] = (
            f"The build plan is ready but the build card failed ({type(e).__name__})."
        )
        return session

    return session


# -- CLI test ------------------------------------------------------------------

if __name__ == "__main__":
    from utils.data_loader import get_example_inventory, get_empty_inventory

    print("=== Happy path: object detection camera ===\n")
    s = run_agent(
        query="object detection camera project under $200",
        inventory=get_example_inventory(),
    )
    if s["error"]:
        print(f"Error: {s['error']}")
    else:
        print(f"Selected: {s['selected_project']['title']}")
        if s["adjustments"]:
            print(f"Adjustments: {s['adjustments']}")
        print(f"\nBuild plan:\n{s['build_plan']}")
        print(f"\nBuild card:\n{s['build_card']}")

    print("\n\n=== No-results path ===\n")
    s2 = run_agent(
        query="underwater sonar submarine drone under $20",
        inventory=get_example_inventory(),
    )
    print(f"Error message: {s2['error']}")
    print(f"build_card is None: {s2['build_card'] is None}")
