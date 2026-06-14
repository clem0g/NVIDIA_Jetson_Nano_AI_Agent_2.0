"""
tests/test_tools.py

One test per failure mode, plus the happy paths that don't need the network.
The two tests that actually call Groq are skipped automatically when
GROQ_API_KEY is not set, so `pytest tests/` passes offline too.
"""

import os

import pytest

from tools import search_projects, plan_build, create_build_card, consult_docs
from utils.data_loader import load_projects, get_example_inventory, get_empty_inventory

NEEDS_KEY = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="requires GROQ_API_KEY (makes a live LLM call)",
)


# -- search_projects (all offline) --------------------------------------------

def test_search_returns_results():
    results = search_projects("object detection camera", difficulty=None, max_cost=None)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # No project is underwater/sonar AND under $5 -> empty list, no exception.
    results = search_projects("underwater sonar submarine", difficulty=None, max_cost=5)
    assert results == []


def test_search_price_filter():
    results = search_projects("camera", difficulty=None, max_cost=185)
    assert all(p["est_cost"] <= 185 for p in results)


def test_search_difficulty_filter():
    results = search_projects("robot", difficulty="Easy", max_cost=None)
    assert all(p["difficulty"].lower() == "easy" for p in results)


def test_search_filter_only_query_still_returns():
    # No keywords, just a difficulty filter -> should still return Easy projects.
    results = search_projects("", difficulty="Easy", max_cost=None)
    assert len(results) > 0
    assert all(p["difficulty"] == "Easy" for p in results)


# -- create_build_card empty-input failure mode (offline) ---------------------

def test_create_build_card_empty_plan_returns_message():
    project = load_projects()[0]
    out = create_build_card("", project)
    assert isinstance(out, str)
    assert out.strip() != ""
    assert "build card" in out.lower()  # descriptive error, not an exception


def test_create_build_card_whitespace_plan_returns_message():
    project = load_projects()[0]
    out = create_build_card("   \n  ", project)
    assert isinstance(out, str) and "build card" in out.lower()


# -- consult_docs graceful degradation (offline in this repo) -----------------

def test_consult_docs_is_graceful():
    # Standalone (no Project 1 rag module) -> returns a dict, never raises.
    out = consult_docs("How do I flash a Jetson Nano?")
    assert isinstance(out, dict)
    assert {"answer", "sources", "available", "grounded"} <= set(out)


def test_consult_docs_empty_question():
    out = consult_docs("")
    assert out["available"] is False


# -- LLM tools (skipped without a key) ----------------------------------------

@NEEDS_KEY
def test_plan_build_empty_inventory_returns_text():
    project = load_projects()[0]
    out = plan_build(project, get_empty_inventory())
    assert isinstance(out, str) and out.strip() != ""


@NEEDS_KEY
def test_plan_build_with_inventory_returns_text():
    project = load_projects()[0]
    out = plan_build(project, get_example_inventory())
    assert isinstance(out, str) and out.strip() != ""


@NEEDS_KEY
def test_create_build_card_varies():
    project = load_projects()[0]
    plan = "Use your Jetson Nano and USB webcam; install Docker; run the container."
    a = create_build_card(plan, project)
    b = create_build_card(plan, project)
    assert a.strip() and b.strip()
    assert a != b  # high temperature should produce different captions
