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
import re
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
    create new items (see :meth:`TodoHandler.do_POST`). Every *not-done* item
    additionally carries its own "done" form (``<form method=post
    action=/done/<id>>`` with a submit button); done items show no "done"
    form. *Every* item -- done or not -- carries its own "delete" form
    (``<form method=post action=/delete/<id>>`` with a "Delete" submit
    button), since deleting is always allowed.
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
            # Every item carries a "delete" form, whether done or not.
            delete_form = (
                f"<form method=post action=/delete/{item_id}>\n"
                '  <input type=submit value="Delete">\n'
                "</form>\n"
            )
            if item.get("done"):
                # A completed item has no "done" form -- nothing left to do --
                # but it can still be deleted.
                rows.append(f"<li>{box}{item_id}: {text}\n{delete_form}</li>")
            else:
                done_form = (
                    f"<form method=post action=/done/{item_id}>\n"
                    '  <input type=submit value="Done">\n'
                    "</form>\n"
                )
                rows.append(f"<li>{box}{item_id}: {text}\n{done_form}{delete_form}</li>")
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
        nothing. ``POST /done/<id>`` marks item ``<id>`` complete
        (:func:`todo.core.mark_done`) and redirects to ``/`` (303); an unknown
        id -- one with no matching item, or a non-integer id -- is a 404 and
        changes nothing on disk. ``POST /delete/<id>`` removes item ``<id>``
        (:func:`todo.core.remove_item`) and redirects to ``/`` (303); an
        unknown id is a 404 and changes nothing on disk (remaining ids are not
        renumbered). Full clean error *pages* are a later issue; for now a
        303/400/404 status with a short body is enough.
        """
        if self.path == "/add":
            self._handle_add()
            return
        done_id = self._parse_done_id(self.path)
        if done_id is not None:
            self._handle_done(done_id)
            return
        delete_id = self._parse_delete_id(self.path)
        if delete_id is not None:
            self._handle_delete(delete_id)
            return
        self.send_error(404, "Not Found")

    def _handle_add(self):
        """Add a new item from the ``text`` field, then redirect to ``/``."""
        text = self._form_field("text")
        if text is None or not text.strip():
            self._send_simple(400, "Bad Request")
            return
        core.add_item(text.strip())
        self._redirect_to("/")

    def _handle_done(self, item_id):
        """Mark item ``item_id`` done, then redirect to ``/``.

        An id with no matching item is a 404 -- nothing is written.
        """
        if core.mark_done(item_id) is None:
            self._send_simple(404, "Not Found")
            return
        self._redirect_to("/")

    def _handle_delete(self, item_id):
        """Remove item ``item_id``, then redirect to ``/``.

        An id with no matching item is a 404 -- the file is left untouched.
        Remaining ids are not renumbered (that is :func:`core.remove_item`'s
        contract, which we reuse rather than reimplementing).
        """
        if core.remove_item(item_id) is None:
            self._send_simple(404, "Not Found")
            return
        self._redirect_to("/")

    # A path of the form /done/<integer id>; the captured id is the item id.
    _DONE_RE = re.compile(r"^/done/(\d+)$")

    def _parse_done_id(self, path):
        """Return the int id from a ``/done/<id>`` path, or ``None``.

        A non-integer id (e.g. ``/done/x``) yields ``None`` so the caller can
        404 it rather than crash.
        """
        match = self._DONE_RE.match(path)
        if match is None:
            return None
        return int(match.group(1))

    # A path of the form /delete/<integer id>; the captured id is the item id.
    _DELETE_RE = re.compile(r"^/delete/(\d+)$")

    def _parse_delete_id(self, path):
        """Return the int id from a ``/delete/<id>`` path, or ``None``.

        A non-integer id (e.g. ``/delete/x``) yields ``None`` so the caller
        can 404 it rather than crash.
        """
        match = self._DELETE_RE.match(path)
        if match is None:
            return None
        return int(match.group(1))

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
