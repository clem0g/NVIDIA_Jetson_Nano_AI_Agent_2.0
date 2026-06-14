"""
utils/data_loader.py

Helper functions for loading BuildFindr's mock data. Use these rather than
re-reading the JSON files by hand.

    load_projects()          -> list[dict]   the project catalog
    get_example_inventory()  -> dict         a populated sample inventory
    get_empty_inventory()    -> dict         an empty inventory (new user)
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROJECTS_PATH = DATA_DIR / "projects.json"
INVENTORY_PATH = DATA_DIR / "inventory_schema.json"


def load_projects() -> list[dict]:
    """Return the full list of project dicts from data/projects.json."""
    with open(PROJECTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_inventory_file() -> dict:
    with open(INVENTORY_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_example_inventory() -> dict:
    """Return the sample inventory dict ({'items': [...]})."""
    return _load_inventory_file()["example_inventory"]


def get_empty_inventory() -> dict:
    """Return an empty inventory dict ({'items': []}) for new-user testing."""
    return _load_inventory_file()["empty_inventory"]


if __name__ == "__main__":
    projects = load_projects()
    print(f"Loaded {len(projects)} projects.")
    difficulties = sorted({p["difficulty"] for p in projects})
    print(f"Difficulties present: {difficulties}")
    example = get_example_inventory()
    print(f"Example inventory: {len(example['items'])} items.")
    print(f"Empty inventory:   {len(get_empty_inventory()['items'])} items.")
