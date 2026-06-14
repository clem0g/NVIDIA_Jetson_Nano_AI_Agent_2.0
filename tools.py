"""
tools.py

The BuildFindr tools. Each is a standalone function you can call and test in
isolation before wiring it into the agent loop (see agent.py).

Tools:
    search_projects(description, difficulty, max_cost) -> list[dict]
    plan_build(project, inventory)                     -> str
    create_build_card(plan, project)                   -> str
    consult_docs(question)                             -> dict   (optional bolt-on)

search_projects is pure Python over data/projects.json (no network).
plan_build and create_build_card call Groq's llama-3.3-70b-versatile.
consult_docs is the bridge to Project 1 (the Jetson Assistant RAG): if that
project's `rag` module is importable it returns a grounded answer; otherwise it
degrades gracefully so this repo still runs standalone.
"""

import os
import re

from dotenv import load_dotenv
load_dotenv()

MODEL = "llama-3.3-70b-versatile"

# Words we never want to treat as search keywords.
_STOPWORDS = {
    "a", "an", "and", "the", "for", "with", "without", "to", "of", "on", "in",
    "my", "me", "i", "want", "need", "looking", "build", "project", "projects",
    "that", "this", "can", "do", "is", "are", "under", "below", "less", "than",
    "max", "up", "over", "using", "use", "something", "make", "made", "get",
    "easy", "simple", "beginner", "starter", "moderate", "intermediate",
    "advanced", "difficult", "hard", "challenging", "expert", "jetson", "nano",
}


# -- Groq client ---------------------------------------------------------------

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(messages, temperature, max_tokens=700):
    """Single-shot chat completion helper."""
    client = _get_groq_client()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def _tokenize(text: str) -> set:
    """Lowercase word tokens, stopwords removed, very short tokens dropped."""
    words = re.findall(r"[a-z0-9+]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


# -- Tool 1: search_projects ---------------------------------------------------

def search_projects(
    description: str,
    difficulty: str | None = None,
    max_cost: float | None = None,
) -> list[dict]:
    """
    Search the mock project catalog for builds matching the description, with
    optional difficulty and cost-ceiling filters.

    Args:
        description: Keywords describing the kind of project the user wants
                     (e.g. "object detection camera").
        difficulty:  One of "Easy", "Moderate", "Difficult", "Expert"
                     (case-insensitive), or None to skip the difficulty filter.
        max_cost:    Maximum estimated cost in USD (inclusive), or None to skip.

    Returns:
        A list of matching project dicts, best match first. Empty list if
        nothing matches -- never raises.

    Each project dict has:
        id, title, description, difficulty, components (list),
        est_cost (float), skill_tags (list), source_url
    """
    from utils.data_loader import load_projects

    projects = load_projects()

    # 1. Hard filters.
    if difficulty:
        d = difficulty.strip().lower()
        projects = [p for p in projects if p["difficulty"].lower() == d]
    if max_cost is not None:
        projects = [p for p in projects if p["est_cost"] <= max_cost]

    # 2. Keyword scoring over title + description + tags + components.
    query_tokens = _tokenize(description)
    scored = []
    for p in projects:
        haystack = " ".join([
            p["title"],
            p["description"],
            " ".join(p.get("skill_tags", [])),
            " ".join(p.get("components", [])),
        ])
        hay_tokens = _tokenize(haystack)
        # If the user gave no usable keywords, keep everything that passed the
        # filters (score 1) so difficulty/price-only queries still return.
        score = len(query_tokens & hay_tokens) if query_tokens else 1
        if score > 0:
            scored.append((score, p))

    # 3. Sort by score desc, then cheaper first as a tiebreak.
    scored.sort(key=lambda sp: (-sp[0], sp[1]["est_cost"]))
    return [p for _, p in scored]


# -- Tool 2: plan_build --------------------------------------------------------

def plan_build(project: dict, inventory: dict) -> str:
    """
    Given a chosen project and the user's hardware inventory, explain what they
    can build now, what they still need to buy, and a realistic build approach.

    Args:
        project:   A project dict from search_projects().
        inventory: An inventory dict ({'items': [...]}). May be empty -- handled.

    Returns:
        A non-empty string. If the inventory is empty, returns general getting-
        started guidance instead of a personalized gap analysis.
    """
    if not project:
        return "No project was provided, so there is nothing to plan a build for."

    title = project.get("title", "this project")
    difficulty = project.get("difficulty", "unknown")
    est_cost = project.get("est_cost", "unknown")
    components = project.get("components", [])
    comp_list = ", ".join(components) if components else "not specified"

    items = (inventory or {}).get("items", [])

    if not items:
        prompt = (
            f"A maker wants to build this NVIDIA Jetson project:\n"
            f"  Title: {title}\n"
            f"  Difficulty: {difficulty}\n"
            f"  Estimated cost: ${est_cost}\n"
            f"  Components it needs: {comp_list}\n\n"
            "They have NOT entered any hardware yet. Give friendly getting-started "
            "guidance: the core parts they'd need to buy first, roughly what skill "
            "level to expect, and 3-5 concrete first steps. Keep it under 180 words. "
            "Do not invent exact prices."
        )
    else:
        owned = "\n".join(
            f"  - {it.get('name', 'unknown')}"
            f"{(' (' + it['specs'] + ')') if it.get('specs') else ''}"
            for it in items
        )
        prompt = (
            f"A maker wants to build this NVIDIA Jetson project:\n"
            f"  Title: {title}\n"
            f"  Difficulty: {difficulty}\n"
            f"  Estimated cost: ${est_cost}\n"
            f"  Components it needs: {comp_list}\n\n"
            f"Here is the hardware they ALREADY own:\n{owned}\n\n"
            "Write a short, practical build plan that:\n"
            "1. Names which needed components they can cover with what they own "
            "(match generously -- e.g. a USB webcam can stand in for a camera).\n"
            "2. Lists what they still need to buy.\n"
            "3. Gives 4-6 concrete build steps in order.\n"
            "4. Ends with a one-line difficulty/time reality check.\n"
            "Keep it under 220 words. Do not invent exact prices."
        )

    messages = [
        {"role": "system", "content": "You are a concise, encouraging NVIDIA Jetson "
                                      "build mentor. You are practical and never invent "
                                      "specs or prices that weren't given to you."},
        {"role": "user", "content": prompt},
    ]
    return _chat(messages, temperature=0.4, max_tokens=600)


# -- Tool 3: create_build_card -------------------------------------------------

def create_build_card(plan: str, project: dict) -> str:
    """
    Generate a short, shareable "build card" caption for a Jetson project -- the
    kind of thing someone would post on LinkedIn or X when they kick off a build.

    Args:
        plan:    The build-plan string from plan_build().
        project: The project dict.

    Returns:
        A 2-4 sentence caption string. If `plan` is empty or whitespace, returns
        a descriptive error message string (never raises).
    """
    if not plan or not plan.strip():
        return ("\u26a0\ufe0f I can't create a build card without a build plan. "
                "Run plan_build first to generate one.")

    title = project.get("title", "a Jetson project")
    est_cost = project.get("est_cost", "")
    difficulty = project.get("difficulty", "")

    prompt = (
        f"Project: {title}\n"
        f"Difficulty: {difficulty}\n"
        f"Estimated cost: ${est_cost}\n"
        f"Build plan:\n{plan}\n\n"
        "Write a short, authentic social-media caption (2-4 sentences) announcing "
        "that you're starting this build. It should:\n"
        "- sound like a real maker posting, not a product description\n"
        "- mention the project name, the rough cost, and that it runs on a Jetson, "
        "naturally and only once each\n"
        "- capture the vibe in specific terms\n"
        "- be fresh and a little different each time\n"
        "Return only the caption text."
    )
    messages = [
        {"role": "system", "content": "You write punchy, genuine maker captions for "
                                      "social media. No hashtag spam, no corporate tone."},
        {"role": "user", "content": prompt},
    ]
    # Higher temperature so repeated calls on the same input vary.
    return _chat(messages, temperature=0.95, max_tokens=220)


# -- Tool 4 (bolt-on): consult_docs --------------------------------------------

def consult_docs(question: str) -> dict:
    """
    Optional bridge to Project 1 (the Jetson Assistant RAG). If that project's
    `rag` module is importable, return a grounded answer from the ingested
    documentation. Otherwise degrade gracefully -- this repo still runs alone.

    To enable it, set the JETSON_ASSISTANT_PATH environment variable to the path
    of your Project 1 repo (the folder containing rag.py), or run BuildFindr from
    inside that repo.

    Returns a dict:
        {
          "answer": str,
          "sources": list,
          "available": bool,   # was the RAG reachable at all?
          "grounded": bool,    # did it actually answer (vs. decline)?
        }
    """
    unavailable = {
        "answer": ("The Jetson Assistant knowledge base isn't connected, so this "
                   "plan is based on the project catalog alone."),
        "sources": [],
        "available": False,
        "grounded": False,
    }
    if not question or not question.strip():
        return unavailable

    try:
        import sys
        kb_path = os.environ.get("JETSON_ASSISTANT_PATH")
        if kb_path and kb_path not in sys.path:
            sys.path.insert(0, kb_path)
        from rag import ask  # Project 1 module
    except Exception:
        return unavailable

    try:
        out = ask(question)
    except Exception as e:
        return {
            **unavailable,
            "answer": (f"The knowledge base is connected but the lookup failed "
                       f"({type(e).__name__}). This plan is from the catalog."),
        }

    return {
        "answer": out.get("answer", ""),
        "sources": out.get("sources", []),
        "available": True,
        "grounded": not out.get("declined", False),
    }
