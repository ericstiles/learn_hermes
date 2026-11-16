"""Styling and README tests for the web UI (issue learn_hermes-154).

These cover the acceptance criteria for "Web UI: styling and README section
with real output":

1. GET / carries an inline ``<style>`` block and references no external
   ``http://``/``https://`` resource (no CDN, no JS, no external assets).
2. A done item's markup carries the ``line-through`` that the CSS applies to a
   done item (the test asserts the substring, so a done item must be marked in
   a way the stylesheet can target -- here a ``class="done"`` on the ``<li>``
   plus a ``.done { text-decoration: line-through; }`` rule).
3. ``README.md`` has a ``Web UI`` section naming ``python3 -m todo.web``,
   ``TODO_PORT`` and ``TODO_FILE``.
4. The README shows real captured output -- the exact ``curl -i`` command and
   its real response status line, plus a ``POST /add`` returning ``303`` --
   none of it invented.
5. The existing tests keep passing and coverage stays >= 80% (that last part is
   enforced by the suite runner, not here).
"""

import http.client
import os
import threading
from pathlib import Path

from todo import core
from todo.web import server

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"


def _start_server(todo_file, port=0, items=None):
    """Start make_server() on a background thread against a temp TODO_FILE.

    Mirrors the helpers in the other web tests: the server runs in-process, so
    it reads the *process* environment -- we set TODO_FILE in os.environ for
    the lifetime of the server and restore it on shutdown.
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


def _get(host, port, path):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    return resp.status, resp.headers, body, conn


# --- criterion 1: inline <style>, no external references -------------------


def test_get_root_has_inline_style_block(tmp_path):
    """The served page carries an inline <style> block."""
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        status, _headers, body, conn = _get(host, port, "/")
        conn.close()
        assert status == 200
        assert "<style" in body
        # A matching close tag, too.
        assert "</style>" in body
    finally:
        _stop(s, t)


def test_get_root_has_no_external_references(tmp_path):
    """No external assets: no http:// or https:// anywhere in the page.

    That means no CDN, no external JS, no external stylesheet -- everything is
    inline.
    """
    s, t, host, port = _start_server(tmp_path / "todos.json", items=[])
    try:
        status, _headers, body, conn = _get(host, port, "/")
        conn.close()
        assert status == 200
        assert "http://" not in body
        assert "https://" not in body
    finally:
        _stop(s, t)


def test_render_page_has_style(tmp_path):
    """render_page() itself embeds the <style> block."""
    page = server.render_page([])
    assert "<style" in page
    assert "</style>" in page


# --- criterion 2: done items get line-through -----------------------------


def test_done_item_has_line_through(tmp_path):
    """A done item's markup carries the line-through the CSS applies.

    The done item is marked ``class="done"`` and the stylesheet carries a
    ``.done { text-decoration: line-through; }`` rule, so a completed item is
    struck through in any browser.
    """
    s, t, host, port = _start_server(
        tmp_path / "todos.json",
        items=[
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": True},
        ],
    )
    try:
        status, _headers, body, conn = _get(host, port, "/")
        conn.close()
        assert status == 200
        # The line-through comes from a CSS rule targeting the done items.
        assert "line-through" in body
        # And the done item is actually marked so the rule applies to it.
        assert 'class="done"' in body
    finally:
        _stop(s, t)


def test_render_page_marks_done_item(tmp_path):
    """render_page() marks a done <li> with class="done"."""
    page = server.render_page(
        [
            {"id": 1, "text": "alpha", "done": False},
            {"id": 2, "text": "beta", "done": True},
        ]
    )
    assert "line-through" in page
    assert 'class="done"' in page


# --- criterion 3: README has a Web UI section -----------------------------


def test_readme_has_web_ui_section():
    """README.md carries a 'Web UI' section naming the start command and env."""
    readme = README.read_text(encoding="utf-8")
    assert "Web UI" in readme
    assert "python3 -m todo.web" in readme
    assert "TODO_PORT" in readme
    assert "TODO_FILE" in readme


# --- criterion 4: README shows real captured output -----------------------


def test_readme_shows_real_curl_output():
    """The README documents the exact curl command and its real status line.

    It must show a `curl -i` invocation and a real 200 response status line,
    plus a POST /add that returns 303 -- all output that was actually captured
    by running the server, not invented.
    """
    readme = README.read_text(encoding="utf-8")
    assert "curl -i" in readme
    # A real 200 status line captured from the GET / response.
    assert "HTTP/1.0 200" in readme
    # And a POST /add that returns 303 (the redirect).
    assert "303" in readme
    assert "/add" in readme
