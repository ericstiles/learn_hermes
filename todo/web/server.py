"""HTTP server for the todo list (tracer bullet).

Stdlib-only. Renders the items loaded from ``todo.core.load_todos()`` as a
single HTML page. Done items are marked ``[x]``; an empty list shows the text
``No items``.

Design goals (kept minimal on purpose -- later issues add forms, escaping,
error handling, and styling):

* A handler class (:class:`TodoHandler`) so it plugs into ``http.server``.
* A :func:`make_server` helper taking a port so tests can bind an ephemeral
  port (``port=0``) and read the assigned one back.
* :func:`resolve_port` centralizes port resolution (``--port`` > ``TODO_PORT``
  > default 8000).
"""

import html
import http.server
import os

from todo import core

# Bind only to the loopback interface so the list is never exposed to a network.
LOOPBACK = "127.0.0.1"

# Default port when neither --port nor TODO_PORT is provided.
DEFAULT_PORT = 8000

# Environment variable (distinct from the CLI's) that selects the port.
PORT_ENV = "TODO_PORT"


def resolve_port(arg, env=None):
    """Resolve the port to bind.

    Precedence: an explicit ``arg`` (the ``--port`` value) wins; else the
    ``TODO_PORT`` environment variable; else :data:`DEFAULT_PORT`.
    """
    if arg is not None:
        return int(arg)
    if env is None:
        env = os.environ
    override = env.get(PORT_ENV)
    if override:
        return int(override)
    return DEFAULT_PORT


def render_page(items):
    """Render the todo list to an HTML document (a ``str``).

    Each item becomes ``<li>ID: text</li>``; a done item is prefixed with
    ``[x]``. An empty list renders the text ``No items`` instead of a list.
    Item text is HTML-escaped so it cannot break out of the markup.
    """
    if not items:
        body = "<p>No items</p>"
    else:
        rows = []
        for item in items:
            box = "[x] " if item.get("done") else ""
            item_id = html.escape(str(item.get("id", "")))
            text = html.escape(str(item.get("text", "")))
            rows.append(f"<li>{box}{item_id}: {text}</li>")
        body = "<ul>" + "".join(rows) + "</ul>"
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>todo</title>\n"
        "</head>\n"
        "<body>\n"
        "<h1>Todo</h1>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


class TodoHandler(http.server.BaseHTTPRequestHandler):
    """Serves the todo list at ``/`` and 404s everything else."""

    # Silence the default per-request stderr logging; the web tracer bullet is
    # not an audit log and the noise hurts in tests.
    def log_message(self, *args):
        return None

    def do_GET(self):
        if self.path != "/":
            self.send_error(404, "Not Found")
            return
        items = core.load_todos()
        page = render_page(items).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


def make_server(port, host=LOOPBACK):
    """Create an HTTP server bound to ``host:port`` with :class:`TodoHandler`.

    Passing ``port=0`` binds an ephemeral port; the assigned one is readable
    via ``server.server_address`` -- which is how the tests drive a real server
    without hardcoding a port.
    """
    return http.server.ThreadingHTTPServer((host, port), TodoHandler)
