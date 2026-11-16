# learn_hermes

A small, learning-oriented repo. Its centerpiece is **`todo`**, a tiny
command-line todo list built as the first "tracer bullet" to exercise the
Hermes Agent workflow end to end. It is written in **Python 3 stdlib only**
(`argparse`, `json`) — no third-party runtime dependencies — so you can run it
with nothing installed beyond a Python interpreter.

The repo also holds notes for a local LLM stack (llama.cpp + Open WebUI) and a
Hermes quick-start guide; see [Other docs](#other-docs) below.

---

## The `todo` CLI

Four commands, all run from the repo root:

| Command             | What it does                                             |
| ------------------- | --------------------------------------------------------|
| `todo add <text>`   | Append a new item and persist it to the JSON data file.  |
| `todo list`         | Print every item as `<id> [ ] text` (one per line).      |
| `todo done <id>`    | Mark an item complete (shown as `[x]` in `list`).        |
| `todo rm <id>`      | Delete an item. Remaining ids are **not** renumbered.    |

### Running it (no install required)

Because the package lives in `todo/` and has no runtime dependencies, the
simplest way to run it is the module form:

```bash
python3 -m todo <command> [args]
```

Run it from the repo root (where `todo/` lives). You can also install the
`todo` console script with `pip install -e .`, after which `todo <command>`
works on your `PATH` — but that is optional; `python3 -m todo` needs nothing
more than a Python 3 interpreter.

### Worked example

The output below is the real output of these commands run on a fresh data file.

```console
$ python3 -m todo add "Write the README"
added 1: Write the README

$ python3 -m todo add "Run the test suite"
added 2: Run the test suite

$ python3 -m todo add "Ship it"
added 3: Ship it

$ python3 -m todo list
1 [ ] Write the README
2 [ ] Run the test suite
3 [ ] Ship it

$ python3 -m todo done 1
done 1: Write the README

$ python3 -m todo list
1 [x] Write the README
2 [ ] Run the test suite
3 [ ] Ship it

$ python3 -m todo rm 2
removed 2: Run the test suite

$ python3 -m todo list
1 [x] Write the README
3 [ ] Ship it
```

Note the gap after `rm 2`: ids `1` and `3` survive with their original numbers —
deletion never renumbers remaining items.

### Error handling

Bad input is reported as a single clean line on **stderr** with a non-zero
exit code — never a traceback:

```console
$ python3 -m todo done abc
error: invalid id 'abc'            # exit 1

$ python3 -m todo done 99
error: no item with id 99         # exit 1
```

An empty `add` (no text) and a missing/unknown id for `done`/`rm` all behave
the same way: one error line, exit `1`.

---

## Data storage and `TODO_FILE`

State lives in a single JSON file — an array of items, each shaped
`{"id": int, "text": str, "done": bool}`. The path is controlled by the
**`TODO_FILE`** environment variable:

- **Unset** → the file defaults to `./todos.json` (in the current directory).
- **Set** → that path is used instead.

`TODO_FILE` is how the test suite keeps its own data in a temp file and how you
can keep separate lists per project. A missing or blank file is treated as an
empty list (so `list`/`add` work on a fresh checkout); a file that *exists but
is corrupt* (bad JSON, wrong shape, unreadable) is reported cleanly rather than
crashing.

```bash
# Point the CLI at a project-specific list
export TODO_FILE=./projects/acme/todos.json
python3 -m todo add "Draft the Q3 plan"
```

---

## Running the tests

Tests live in `tests/` and use **pytest** with coverage (`pytest-cov`). The
suite runs from the repo root:

```bash
python3 -m pytest
```

Expected result on the current tree:

```console
............................................                             [100%]
44 passed in ~0.4s
```

`pyproject.toml` wires coverage automatically (`--cov=todo --cov-report=term-missing`),
so every `pytest` run prints a coverage table. To run a single test file or a
single test, use pytest's usual selection:

```bash
python3 -m pytest tests/test_cli_e2e.py        # one file
python3 -m pytest -k "rm_removes_item"         # by name
```

---

## Project layout

```
todo/            # the package
  __init__.py    # public API re-exports
  __main__.py    # `python -m todo` entry point
  cli.py         # argparse commands (add/list/done/rm) + error reporting
  core.py        # JSON load/save, id handling, TODO_FILE resolution
tests/           # pytest suite
  test_core.py       # in-process unit tests for core + cli
  test_validation.py # error-handling / validation cases
  test_cli_e2e.py    # drives the real `python -m todo` entrypoint
pyproject.toml   # project metadata, `todo` script, pytest/coverage config
```

---

## Other docs

The `todo` CLI is the tracer bullet. This repo also documents the surrounding
learning stack:

- **`README_LLM.md`** — the local LLM stack (llama.cpp + Open WebUI on Apple
  Silicon), including how to point Open WebUI at the local model server.
- **`HOW_TO_USE_HERMES.md`** — a quick-start guide to driving the Hermes Agent
  itself.
