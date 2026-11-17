"""Hardening tests for the web UI (issue learn_hermes-7p6).

These start a *real* http.server on an ephemeral port (port 0) in a
background thread with a temporary TODO_FILE and drive it with
http.client / raw sockets -- the same path a browser (or an attacker's web
page) would take. They cover the acceptance criteria for learn_hermes-7p6
("Web server hardening gaps: negative Content-Length, query strings,
cross-origin POST and Host check"):

1. POST /add with Content-Length -5 is a clean 400 (no empty reply, no
   traceback on stderr); '+5', ' 5' and '5x' are each 400 too.
2. GET /?x=1 is 200 and POST /add?x=1 with text=a is 303 (query string
   ignored).
3. A cross-origin POST (Origin: http://evil.example) is a 403 and adds
   nothing; Origin: http://127.0.0.1:<port> is 303; no Origin header is 303.
4. Sec-Fetch-Site: cross-site is 403.
5. A Host of evil.example is 403; 127.0.0.1:<port> and localhost:<port> are
   200.
6. `python -m todo.web --port 0` prints its "serving on" line promptly when
   stdout is a pipe.
7. Existing tests pass; coverage stays >= 80%.
"""

import http.client
import os
import select
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from todo import core
from todo.web import server

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- helpers (mirroring test_web_hardening.py) -----------------------------


def _start_server(todo_file, port=0, items=None):
    """Start make_server() on a background thread against a temp TODO_FILE.

    Returns (server, thread, host, actual_port).
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
    """Issue a request and return (status, headers, body, conn)."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    resp_body = resp.read().decode("utf-8")
    return resp.status, resp.headers, resp_body, conn


def _request_raw(host, port, method, path, raw_headers, body=b""):
    """Send a raw request with exact header text and read the status line.

    Returns (status, response_body_bytes). Used for cases http.client would
    normalize away (e.g. a non-integer Content-Length) or that must set a Host
    header the server does not recognize.
    """
    s = socket.create_connection((host, port), timeout=5)
    req = f"{method} {path} HTTP/1.1\r\nHost: {raw_headers['Host']}\r\n"
    s.sendall(req.encode("utf-8"))
    for k, v in raw_headers.items():
        if k == "Host":
            continue
        s.sendall(f"{k}: {v}\r\n".encode())
    s.sendall(b"\r\n")
    # Read the full response until the server closes the connection. For a
    # rejected request the server may answer with HTTP/1.0 and close without a
    # body (or with the error page); we take everything up to EOF.
    chunks = []
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except TimeoutError:
        pass
    s.close()
    raw = b"".join(chunks)
    if b"\r\n\r\n" not in raw:
        raise AssertionError(f"no response headers received: {raw!r}")
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body.decode("utf-8", "replace")


# --- criterion 1: non-integer / negative Content-Length -> 400 -------------


def test_add_negative_content_length_is_400_and_no_traceback(tmp_path):
    """POST /add with 'Content-Length: -5' is a clean 400, not an empty reply.

    The buggy code handed -5 to rfile.read (which raises ValueError outside
    any try block), dropping the connection and printing a traceback to
    stderr. This must now be a 400 with a well-formed response body.
    """
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, body = _request_raw(
            host,
            port,
            "POST",
            "/add",
            {
                "Host": "127.0.0.1",
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": "-5",
            },
        )
        assert status == 400
        assert "Traceback" not in body
        assert "Home" in body  # a well-formed error page, not a dropped conn
        # Nothing was added.
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_add_bad_content_length_variants_return_400(tmp_path):
    """A leading sign or a stray character in Content-Length is a 400.

    '+5' and '5x' are not canonical decimals, so they are rejected before the
    body is read. (The issue also names ' 5'; the HTTP layer strips leading
    whitespace so ' 5' reaches the handler as the valid '5' and is covered by
    the unit-level _parse_content_length test, where the leading space is what
    makes it non-canonical.)
    """
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        for cl in ("+5", "5x"):
            status, body = _request_raw(
                host,
                port,
                "POST",
                "/add",
                {
                    "Host": "127.0.0.1",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": cl,
                },
            )
            assert status == 400, f"CL {cl!r} expected 400, got {status}"
            assert "Traceback" not in body
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_space_padded_content_length_is_noncanonical(tmp_path):
    """A leading-space Content-Length (" 5") is not canonical -- a 400 cause.

    The HTTP layer normalizes " 5" to "5" on the wire, so the non-canonical
    value is exercised here, where the leading space is what the parser
    rejects.
    """
    try:
        server._parse_content_length(" 5")
    except ValueError:
        pass
    else:
        raise AssertionError("' 5' should be rejected as non-canonical")


def test_parse_content_length_rejects_noncanonical(tmp_path):
    """_parse_content_length rejects non-integer / negative / signed / padded."""
    for bad in ("-5", "+5", " 5", "5 ", "5x", "5 9", "", "  5", "5\n"):
        try:
            server._parse_content_length(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} was accepted, expected ValueError")
    # A canonical non-negative integer is accepted and returns its int value.
    assert server._parse_content_length("0") == 0
    assert server._parse_content_length("10") == 10
    assert server._parse_content_length("4096") == 4096


# --- criterion 2: query strings are ignored --------------------------------


def test_get_root_with_query_string_returns_200(tmp_path):
    """GET /?x=1 returns 200 (the query string is ignored)."""
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        status, _headers, body, conn = _request(host, port, "GET", "/?x=1")
        conn.close()
        assert status == 200
        assert "No items" in body
    finally:
        _stop(s, t)


def test_post_add_with_query_string_returns_303(tmp_path):
    """POST /add?x=1 with text=a returns 303 and adds the item."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _headers, _body, conn = _request(
            host,
            port,
            "POST",
            "/add?x=1",
            body="text=a",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 303
        assert [it["text"] for it in core.load_todos(path=str(todo_file))] == ["a"]
    finally:
        _stop(s, t)


def test_done_and_delete_with_query_string_still_route(tmp_path):
    """A query string on /done/ and /delete/ is ignored; they still route."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file, items=[{"id": 1, "text": "alpha", "done": False}]
    )
    try:
        status, _h, _b, conn = _request(host, port, "POST", "/done/1?x=1")
        conn.close()
        assert status == 303
        assert core.load_todos(path=str(todo_file))[0]["done"] is True

        status, _h, _b, conn = _request(host, port, "POST", "/delete/1?x=2")
        conn.close()
        assert status == 303
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


# --- criterion 3: cross-origin POST (CSRF) ---------------------------------


def test_cross_origin_post_add_is_403_and_adds_nothing(tmp_path):
    """Origin: http://evil.example is a 403 and adds nothing."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _h, _body, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=fromevil",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "http://evil.example",
            },
        )
        conn.close()
        assert status == 403
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_loopback_origin_post_add_is_303(tmp_path):
    """Origin: http://127.0.0.1:<port> is accepted (303)."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _h, _b, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=ok",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": f"http://127.0.0.1:{port}",
            },
        )
        conn.close()
        assert status == 303
        assert [it["text"] for it in core.load_todos(path=str(todo_file))] == ["ok"]
    finally:
        _stop(s, t)


def test_no_origin_header_post_add_is_303(tmp_path):
    """A POST with no Origin header is accepted (303)."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _h, _b, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=noorigin",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        conn.close()
        assert status == 303
    finally:
        _stop(s, t)


def test_cross_origin_done_and_delete_are_403(tmp_path):
    """Cross-origin POST to /done/ and /delete/ is 403 and changes nothing."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(
        todo_file, items=[{"id": 1, "text": "alpha", "done": False}]
    )
    try:
        for path in ("/done/1", "/delete/1"):
            status, _h, _b, conn = _request(
                host,
                port,
                "POST",
                path,
                headers={"Origin": "http://evil.example"},
            )
            conn.close()
            assert status == 403, f"{path} expected 403, got {status}"
        assert core.load_todos(path=str(todo_file)) == [
            {"id": 1, "text": "alpha", "done": False}
        ]
    finally:
        _stop(s, t)


# --- criterion 4: Sec-Fetch-Site -------------------------------------------


def test_cross_site_sec_fetch_site_is_403(tmp_path):
    """A cross-site Sec-Fetch-Site (no Origin) is a 403."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _h, _b, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=fromsite",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        conn.close()
        assert status == 403
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


def test_same_origin_sec_fetch_site_is_303(tmp_path):
    """A same-origin Sec-Fetch-Site (no Origin) is accepted (303)."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _h, _b, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=same",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        conn.close()
        assert status == 303
    finally:
        _stop(s, t)


# --- criterion 5: Host / DNS-rebinding check -------------------------------


def test_get_bad_host_is_403(tmp_path):
    """A Host of evil.example is a 403 for GET /."""
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        status, _h, _body, conn = _request(
            host, port, "GET", "/", headers={"Host": "evil.example"}
        )
        conn.close()
        assert status == 403
    finally:
        _stop(s, t)


def test_get_loopback_hosts_are_200(tmp_path):
    """Host 127.0.0.1:<port> and localhost:<port> are 200."""
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        for host_header in (f"127.0.0.1:{port}", f"localhost:{port}"):
            status, _h, _b, conn = _request(
                host, port, "GET", "/", headers={"Host": host_header}
            )
            conn.close()
            assert status == 200, f"Host {host_header} expected 200, got {status}"
    finally:
        _stop(s, t)


def test_post_add_bad_host_is_403(tmp_path):
    """A cross-host POST /add is a 403 and adds nothing."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        status, _h, _b, conn = _request(
            host,
            port,
            "POST",
            "/add",
            body="text=rebound",
            headers={"Host": "evil.example"},
        )
        conn.close()
        assert status == 403
        assert core.load_todos(path=str(todo_file)) == []
    finally:
        _stop(s, t)


# --- criterion 6: startup line flushes when stdout is a pipe ---------------


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_main_prints_serving_line_to_pipe(tmp_path):
    """`python -m todo.web --port N` prints its line promptly into a pipe.

    A non-flushing ``print`` buffers the line in the child's stdout buffer and
    it only reaches the pipe once the buffer fills or the process exits -- so
    the child would still be alive when a prompt reader times out. A flushed
    line arrives within a short deadline.
    """
    todo_file = tmp_path / "todos.json"
    core.save_todos([{"id": 1, "text": "alpha", "done": False}], path=todo_file)
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
        # Wait for the "serving on" line with a hard deadline. A prompt line
        # (flush=True) arrives quickly; a buffered one does not, so the
        # timeout fires while the child is still alive.
        deadline = time.monotonic() + 3.0
        first_line = b""
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.1))
            if not ready:
                continue
            first_line = proc.stdout.readline()
            break
        assert b"serving on" in first_line, (
            f"'serving on' line not delivered promptly: got {first_line!r} "
            f"(child still running: {proc.poll() is None})"
        )
        # The server is now live: confirm it accepts a request on the port.
        for _ in range(50):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                conn.request("GET", "/")
                resp = conn.getresponse()
                assert resp.status == 200
                conn.close()
                break
            except ConnectionRefusedError:
                time.sleep(0.1)
        else:
            raise AssertionError("server never came up")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# --- helpers: origin / host acceptance -------------------------------------


def test_origin_and_host_helpers():
    """_is_allowed_origin / _is_allowed_host accept loopback, reject others."""
    assert server._is_allowed_origin("http://127.0.0.1:8000", 8000)
    assert server._is_allowed_origin("http://localhost:8000", 8000)
    assert not server._is_allowed_origin("http://evil.example", 8000)
    assert not server._is_allowed_origin("http://127.0.0.1:9000", 8000)
    assert not server._is_allowed_origin("https://127.0.0.1:8000", 8000)
    assert server._is_allowed_host(None, 8000)  # absent Host is allowed
    assert server._is_allowed_host("127.0.0.1:8000", 8000)
    assert server._is_allowed_host("localhost:8000", 8000)
    assert not server._is_allowed_host("evil.example", 8000)
    assert not server._is_allowed_host("127.0.0.1:9000", 8000)
