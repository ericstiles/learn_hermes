"""Hardening tests for the web UI (issue learn_hermes-clq).

These start a *real* http.server on an ephemeral port (port 0) in a
background thread with a temporary TODO_FILE, then drive it with
http.client -- the same path a browser would take. They cover the
acceptance criteria for learn_hermes-clq ("Web UI: HTML escaping, input
validation, clean error pages"):

1. Adding text '<script>alert(1)</script>' then GET / contains the escaped
   form and never a raw '<script>'.
2. Text containing a double quote is rendered as '&quot;'.
3. POST /done/abc, /done/-1, /delete/1.5 and /done/99999999999999999999 each
   return 400 (malformed id); a well-formed id with no item is still a 404.
4. POST /add with Content-Length 5000 returns 413; text of 201 chars returns
   400; text of exactly 200 chars returns 303.
5. PUT / returns 405.
6. With TODO_FILE containing 'not json', GET / returns 500 whose body
   contains 'Internal error' but neither 'Traceback' nor the temp path.
7. POST /add with body 'text=%ff' (invalid UTF-8) returns 400.
8. Existing tests pass; coverage stays >= 80%.
"""

import http.client
import os
import threading
import urllib.parse

from todo import core
from todo.web import server

# --- helpers (mirroring test_web_done.py) ----------------------------------


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


def _start_server_with_raw_file(todo_file, raw_content, port=0):
    """Start a server whose TODO_FILE is exactly ``raw_content``.

    Unlike :func:`_start_server`, this does *not* (re)save items, so it can
    seed a corrupt data file. Returns (server, thread, host, actual_port).
    """
    todo_file.write_text(raw_content, encoding="utf-8")
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

    The client is a raw http.client connection, so it does *not* follow
    redirects -- 303 responses are returned as-is.
    """
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    resp_body = resp.read().decode("utf-8")
    return resp.status, resp.headers, resp_body, conn


# --- criterion 1 & 2: HTML escaping ----------------------------------------


def test_add_then_render_escapes_script_tag(tmp_path):
    """Adding '<script>alert(1)</script>' renders escaped, never raw."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        payload = urllib.parse.urlencode({"text": "<script>alert(1)</script>"})
        status, _headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 303

        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        # The escaped form is present...
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        # ...and a raw script tag is never emitted.
        assert "<script>" not in body
    finally:
        _stop(s, t)


def test_add_then_render_escapes_double_quote(tmp_path):
    """Text with a double quote renders as &quot; (quote=True)."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        payload = urllib.parse.urlencode({"text": 'say "hi"'})
        status, _headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 303

        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 200
        assert "&quot;" in body
        # The literal quote must not survive into the markup.
        assert 'say "hi"' not in body
    finally:
        _stop(s, t)


# --- criterion 3: malformed ids -> 400 -------------------------------------


def test_malformed_ids_return_400(tmp_path):
    """Letters, a sign, a decimal, and >9 digits are all 400 (not 404/crash)."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file, items=[{"id": 1, "text": "alpha", "done": False}]
    )
    try:
        for path in (
            "/done/abc",
            "/done/-1",
            "/delete/1.5",
            "/done/99999999999999999999",
        ):
            status, _headers, _body, conn = _request(host, port, "POST", path)
            conn.close()
            assert status == 400, f"{path} expected 400, got {status}"
        # Nothing was changed on disk.
        assert core.load_todos(path=str(todo_file)) == [
            {"id": 1, "text": "alpha", "done": False}
        ]
    finally:
        _stop(s, t)


# --- criterion 4: body-size and text-length limits -------------------------


def test_add_oversized_body_returns_413(tmp_path):
    """Content-Length 5000 (> 4096) is a 413, checked before reading."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        body = "a" * 5000
        status, _headers, _resp, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 413
        # Nothing was added.
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_add_text_201_chars_returns_400(tmp_path):
    """Text longer than 200 chars is rejected with 400."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        body = "text=" + ("a" * 201)
        status, _headers, _resp, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 400
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_add_text_exactly_200_chars_returns_303(tmp_path):
    """Text of exactly 200 chars is accepted (the limit is inclusive)."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        body = "text=" + ("a" * 200)
        status, _headers, _resp, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 303
        assert [it["text"] for it in core.load_todos(path=str(todo_file))] == [
            "a" * 200
        ]
    finally:
        _stop(s, t)


def test_add_missing_content_length_returns_400(tmp_path):
    """A POST with no Content-Length header is a 400."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        # An empty body via http.client sends no Content-Length; emulate a
        # non-urlencoded, length-less body by sending a raw request.
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.putrequest("POST", "/add", skip_host=True, skip_accept_encoding=True)
        conn.putheader("Content-Type", "application/x-www-form-urlencoded")
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 400
    finally:
        _stop(s, t)


def test_add_wrong_content_type_returns_415(tmp_path):
    """A non-urlencoded Content-Type is a 415."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _headers, _resp, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=hello",
            headers={"Content-Type": "application/json"},
        )
        conn.close()
        assert status == 415
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


# --- criterion 5: unsupported methods -> 405 -------------------------------


def test_unsupported_method_returns_405(tmp_path):
    """PUT (and the other unsupported verbs) are a 405."""
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            status, _headers, _body, conn = _request(host, port, method, "/")
            conn.close()
            assert status == 405, f"{method} expected 405, got {status}"
    finally:
        _stop(s, t)


# --- criterion 6: corrupt data file -> clean 500 ---------------------------


def test_corrupt_data_file_returns_clean_500(tmp_path):
    """GET / on a corrupt TODO_FILE is a 500 'Internal error', no leak."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server_with_raw_file(todo_file, "not json")
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/")
        conn.close()
        assert status == 500
        assert "Internal error" in body
        # No traceback and no absolute temp path leak into the response.
        assert "Traceback" not in body
        assert str(todo_file) not in body
        assert "todos.json" not in body
    finally:
        _stop(s, t)


# --- criterion 7: invalid UTF-8 in the body -> 400 -------------------------


def test_add_invalid_utf8_returns_400(tmp_path):
    """A body 'text=%ff' (bad percent-escape) is a 400."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _headers, _resp, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=%ff",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 400
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


# --- criterion 3 (extra): well-formed id with no item is still a 404 -------


def test_wellformed_unknown_id_still_404(tmp_path):
    """A numeric id that matches no item is a 404, not a 400."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file, items=[{"id": 1, "text": "alpha", "done": False}]
    )
    try:
        for path in ("/done/99", "/delete/99"):
            status, _headers, _body, conn = _request(host, port, "POST", path)
            conn.close()
            assert status == 404, f"{path} expected 404, got {status}"
        assert core.load_todos(path=str(todo_file)) == [
            {"id": 1, "text": "alpha", "done": False}
        ]
    finally:
        _stop(s, t)
