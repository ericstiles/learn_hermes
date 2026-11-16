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
.......................................................................    [100%]
87 passed in ~17s
```

`pyproject.toml` wires coverage automatically (`--cov=todo --cov-report=term-missing`),
so every `pytest` run prints a coverage table. To run a single test file or a
single test, use pytest's usual selection:

```bash
python3 -m pytest tests/test_cli_e2e.py        # one file
python3 -m pytest -k "rm_removes_item"         # by name
```

---

## Web UI

The `todo` list can also be browsed and edited in a web browser. The web UI
lives in **`todo/web/`** (a stdlib `http.server` — no framework, no
dependencies) and reuses the exact same `todo.core` storage as the CLI, so a
list you build with the CLI and one you edit in the browser are the *same file*.

### Running it

From the repo root, start the server with the module entry point:

```bash
python3 -m todo.web
```

The server binds **`127.0.0.1` only** (it is never exposed to a network) and
prints one startup line, for example:

```console
$ python3 -m todo.web
todo web serving on http://127.0.0.1:8000
```

Then open `http://127.0.0.1:8000/` in a browser. Press `Ctrl-C` to stop it.

The **port** is resolved in this order:

1. an explicit `--port` flag (e.g. `python3 -m todo.web --port 8080`), which
   **wins**;
2. else the **`TODO_PORT`** environment variable;
3. else the default **`8000`**.

The **data file** comes from the same **`TODO_FILE`** environment variable the
CLI uses (else `./todos.json`), so the web UI and the CLI edit one list. The
page itself carries a small inline `<style>` block — a readable font, a centered
max-width container, completed items struck through, and styled form controls —
with **no external assets, no CDN, and no JavaScript**.

### Routes

| Method & path        | What it does                                             |
| -------------------- | -------------------------------------------------------- |
| `GET /`              | Render the list as one HTML page (200).                  |
| `POST /add`          | Add an item from the `text` form field; redirect to `/`. |
| `POST /done/<id>`    | Mark item `<id>` complete; redirect to `/`.              |
| `POST /delete/<id>`  | Delete item `<id>`; redirect to `/`.                     |

A successful `POST` answers **`303 See Other`** with a `Location: /` header, so
a browser follows the redirect and shows the updated list. Unsupported methods
(`PUT`, `DELETE`, …) are **`405`**; a malformed id, an over-long or missing
`text`, or a non-UTF-8 body is **`400`/`413`/`415`**; and any failure to read
the data file is a clean **`500`** page (no traceback, no file path leaks to the
client).

### What you'll see (real output)

The responses below are the **real output** of running the server on port 8000
against a list with two items (one already done) and curling it — nothing is
invented:

```console
$ curl -i http://127.0.0.1:8000/
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.15
Date: Mon, 16 Nov 2026 23:05:13 GMT
Content-Type: text/html; charset=utf-8
Content-Length: 1229

<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>todo</title>
<style>
...
```

Adding an item via the form (or `curl -X POST --data "text=Call the plumber"
http://127.0.0.1:8000/add`) redirects back home:

```console
$ curl -i -X POST --data "text=Call the plumber" http://127.0.0.1:8000/add
HTTP/1.0 303 See Other
Server: BaseHTTP/0.6 Python/3.11.15
Date: Mon, 16 Nov 2026 23:05:31 GMT
Location: /
```

An empty `text` field is rejected, and an unsupported method is refused — each
returns a small HTML error page that links back to `/`:

```console
$ curl -i -X POST -H "Content-Type: application/x-www-form-urlencoded" --data "text=" http://127.0.0.1:8000/add
HTTP/1.0 400 Bad Request
Server: BaseHTTP/0.6 Python/3.11.15
Date: Mon, 16 Nov 2026 23:05:31 GMT
Content-Type: text/html; charset=utf-8

$ curl -i -X PUT http://127.0.0.1:8000/
HTTP/1.0 405 Method Not Allowed
Server: BaseHTTP/0.6 Python/3.11.15
Date: Mon, 16 Nov 2026 23:05:31 GMT
Content-Type: text/html; charset=utf-8
```

The web UI is exercised by the same `python3 -m pytest` suite above: the tests
in `tests/test_web_*.py` start a real `http.server` on an ephemeral port
(`port=0`) in a background thread with a temporary `TODO_FILE` and drive it with
`http.client` — the same path a browser takes.

---

## Project layout

```
todo/            # the package
  __init__.py    # public API re-exports
  __main__.py    # `python -m todo` entry point
  cli.py         # argparse commands (add/list/done/rm) + error reporting
  core.py        # JSON load/save, id handling, TODO_FILE resolution
  web/           # the web UI (stdlib http.server, no dependencies)
    __init__.py  # re-exports from server.py
    __main__.py  # `python -m todo.web` entry point
    server.py    # the HTTP handler, page rendering, and inline CSS
tests/           # pytest suite
  test_core.py       # in-process unit tests for core + cli
  test_validation.py # error-handling / validation cases
  test_cli_e2e.py    # drives the real `python -m todo` entrypoint
  test_web_server.py # GET /, port resolution, loopback bind, the entry point
  test_web_add.py    # POST /add (and the empty-text 400)
  test_web_done.py   # POST /done/<id> (and the unknown/malformed-id cases)
  test_web_delete.py # POST /delete/<id> (and the unknown/malformed-id cases)
  test_web_hardening.py # escaping, body limits, 405s, clean 500s
  test_web_styling.py # inline <style>, no external refs, line-through, README
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
