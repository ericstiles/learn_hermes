"""Tests for deleting a todo item via a web form POST.

These start a *real* http.server on an ephemeral port (port 0) in a
background thread with a temporary TODO_FILE, then drive it with
http.client -- the same path a browser would take. They cover the
acceptance criteria for learn_hermes-c13 ("Web UI: delete an item"):

1. GET / contains a form with action=/delete/<id> for every item.
2. With items 1,2,3, POST /delete/2 returns 303 with Location '/'.
3. Afterwards load_todos() ids are [1,3] and GET / no longer contains
   item 2's text.
4. POST /delete/99 (no such item) returns 404 and does not modify the file.
5. Existing tests keep passing; coverage stays >= 80%.
"""

import http.client
import os
import threading

from todo import core
from todo.web import server


def _start_server(todo_file, port=0, items=None):
    """Start make_server() on a background thread against a temp TODO_FILE.

    The server runs in-process, so it reads the *process* environment -- we
    set TODO_FILE in os.environ for the lifetime of the server and restore it
    on shutdown. Returns (server, thread, host, actual_port).
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


# --- criterion 1: GET / renders a /delete/<id> form for every item ----------

def test_get_root_renders_delete_form_for_every_item(tmp_path):
    s, t, host, port = _start_server(
        tmp_path / "todos.json",
        items=[
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": False},
            {"id": 3, "text": "gamma", "done": True},
        ],
    )
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        # Every item -- done or not -- carries a delete form.
        assert "action=/delete/1" in body
        assert "action=/delete/2" in body
        assert "action=/delete/3" in body
        assert "method=post" in body
        assert "Delete" in body
    finally:
        _stop(s, t)


def test_get_root_delete_form_on_done_item(tmp_path):
    """A done item still gets a delete form (deleting is always allowed)."""
    s, t, host, port = _start_server(
        tmp_path / "todos.json",
        items=[{"id": 1, "text": "alpha", "done": True}],
    )
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        assert "action=/delete/1" in body
    finally:
        _stop(s, t)


# --- criteria 2 & 3: POST /delete/<id> removes the item and redirects -------

def test_post_delete_removes_item_and_redirects(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file,
        items=[
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": False},
            {"id": 3, "text": "gamma", "done": False},
        ],
    )
    try:
        # 2) POST /delete/2 -> 303 with Location '/'.
        status, headers, _body, conn = _request(host, port, "POST", "/delete/2")
        conn.close()
        assert status == 303
        assert headers["Location"] == "/"

        # 3) Item 2 is gone; remaining ids are [1, 3] (not renumbered)...
        items = core.load_todos(path=str(todo_file))
        assert [it["id"] for it in items] == [1, 3]
        assert all(it["text"] != "beta" for it in items)

        # ...and GET / no longer shows item 2's text.
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        assert "beta" not in body
        assert "alpha" in body
        assert "gamma" in body
    finally:
        _stop(s, t)


# --- criterion 4: unknown id -> 404 and no file change ---------------------

def test_post_delete_unknown_id_returns_404_and_no_change(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file,
        items=[
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": False},
            {"id": 3, "text": "gamma", "done": False},
        ],
    )
    try:
        before = core.load_todos(path=str(todo_file))
        status, headers, _body, conn = _request(host, port, "POST", "/delete/99")
        conn.close()
        assert status == 404
        # Nothing was removed: the file is byte-for-byte unchanged.
        after = core.load_todos(path=str(todo_file))
        assert after == before
        assert [it["id"] for it in after] == [1, 2, 3]
    finally:
        _stop(s, t)


def test_post_delete_rejects_non_integer_id(tmp_path):
    """A /delete path with a non-numeric id is a 404, not a 500 or crash."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file,
        items=[{"id": 1, "text": "alpha", "done": False}],
    )
    try:
        status, _headers, _body, conn = _request(host, port, "POST", "/delete/x")
        conn.close()
        assert status == 404
        # Nothing was removed.
        assert core.load_todos(path=str(todo_file)) == [
            {"id": 1, "text": "alpha", "done": False}
        ]
    finally:
        _stop(s, t)
