"""Validation and error-handling tests for the todo CLI (issue 7oa).

Every case here asserts two things: a non-zero exit code and a one-line
stderr message -- never a traceback. Some cases drive the real `python -m
todo` entrypoint via subprocess (matching tests/test_cli_e2e.py); the rest
call the CLI in-process with a temporary TODO_FILE.

The acceptance criteria are:
  - reject empty text, unknown ids, non-integer ids
  - recover cleanly from a missing or corrupt data file (no traceback)
  - each error case: exit code != 0 and a one-line stderr message
  - coverage >= 80%
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo import cli, core

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- helpers ---------------------------------------------------------------

def _run_cli(args, todo_file):
    """Invoke the real CLI entrypoint with a temp TODO_FILE; return CompletedProcess."""
    env = os.environ.copy()
    env["TODO_FILE"] = str(todo_file)
    return subprocess.run(
        [sys.executable, "-m", "todo", *args],
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _one_line(text):
    """Assert ``text`` is a single non-empty line (no internal newline)."""
    assert text.strip(), "stderr message must not be empty"
    assert "\n" not in text.strip(), f"expected one line, got: {text!r}"
    return text


def _no_traceback(stderr):
    """A clean recovery must not leak a Python traceback into stderr."""
    assert "Traceback (most recent call last)" not in stderr


# --- core: corrupt / unreadable data file ----------------------------------

def test_load_corrupt_json_raises(tmp_path):
    f = tmp_path / "todos.json"
    f.write_text("{ this is not json ]", encoding="utf-8")
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(f)


def test_load_non_array_json_raises(tmp_path):
    f = tmp_path / "todos.json"
    f.write_text(json.dumps({"items": {"nope": 1}}), encoding="utf-8")
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(f)


def test_load_unreadable_file_raises(tmp_path):
    # A path that exists but is not a readable file (here, a directory) makes
    # read_text raise an OSError. Using a directory instead of chmod 0o000
    # keeps the test deterministic even when running as root (root bypasses
    # permission bits, so a 0o000 file is still readable by root).
    d = tmp_path / "todos.json"
    d.mkdir()
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(d)


def test_missing_file_is_empty_not_corrupt(tmp_path):
    f = tmp_path / "todos.json"
    assert core.load_todos(f) == []


# --- core: corrupt entries (bad id / done / non-dict) -- issue 741 ---------
#
# The old load_todos silently *dropped* malformed entries and coerced types
# with int()/bool(), which (a) crashed with a raw traceback on a non-int id,
# (b) rendered done:"false" (a string) as done because bool("false") is True,
# and (c) hid a damaged file by dropping its bad rows. load_todos now raises
# CorruptDataFile with a one-line message (naming the file and the entry index)
# on any of these, instead of crashing or silently dropping.
#
# NOTE (741): the previous test_load_drops_non_dict_entries_in_array asserted
# the now-removed silent-drop behavior. It is replaced by the tests below; a
# non-dict (or otherwise malformed) entry is corruption, not something to drop.

def _corrupt_file(tmp_path, entries):
    f = tmp_path / "todos.json"
    f.write_text(json.dumps(entries), encoding="utf-8")
    return f


def test_load_rejects_string_id(tmp_path):
    # id "abc" used to raise a raw ValueError traceback; now a clean
    # CorruptDataFile (issue 741).
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(_corrupt_file(tmp_path, [{"id": "abc", "text": "x", "done": False}]))


@pytest.mark.parametrize("bad_id", [None, True, 0, -1, 1.5])
def test_load_rejects_bad_id(tmp_path, bad_id):
    # id null/True/0/-1/1.5 are all not a positive int.
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(_corrupt_file(tmp_path, [{"id": bad_id, "text": "x"}]))


def test_load_rejects_bool_done(tmp_path):
    # done:"false" (a string) used to render as done because bool("false") is
    # True; now it is corruption.
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(_corrupt_file(tmp_path, [{"id": 1, "text": "x", "done": "false"}]))


def test_load_defaults_missing_done_to_false(tmp_path):
    # A missing 'done' still defaults to False (a valid, common case).
    loaded = core.load_todos(_corrupt_file(tmp_path, [{"id": 1, "text": "x"}]))
    assert loaded == [{"id": 1, "text": "x", "done": False}]


def test_load_rejects_non_dict_entry(tmp_path):
    # A non-object entry (e.g. 5) is corruption, not a row to silently drop.
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(_corrupt_file(tmp_path, [5]))


def test_load_rejects_mixed_non_dict_and_dict(tmp_path):
    # Even with one good entry, a non-dict sibling makes the whole file corrupt
    # (no silent dropping of the bad sibling).
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(
            _corrupt_file(
                tmp_path,
                [{"id": 1, "text": "ok", "done": False}, 5, "junk", None],
            )
        )


def test_load_rejects_non_string_text(tmp_path):
    with pytest.raises(core.CorruptDataFile):
        core.load_todos(_corrupt_file(tmp_path, [{"id": 1, "text": 42}]))


def test_corrupt_message_names_file_and_index(tmp_path):
    f = _corrupt_file(tmp_path, [{"id": "abc", "text": "x"}])
    try:
        core.load_todos(f)
        raise AssertionError("expected CorruptDataFile")
    except core.CorruptDataFile as exc:
        msg = str(exc)
        assert msg.startswith("error:")
        assert str(f) in msg
        assert "index 0" in msg
        # One line, no traceback.
        assert "\n" not in msg


def test_load_valid_file_unaffected(tmp_path):
    # A well-formed array (including a missing 'done' and a done:true) loads
    # exactly as before.
    f = _corrupt_file(
        tmp_path,
        [
            {"id": 1, "text": "first", "done": False},
            {"id": 2, "text": "second"},
            {"id": 3, "text": "third", "done": True},
        ],
    )
    assert core.load_todos(f) == [
        {"id": 1, "text": "first", "done": False},
        {"id": 2, "text": "second", "done": False},
        {"id": 3, "text": "third", "done": True},
    ]


def test_list_bad_id_file_errors_one_line_via_cli(tmp_path):
    # Acceptance 5: 'python -m todo list' on a corrupt file exits 1, prints one
    # line starting 'error:', and leaks no traceback.
    f = _corrupt_file(tmp_path, [{"id": "abc", "text": "x", "done": False}])
    result = _run_cli(["list"], f)
    assert result.returncode == 1
    _one_line(result.stderr.strip())
    _no_traceback(result.stderr)
    assert result.stderr.lstrip().startswith("error:")


# --- cli: corrupt file recovers cleanly for every command -------------------

def test_list_corrupt_file_errors_one_line(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    f.write_text("}{garbage", encoding="utf-8")
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["list"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    _no_traceback(err)
    assert "corrupt" in err.lower() or "json" in err.lower()


def test_add_corrupt_file_errors_one_line(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    f.write_text("nope", encoding="utf-8")
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["add", "something"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    _no_traceback(err)


def test_done_corrupt_file_errors_one_line(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    f.write_text("[1,2", encoding="utf-8")
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["done", "1"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    _no_traceback(err)


def test_rm_corrupt_file_errors_one_line(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    f.write_text('{"items": 42}', encoding="utf-8")
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["rm", "1"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    _no_traceback(err)


def test_corrupt_file_no_traceback_via_cli(tmp_path):
    """A corrupt file must never print a Python traceback, even via subprocess."""
    f = tmp_path / "todos.json"
    f.write_text("this is corrupt <<< not json", encoding="utf-8")
    result = _run_cli(["list"], f)
    assert result.returncode != 0
    _no_traceback(result.stderr)
    _one_line(result.stderr.strip())


# --- cli: empty text -------------------------------------------------------

def test_add_empty_text_errors(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["add", "   "])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)


def test_add_empty_text_via_cli(tmp_path):
    f = tmp_path / "todos.json"
    result = _run_cli(["add", "   "], f)
    assert result.returncode != 0
    _one_line(result.stderr.strip())


# --- cli: unknown id -------------------------------------------------------

def test_done_unknown_id_errors(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    core.add_item("only one", path=f)
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["done", "999"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    assert "999" in err or "no item" in err.lower()


def test_rm_unknown_id_errors(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    core.add_item("only one", path=f)
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["rm", "999"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    assert "999" in err or "no item" in err.lower()


# --- cli: non-integer id ---------------------------------------------------

def test_done_non_integer_id_errors(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    core.add_item("thing", path=f)
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["done", "abc"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    assert "invalid" in err.lower()


def test_rm_non_integer_id_errors(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    core.add_item("thing", path=f)
    monkeypatch.setenv(core.TODO_ENV, str(f))
    rc = cli.main(["rm", "abc"])
    err = capsys.readouterr().err
    assert rc != 0
    _one_line(err)
    assert "invalid" in err.lower()


def test_non_integer_id_no_crash_via_cli(tmp_path):
    f = tmp_path / "todos.json"
    core.add_item("thing", path=f)
    result = _run_cli(["done", "abc"], f)
    assert result.returncode != 0
    _no_traceback(result.stderr)


# --- core: unknown id no-op is unchanged ------------------------------------

def test_unknown_id_does_not_mutate_data(tmp_path):
    f = tmp_path / "todos.json"
    core.add_item("keep", path=f)
    assert core.mark_done(999, path=f) is None
    assert core.remove_item(999, path=f) is None
    # No-op: the single item is untouched.
    loaded = core.load_todos(f)
    assert [i["id"] for i in loaded] == [1]
    assert loaded[0]["done"] is False


# --- core: _parse_id contract ----------------------------------------------

def test_parse_id_accepts_integer_string():
    assert cli._parse_id("42") == 42
    assert cli._parse_id("-7") == -7
    assert cli._parse_id("0007") == 7


def test_parse_id_rejects_non_integer():
    with pytest.raises(ValueError):
        cli._parse_id("abc")
    with pytest.raises(ValueError):
        cli._parse_id("3.5")
