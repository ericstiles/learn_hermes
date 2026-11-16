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
import urllib.parse

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

    The page also carries an "add" form (``<form method=post action=/add>``)
    with a text input named ``text`` and a submit button, so a browser can
    create new items (see :meth:`TodoHandler.do_POST`).
    """
    add_form = (
        "<form method=post action=/add>\n"
        '  <input type=text name=text>\n'
        '  <input type=submit value="Add">\n'
        "</form>\n"
    )
    if not items:
        body = add_form + "<p>No items</p>"
    else:
        rows = []
        for item in items:
            box = "[x] " if item.get("done") else ""
            item_id = html.escape(str(item.get("id", "")))
            text = html.escape(str(item.get("text", "")))
            rows.append(f"<li>{box}{item_id}: {text}</li>")
        body = add_form + "<ul>" + "".join(rows) + "</ul>"
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

    def do_POST(self):
        """Handle form submissions.

        ``POST /add`` adds a new item from the ``text`` field and redirects to
        ``/`` (HTTP 303). Empty/blank text is rejected with 400 and adds
        nothing. Full clean error *pages* are a later issue; for now a 303/400
        status with a short body is enough.
        """
        if self.path != "/add":
            self.send_error(404, "Not Found")
            return
        text = self._form_field("text")
        if text is None or not text.strip():
            self._send_simple(400, "Bad Request")
            return
        core.add_item(text.strip())
        self._redirect_to("/")

    def _form_field(self, name):
        """Return the value of ``name`` from an x-www-form-urlencoded body.

        Returns ``None`` when the field is absent. The body length comes from
        the ``Content-Length`` header; a missing/zero body yields no fields.
        """
        length = self.headers.get("Content-Length")
        if not length:
            return None
        raw = self.rfile.read(int(length))
        parsed = urllib.parse.parse_qs(raw.decode("utf-8"))
        values = parsed.get(name)
        if not values:
            return None
        return values[0]

    def _redirect_to(self, location):
        """Send a 303 See Other redirect to ``location``."""
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _send_simple(self, status, message):
        """Send a short plain-text response body with ``status``."""
        body = f"{status} {message}\n".encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(port, host=LOOPBACK):
    """Create an HTTP server bound to ``host:port`` with :class:`TodoHandler`.

    Passing ``port=0`` binds an ephemeral port; the assigned one is readable
    via ``server.server_address`` -- which is how the tests drive a real server
    without hardcoding a port.
    """
    return http.server.ThreadingHTTPServer((host, port), TodoHandler)
