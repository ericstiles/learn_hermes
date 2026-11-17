"""End-to-end tests for the todo web tracer bullet.

These start a *real* http.server on an ephemeral port (port 0) in a background
thread with a temporary TODO_FILE, then hit it with urllib/http.client -- the
same path a browser would take. They cover the acceptance criteria for the
web UI tracer bullet (learn_hermes-3dq).
"""

import http.client
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from todo import core
from todo.web import server

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _get(host, port, path):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    return resp.status, resp.headers, body, conn


# --- criterion 4: bound to 127.0.0.1 --------------------------------------

def test_server_bound_to_loopback(tmp_path):
    s, t, host, _port = _start_server(tmp_path / "todos.json")
    try:
        assert host == "127.0.0.1"
        assert s.server_address[0] == "127.0.0.1"
    finally:
        _stop(s, t)


# --- criteria 1, 2, 3: GET / renders the item list ------------------------

def test_get_root_lists_items(tmp_path):
    """GET / returns 200 text/html with every item as an <li>."""
    s, t, host, port = _start_server(tmp_path / "todos.json")
    try:
        status, headers, body, conn = _get(host, port, "/")
        conn.close()
        assert status == 200
        assert headers.get("Content-Type") == "text/html; charset=utf-8"
        # Both items appear.
        assert "alpha" in body
        assert "beta" in body
        # Exactly two <li> elements, and the done item is marked [x].
        assert body.count("<li") == 2
        assert "[x]" in body
    finally:
        _stop(s, t)


def test_get_root_empty_list_shows_no_items(tmp_path):
    """A missing/empty TODO_FILE yields 'No items'."""
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        status, _headers, body, conn = _get(host, port, "/")
        conn.close()
        assert status == 200
        assert "No items" in body
    finally:
        _stop(s, t)


# --- criterion 6: unknown path -> 404 -------------------------------------

def test_unknown_path_returns_404(tmp_path):
    s, t, host, port = _start_server(tmp_path / "todos.json")
    try:
        status, _headers, _body, conn = _get(host, port, "/nope")
        conn.close()
        assert status == 404
    finally:
        _stop(s, t)


# --- criterion 5: port resolution -----------------------------------------

def test_resolve_port_default_is_8000():
    assert server.resolve_port(None, {}) == 8000


def test_resolve_port_from_env():
    assert server.resolve_port(None, {"TODO_PORT": "9000"}) == 9000


def test_resolve_port_arg_wins_over_env():
    assert server.resolve_port(7000, {"TODO_PORT": "9000"}) == 7000


def test_resolve_port_arg_when_no_env():
    assert server.resolve_port(6000, {}) == 6000


# --- real entry point: `python -m todo.web --port N` ----------------------

def _free_port():
    """Grab an OS-assigned free port and release it."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_main_entry_serves_via_subprocess(tmp_path):
    """`python -m todo.web --port N` binds 127.0.0.1 and serves the list.

    Drives the real module entry point out-of-process, like a user would.
    """
    todo_file = tmp_path / "todos.json"
    core.save_todos(
        [
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": True},
        ],
        path=todo_file,
    )
    port = _free_port()
    env = os.environ.copy()
    env[core.TODO_ENV] = str(todo_file)
    proc = subprocess.Popen(
        [sys.executable, "-m", "todo.web", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Wait for the socket to accept connections.
        conn = None
        for _ in range(50):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                conn.request("GET", "/")
                resp = conn.getresponse()
                break
            except ConnectionRefusedError:
                time.sleep(0.1)
        else:
            raise AssertionError("server never came up")
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "text/html; charset=utf-8"
        body = resp.read().decode("utf-8")
        assert "alpha" in body
        assert "beta" in body
        assert body.count("<li") == 2
        assert "[x]" in body
        conn.close()
    finally:
        proc.terminate()
        proc.wait(timeout=5)
