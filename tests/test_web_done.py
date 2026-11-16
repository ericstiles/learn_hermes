"""Tests for marking an item done via a web form POST.

These start a *real* http.server on an ephemeral port (port 0) in a background
thread with a temporary TODO_FILE, then drive it with http.client -- the same
path a browser would take. They cover the acceptance criteria for
learn_hermes-mse ("Web UI: mark an item done"):

1. With item 1 not done, GET / contains a form with action=/done/1.
2. POST /done/1 returns 303 with Location '/'.
3. Afterwards load_todos()[0]['done'] is True and GET / shows item 1 as done
   (marked [x]) with no /done/1 form.
4. POST /done/99 (no such item) returns 404 and does not modify the file.
5. Existing tests keep passing; coverage stays >= 80%.
"""

import http.client
import os
import threading

from todo import core
from todo.web import server


def _start_server(todo_file, port=0, items=None):
    """Start make_server() on a background thread against a temp TODO_FILE.

    The server runs in-process, so it reads the *process* environment -- we set
    TODO_FILE in os.environ for the lifetime of the server and restore it on
    shutdown. Returns (server, thread, host, actual_port).
    """
    if items is None:
        items = [
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": True},
        ]
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


# --- criterion 1: GET / renders a /done/<id> form for not-done items -------


def test_get_root_renders_done_form_for_not_done_item(tmp_path):
    s, t, host, port = _start_server(
        tmp_path / "todos.json",
        items=[{"id": 1, "text": "alpha", "done": False}],
    )
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        # The not-done item carries a form that posts to /done/1.
        assert "action=/done/1" in body
        assert "method=post" in body
        assert "Done" in body
    finally:
        _stop(s, t)


def test_get_root_no_done_form_for_done_item(tmp_path):
    s, t, host, port = _start_server(
        tmp_path / "todos.json",
        items=[
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": True},
        ],
    )
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        # The not-done item gets a form...
        assert "action=/done/1" in body
        # ...but the already-done item does not.
        assert "action=/done/2" not in body
    finally:
        _stop(s, t)


# --- criteria 2 & 3: POST /done/<id> marks the item done and redirects -----


def test_post_done_marks_item_and_redirects(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file, items=[{"id": 1, "text": "alpha", "done": False}]
    )
    try:
        # 2) POST /done/1 -> 303 with Location '/'.
        status, headers, _body, conn = _request(host, port, "POST", "/done/1")
        conn.close()
        assert status == 303
        assert headers["Location"] == "/"

        # 3) The item is now done on disk...
        items = core.load_todos(path=str(todo_file))
        assert items[0]["done"] is True

        # ...and GET / shows it as [x] with no /done/1 form left.
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        assert "[x]" in body
        assert "action=/done/1" not in body
    finally:
        _stop(s, t)


# --- criterion 4: unknown id -> 404 and no file change ---------------------


def test_post_done_unknown_id_returns_404_and_no_change(tmp_path):
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file,
        items=[
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": True},
        ],
    )
    try:
        before = core.load_todos(path=str(todo_file))
        status, _headers, _body, conn = _request(host, port, "POST", "/done/99")
        conn.close()
        assert status == 404
        # No item was marked done and the stored items are unchanged.
        after = core.load_todos(path=str(todo_file))
        assert after == before
        assert all(not it["done"] or it["id"] == 2 for it in after)
        assert all(it["id"] != 99 for it in after)
    finally:
        _stop(s, t)


def test_post_done_rejects_non_integer_id(tmp_path):
    """A /done path with a non-numeric id is a 400 (invalid id), not a crash.

    learn_hermes-clq redefined malformed ids as 400 (previously 404); a
    well-formed id with no matching item is still a 404.
    """
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file, items=[{"id": 1, "text": "alpha", "done": False}]
    )
    try:
        status, _headers, _body, conn = _request(host, port, "POST", "/done/x")
        conn.close()
        assert status == 400
        # Nothing was marked done.
        assert core.load_todos(path=str(todo_file))[0]["done"] is False
    finally:
        _stop(s, t)
