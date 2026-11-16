"""Core data layer for the todo tracer bullet.

Storage: a single JSON file (path from the TODO_FILE env var, else
./todos.json). The file holds a JSON array of items, each an object with the
shape ``{"id": int, "text": str, "done": bool}``. Ids are stable positive
integers starting at 1.
"""

import json
import os
from pathlib import Path

# Environment variable that overrides the default data file location so tests
# can use a temp file and users can keep separate lists per context.
TODO_ENV = "TODO_FILE"

# Default location when TODO_FILE is not set.
DEFAULT_TODO_FILE = "todos.json"


def data_file():
    """Return the Path to the data file, honoring the TODO_FILE env var."""
    override = os.environ.get(TODO_ENV)
    return Path(override) if override else Path(DEFAULT_TODO_FILE)


def load_todos(path=None):
    """Load items from the JSON file. Missing/empty/corrupt -> empty list.

    Tolerates a missing file (first run) and a stray empty file, returning []
    so `add` and `list` both work on a fresh checkout.
    """
    p = Path(path) if path is not None else data_file()
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not raw:
        return []
    data = json.loads(raw)
    # Accept either a bare list of items or {"items": [...]}.
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        return []
    # Normalize: coerce to the canonical item shape, drop malformed entries.
    items = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "id": int(entry.get("id", 0)),
                "text": str(entry.get("text", "")),
                "done": bool(entry.get("done", False)),
            }
        )
    return items


def save_todos(items, path=None):
    """Persist items to the JSON file, creating parent dirs as needed."""
    p = Path(path) if path is not None else data_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def next_id(items):
    """Next stable integer id: 1 when empty, else max(existing) + 1."""
    ids = [it["id"] for it in items if isinstance(it.get("id"), int)]
    return (max(ids) + 1) if ids else 1


def add_item(text, path=None):
    """Append a new item and return the new item dict (persisted)."""
    items = load_todos(path)
    item = {"id": next_id(items), "text": text, "done": False}
    items.append(item)
    save_todos(items, path)
    return item


def mark_done(item_id, path=None):
    """Mark the item with ``item_id`` complete and persist.

    Returns the updated item dict, or ``None`` when no item has that id.
    (Unknown-id *error reporting* is owned by the validation issue; the core
    contract is simply "update if present, else no-op".)
    """
    items = load_todos(path)
    for item in items:
        if item["id"] == item_id:
            item["done"] = True
            save_todos(items, path)
            return item
    return None


def remove_item(item_id, path=None):
    """Delete the item with ``item_id`` and persist.

    Returns the removed item dict, or ``None`` when no item has that id.
    Remaining ids are left unchanged -- deletion does *not* renumber, so a gap
    is expected (e.g. removing 2 from [1,2,3] leaves [1,3]). The core contract
    is "delete if present, else no-op"; unknown-id *error reporting* is owned
    by the validation issue.
    """
    items = load_todos(path)
    kept, removed = [], None
    for item in items:
        if item["id"] == item_id and removed is None:
            removed = item  # remove only the first matching id
        else:
            kept.append(item)
    if removed is None:
        return None  # no item matched -> no-op, nothing written
    save_todos(kept, path)
    return removed
