"""Tests for adding a todo item via a web form POST.

These start a *real* http.server on an ephemeral port (port 0) in a
background thread with a temporary TODO_FILE, then drive it with
http.client -- the same path a browser would take. They cover the
acceptance criteria for learn_hermes-7cq ("Web UI: add an item via form
POST"):

1. GET / renders a <form method=post action=/add> with an input named 'text'.
2. POST /add with 'text=buy+milk' -> 303 with Location: / (no redirect follow).
3. After that POST, load_todos() holds exactly one item
   {id:1, text:'buy milk', done:false} and GET / shows 'buy milk'.
4. POST /add with empty/blank text -> 400 and nothing is added.
5. Existing tests keep passing; coverage stays >= 80%.
"""

import http.client
import os
import threading

from todo import core
from todo.web import server

REPO_ROOT = None  # not needed here; helpers mirror test_web_server.py


def _start_server(todo_file, port=0, items=None):
    """Start make_server() on a background thread against a temp TODO_FILE.

    The server runs in-process, so it reads the *process* environment -- we set
    TODO_FILE in os.environ for the lifetime of the server and restore it on
    shutdown. Returns (server, thread, host, actual_port).
    """
    if items is None:
        items = []
    core.save_todos(items, path=todo_file)
    os.environ[core.TODO_ENV] = str(todo_file)
    server_obj = server.make_server(port, host="127.0.0.1")
    thread = threading.Thread(target=server_obj.serve_forever, daemon=True)
    thread.start()
    host, actual_port = server_obj.server_address
    return server_obj, thread, host, actual_port


def _stop(server_obj, thread):
    server_obj.shutdown()
    server_obj.server_close()
    thread.join(timeout=5)
    os.environ.pop(core.TODO_ENV, None)


def _request(host, port, method, path, body=None, headers=None):
    """Issue a request and return (status, headers, body, conn).

    The test client is a raw http.client connection, so it does *not* follow
    redirects -- 303 responses are returned as-is.
    """
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    resp_body = resp.read().decode("utf-8")
    return resp.status, resp.headers, resp_body, conn


# --- criterion 1: GET / renders the add form ------------------------------

def test_get_root_renders_add_form(tmp_path):
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        # The form posts to /add.
        assert "method=post" in body
        assert "action=/add" in body
        # The input is named 'text'.
        assert "name=text" in body
    finally:
        _stop(s, t)


# --- criteria 2 & 3: POST /add adds an item and redirects -------------------

def test_post_add_adds_item_and_redirects(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        # 2) POST /add with 'text=buy+milk' -> 303 with Location '/'.
        status, headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=buy+milk",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 303
        assert headers["Location"] == "/"

        # 3) Exactly one item persisted with the expected shape...
        items = core.load_todos(path=str(todo_file))
        assert items == [{"id": 1, "text": "buy milk", "done": False}]

        # ...and GET / now shows it.
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        assert "buy milk" in body
    finally:
        _stop(s, t)


# --- criterion 4: empty/blank text -> 400, nothing added -------------------

def test_post_add_empty_text_returns_400(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 400
        # Nothing was added.
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_post_add_blank_text_returns_400(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        # 'text=%20%20' is two spaces; urlencoded '+' is a space too, but here
        # we send literal spaces to mirror a browser submitting "  ".
        status, _headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=%20%20",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 400
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_post_add_with_no_text_field_returns_400(tmp_path):
    """A POST that omits the 'text' field entirely must also 400."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 400
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)
