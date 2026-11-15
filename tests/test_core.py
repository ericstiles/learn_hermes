"""In-process unit tests for the todo core + CLI.

The e2e test (tests/test_cli_e2e.py) drives the real `python -m todo` entry
point via subprocess to satisfy the acceptance criteria. These in-process tests
cover the same code paths directly so line coverage of the package is real.
"""

import pytest

from todo import cli
from todo import core


# --- core: load/save -------------------------------------------------------

def test_load_missing_file_returns_empty():
    assert core.load_todos("/nonexistent/path/todos.json") == []


def test_round_trip_add_and_load(tmp_path):
    f = tmp_path / "todos.json"
    item = core.add_item("hello", path=f)
    assert item == {"id": 1, "text": "hello", "done": False}
    assert core.load_todos(f) == [item]


def test_next_id_starts_at_one_and_is_stable(tmp_path):
    f = tmp_path / "todos.json"
    core.add_item("first", path=f)
    core.add_item("second", path=f)
    core.add_item("third", path=f)
    loaded = core.load_todos(f)
    assert [i["id"] for i in loaded] == [1, 2, 3]
    # After adding more, ids keep climbing from the max, no gaps.
    assert core.next_id(loaded) == 4


def test_load_tolerates_missing_file_then_add(tmp_path):
    f = tmp_path / "sub" / "todos.json"
    assert core.load_todos(f) == []
    core.add_item("bootstrap", path=f)
    assert core.load_todos(f) == [{"id": 1, "text": "bootstrap", "done": False}]


def test_load_tolerates_dict_wrapper(tmp_path):
    f = tmp_path / "todos.json"
    f.write_text('{"items": [{"id": 1, "text": "x", "done": true}]}')
    assert core.load_todos(f) == [{"id": 1, "text": "x", "done": True}]


def test_empty_text_file_is_empty_list(tmp_path):
    f = tmp_path / "todos.json"
    f.write_text("   ")
    assert core.load_todos(f) == []


def test_data_file_honors_env(tmp_path, monkeypatch):
    f = tmp_path / "env-todos.json"
    monkeypatch.setenv(core.TODO_ENV, str(f))
    assert core.data_file() == f


def test_data_file_default_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv(core.TODO_ENV, raising=False)
    assert core.data_file().name == "todos.json"


# --- cli -------------------------------------------------------------------

def test_main_add_then_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(core.TODO_ENV, str(tmp_path / "todos.json"))
    rc = cli.main(["add", "do", "the", "thing"])
    assert rc == 0
    rc = cli.main(["add", "second"])
    assert rc == 0
    rc = cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 [ ] do the thing" in out
    assert "2 [ ] second" in out


def test_main_add_empty_text_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(core.TODO_ENV, str(tmp_path / "todos.json"))
    rc = cli.main(["add", "   "])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "error" in err


def test_list_marks_done_items(tmp_path, monkeypatch, capsys):
    f = tmp_path / "todos.json"
    core.add_item("todo", path=f)
    items = core.load_todos(f)
    items[0]["done"] = True
    core.save_todos(items, f)
    monkeypatch.setenv(core.TODO_ENV, str(f))
    assert cli.main(["list"]) == 0
    assert "1 [x] todo" in capsys.readouterr().out


def test_missing_command_errors(tmp_path, monkeypatch):
    monkeypatch.setenv(core.TODO_ENV, str(tmp_path / "todos.json"))
    with pytest.raises(SystemExit):
        cli.main([])
