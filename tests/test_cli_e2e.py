"""End-to-end tests for the todo CLI tracer bullet.

These drive the *real* CLI entrypoint (`python -m todo`) via subprocess so we
exercise the same code path a user would, with a temporary TODO_FILE so the
tests never touch the user's real todo data.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(args, todo_file):
    """Invoke `python -m todo <args>` with TODO_FILE pointed at a temp path."""
    env = os.environ.copy()
    env["TODO_FILE"] = str(todo_file)
    return subprocess.run(
        [sys.executable, "-m", "todo", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def test_add_then_list_persists_two_items(tmp_path):
    """Add two items, then list them via the real CLI.

    Acceptance criteria:
      - two items added then listed via the real CLI entrypoint
      - a temp TODO_FILE is used
      - ids are stable ints starting at 1
    """
    todo_file = tmp_path / "todos.json"

    add_one = run_cli(["add", "write the tracer bullet"], todo_file)
    add_two = run_cli(["add", "ship it"], todo_file)

    # Both adds should succeed.
    assert add_one.returncode == 0, add_one.stderr
    assert add_two.returncode == 0, add_two.stderr

    # The data must be persisted to the temp file as JSON.
    assert todo_file.exists(), "TODO_FILE was not created"

    listing = run_cli(["list"], todo_file)
    assert listing.returncode == 0, listing.stderr

    out = listing.stdout
    # Format: "<id> [ ] text"
    assert "1 [ ] write the tracer bullet" in out, out
    assert "2 [ ] ship it" in out, out

    # ids are stable ints starting at 1 (no gaps, sequential).
    import re

    ids = [int(m.group(1)) for m in re.finditer(r"^(\d+) \[ \] ", out, re.MULTILINE)]
    assert ids == [1, 2], ids


def test_done_then_list_marks_item_complete(tmp_path):
    """Mark an item done via the real CLI, then list it as '[x]'.

    Acceptance criteria:
      - marking an item complete via the real CLI entrypoint
      - the list reflects the done state ('[x]')
      - a temp TODO_FILE is used
    """
    todo_file = tmp_path / "todos.json"

    add_one = run_cli(["add", "mark me done"], todo_file)
    assert add_one.returncode == 0, add_one.stderr

    done = run_cli(["done", "1"], todo_file)
    assert done.returncode == 0, done.stderr

    listing = run_cli(["list"], todo_file)
    assert listing.returncode == 0, listing.stderr
    assert "1 [x] mark me done" in listing.stdout, listing.stdout


def test_rm_then_list_removes_item_and_keeps_other_ids(tmp_path):
    """Remove an item via the real CLI; remaining ids must not change.

    Acceptance criteria:
      - removing an item via the real CLI entrypoint
      - the remaining items keep their original ids (no renumbering)
      - a temp TODO_FILE is used
    """
    todo_file = tmp_path / "todos.json"

    add_one = run_cli(["add", "first"], todo_file)
    add_two = run_cli(["add", "second"], todo_file)
    add_three = run_cli(["add", "third"], todo_file)
    assert add_one.returncode == 0, add_one.stderr
    assert add_two.returncode == 0, add_two.stderr
    assert add_three.returncode == 0, add_three.stderr

    rm = run_cli(["rm", "2"], todo_file)
    assert rm.returncode == 0, rm.stderr

    listing = run_cli(["list"], todo_file)
    assert listing.returncode == 0, listing.stderr
    out = listing.stdout
    # Item 2 is gone; 1 and 3 remain with their original ids (no renumbering).
    assert "1 [ ] first" in out, out
    assert "3 [ ] third" in out, out
    assert "2 [" not in out, out

    import re

    ids = [int(m.group(1)) for m in re.finditer(r"^(\d+) \[ \] ", out, re.MULTILINE)]
    assert ids == [1, 3], ids
