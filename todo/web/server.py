"""HTTP server for the todo list (tracer bullet, hardened).

Stdlib-only. Renders the items loaded from ``todo.core.load_todos()`` as a
single HTML page. Done items are marked ``[x]``; an empty list shows the text
``No items``.

Hardening (learn_hermes-clq):

* Every rendered item id and item text is HTML-escaped with
  ``html.escape(..., quote=True)`` so stored text can never break out of the
  markup (``<script>`` renders as ``&lt;script&gt;``, ``"`` as ``&quot;``).
* ``/done/<id>`` and ``/delete/<id>`` ids must match ``^[0-9]{1,9}$``; a
  malformed id (letters, a sign, a decimal, or >9 digits) is a 400, while a
  well-formed id with no matching item is a 404.
* ``POST /add`` validates its request body before touching the filesystem:
  a non-urlencoded ``Content-Type`` is 415, a missing ``Content-Length`` is
  400, a body larger than 4096 bytes is 413 (checked *before* reading the
  body), non-UTF-8 bytes are 400, and text longer than 200 characters is 400.
* Unsupported methods (``PUT``, ``DELETE``, ``PATCH``, ``OPTIONS``, ``TRACE``)
  are a 405.
* Any unexpected exception -- including :class:`todo.core.CorruptDataFile` --
  yields a clean 500 HTML page saying ``Internal error`` with no traceback and
  no file path; the detail is logged to stderr only.
* Every error response (400/404/405/413/415/500) is a small HTML page that
  links back to ``/``.

Further hardening (learn_hermes-7p6):

* A ``Content-Length`` that is not a canonical non-negative decimal integer is
  a 400 -- a negative value (``-5``), a leading sign (``+5``), surrounding
  whitespace, or a stray character (``5x``) is rejected *before* the body is
  read, so it can never reach ``rfile.read`` as a bogus byte count.
* The request path is parsed with :func:`urllib.parse.urlsplit`, so a query
  string (``GET /?x=1``, ``POST /add?x=1``) is ignored and the route is
  matched on the path component only.
* Every POST is guarded against cross-origin form submission (CSRF): if an
  ``Origin`` header is present it must be the loopback origin served by this
  process, else 403; if it is absent but ``Sec-Fetch-Site`` is present that
  value must be ``same-origin`` or ``none``, else 403.
* Every request is guarded against DNS rebinding: a present ``Host`` header
  that is not ``127.0.0.1[:port]`` or ``localhost[:port]`` is a 403.
* The id routes use :func:`re.fullmatch` (not ``match`` with ``$``).

Design goals (kept minimal on purpose -- later issues add styling and README):

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
import sys
import urllib.parse

from todo import core

# Bind only to the loopback interface so the list is never exposed to a network.
LOOPBACK = "127.0.0.1"

# Default port when neither --port nor TODO_PORT is provided.
DEFAULT_PORT = 8000

# Environment variable (distinct from the CLI's) that selects the port.
PORT_ENV = "TODO_PORT"

# Largest request body we are willing to accept (bytes); checked before reading.
MAX_BODY = 4096

# Longest item text we accept (characters after URL-decoding and stripping).
MAX_TEXT = 200

# The one request body content type we accept for form posts.
_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

# A well-formed id path: 1-9 digits (captured). Anything else -- letters, a
# sign, a decimal, or >9 digits -- fails the fullmatch and is rejected as a
# 400. The capture group is the id we hand to core. Compiled once at import;
# anchored by fullmatch (no leading/trailing anchors) so the whole path must
# match, as the issue requires.
_DONE_ID_RE = re.compile(r"/done/([0-9]{1,9})")
_DELETE_ID_RE = re.compile(r"/delete/([0-9]{1,9})")

# A canonical Content-Length: only a non-negative decimal integer. A leading
# sign, surrounding whitespace, or a stray character is rejected (a bogus byte
# count must never reach rfile.read, which would raise an uncaught error).
_CONTENT_LENGTH_RE = re.compile(r"[0-9]+")

# Hosts/origins this loopback server is willing to serve. A request whose Host
# or Origin points anywhere else is a 403 (DNS-rebinding / CSRF defense).
_ALLOWED_HOSTS = ("127.0.0.1", "localhost")

# Sec-Fetch-Site values that are acceptable when Origin is absent.
_ALLOWED_SEC_FETCH_SITES = ("same-origin", "none")

# Minimal inline CSS, kept as one constant so it is injected into the <head> of
# the main page -- no external stylesheet, no CDN, no JS. It gives the page a
# readable font stack, a centered max-width container, completed items struck
# through, and styled form controls. It is deliberately free of any "http://" or
# "https://" so the page references nothing external.
_STYLE = """
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
    Helvetica, Arial, sans-serif;
  margin: 0;
  padding: 2rem;
  color: #1a1a1a;
  background: #fafafa;
}
.container {
  max-width: 40rem;
  margin: 0 auto;
}
h1 {
  margin-top: 0;
}
ul {
  list-style: none;
  padding: 0;
}
li {
  padding: 0.5rem 0;
  border-bottom: 1px solid #ececec;
}
li.done {
  text-decoration: line-through;
  color: #888;
}
form {
  margin: 0.5rem 0;
}
input[type=text],
input[type=submit] {
  font: inherit;
  padding: 0.25rem 0.5rem;
  border: 1px solid #ccc;
  border-radius: 4px;
}
input[type=submit] {
  background: #fff;
  cursor: pointer;
}
"""


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


def _parse_content_length(value):
    """Return the non-negative integer ``Content-Length`` or raise ``ValueError``.

    Only a canonical decimal integer is accepted: no leading sign, no
    surrounding whitespace, no stray characters. A negative value, a ``+``
    sign, or anything non-digit is rejected so the count can never be handed
    to ``rfile.read`` (which would raise an uncaught error and drop the
    connection).
    """
    if not isinstance(value, str) or not _CONTENT_LENGTH_RE.fullmatch(value):
        raise ValueError(f"bad Content-Length: {value!r}")
    return int(value)


def _is_allowed_host(host_header, port):
    """True when ``host_header`` names this loopback server.

    A present Host must be ``127.0.0.1[:port]`` or ``localhost[:port]`` (the
    port, when given, must match the bound port). An *absent* Host is allowed
    -- it is a degenerate, non-browser case (the test suite's raw
    ``skip_host=True`` requests), and rejecting it would break the missing
    Content-Length test, which never sends a Host header.
    """
    if host_header is None:
        return True
    host = host_header.strip()
    # Split an optional ":port"; strip IPv6 brackets if present.
    name, sep, given_port = host.partition(":")
    if name.startswith("["):
        name = name[1:-1]
    name = name.lower()
    if name not in _ALLOWED_HOSTS:
        return False
    if sep:
        return given_port == str(port)
    return True


def _is_allowed_origin(origin, port):
    """True when ``origin`` is this server's loopback origin.

    The scheme must be ``http`` (we serve http only), the host must be
    ``127.0.0.1`` or ``localhost``, and the port must match the bound port.
    """
    parts = urllib.parse.urlsplit(origin)
    if parts.scheme != "http":
        return False
    if parts.hostname not in _ALLOWED_HOSTS:
        return False
    if parts.port is None:
        return False
    return parts.port == int(port)


def render_page(items):
    """Render the todo list to an HTML document (a ``str``).

    Each item becomes ``<li>ID: text</li>``; a done item is prefixed with
    ``[x]``. An empty list renders the text ``No items`` instead of a list.
    Item ids and text are HTML-escaped with ``html.escape(..., quote=True)``
    so stored text cannot break out of the markup -- ``<script>`` renders as
    ``&lt;script&gt;`` and ``"`` as ``&quot;``.

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
        "  <input type=text name=text>\n"
        '  <input type=submit value="Add">\n'
        "</form>\n"
    )
    if not items:
        body = add_form + "<p>No items</p>"
    else:
        rows = []
        for item in items:
            box = "[x] " if item.get("done") else ""
            item_id = html.escape(str(item.get("id", "")), quote=True)
            text = html.escape(str(item.get("text", "")), quote=True)
            # Every item carries a "delete" form, whether done or not.
            delete_form = (
                f"<form method=post action=/delete/{item_id}>\n"
                '  <input type=submit value="Delete">\n'
                "</form>\n"
            )
            if item.get("done"):
                # A completed item has no "done" form -- nothing left to do --
                # but it can still be deleted. The ``class="done"`` is what the
                # inline CSS strikes it through.
                rows.append(
                    f'<li class="done">{box}{item_id}: {text}\n'
                    f"{delete_form}</li>"
                )
            else:
                done_form = (
                    f"<form method=post action=/done/{item_id}>\n"
                    '  <input type=submit value="Done">\n'
                    "</form>\n"
                )
                rows.append(
                    f"<li>{box}{item_id}: {text}\n{done_form}{delete_form}</li>"
                )
        body = add_form + "<ul>" + "".join(rows) + "</ul>"
    # Wrap the content in a centered, max-width container so the page reads
    # well on a wide screen.
    wrapped = f'<div class="container">\n{body}\n</div>\n'
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>todo</title>\n"
        f"<style>\n{_STYLE}\n</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>Todo</h1>\n"
        f"{wrapped}"
        "</body>\n"
        "</html>\n"
    )


def error_page(status, title, message):
    """Return a small HTML error page (a ``str``) linking back to ``/``.

    ``title`` and ``message`` are HTML-escaped so nothing we render can break
    out of the markup. The body deliberately carries no traceback or file
    path -- those are logged to stderr, never sent to the client.
    """
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{html.escape(str(title), quote=True)}</title>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{status} {html.escape(str(title), quote=True)}</h1>\n"
        f"<p>{html.escape(str(message), quote=True)}</p>\n"
        '<p><a href="/">Home</a></p>\n'
        "</body>\n"
        "</html>\n"
    )


class TodoHandler(http.server.BaseHTTPRequestHandler):
    """Serve the todo list and validate every request before touching disk."""

    # Silence the default per-request stderr logging; the web tracer bullet is
    # not an audit log and the noise hurts in tests.
    def log_message(self, *args):
        return None

    # --- GET -------------------------------------------------------------

    def do_GET(self):
        if not self._host_ok():
            self._send_error_page(403, "Forbidden", "Forbidden host")
            return
        path = urllib.parse.urlsplit(self.path).path
        if path != "/":
            self._send_error_page(404, "Not Found", "Not Found")
            return
        try:
            items = core.load_todos()
        except core.CorruptDataFile as exc:
            self._log_detail(f"GET {self.path}: corrupt data file: {exc}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        except Exception as exc:  # noqa: BLE001 - last-resort clean 500
            self._log_detail(f"GET {self.path}: unexpected error: {exc!r}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        page = render_page(items).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    # --- POST ------------------------------------------------------------

    def do_POST(self):
        """Handle form submissions, validating each before touching disk.

        A request is first rejected for a bad Host (403) and for a
        cross-origin submission (403); the path is then matched on its
        ``urlsplit`` path component so a query string is ignored.

        ``POST /add`` adds a new item from the ``text`` field and redirects to
        ``/`` (HTTP 303); its request body is validated first (see
        :meth:`_handle_add`). ``POST /done/<id>`` and ``POST /delete/<id>``
        mark/remove item ``<id>`` (reusing :func:`todo.core.mark_done` /
        :func:`todo.core.remove_item`) and redirect to ``/`` (303). A
        well-formed id with no matching item is a 404 and changes nothing on
        disk; a *malformed* id (anything not matching ``^[0-9]{1,9}$``) is a
        400.
        """
        if not self._host_ok():
            self._send_error_page(403, "Forbidden", "Forbidden host")
            return
        if not self._origin_ok():
            self._send_error_page(403, "Forbidden", "Cross-origin request")
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/add":
            self._handle_add()
            return
        if path.startswith("/done/"):
            match = _DONE_ID_RE.fullmatch(path)
            if match is None:
                self._send_error_page(400, "Bad Request", "Invalid id")
                return
            self._handle_done(int(match.group(1)))
            return
        if path.startswith("/delete/"):
            match = _DELETE_ID_RE.fullmatch(path)
            if match is None:
                self._send_error_page(400, "Bad Request", "Invalid id")
                return
            self._handle_delete(int(match.group(1)))
            return
        self._send_error_page(404, "Not Found", "Not Found")

    def _handle_add(self):
        """Validate the POST body, add the item, then redirect to ``/``.

        Body rules (checked in order, before touching the filesystem):
        a non-urlencoded ``Content-Type`` is 415; a missing ``Content-Length``
        is 400; a non-integer or negative ``Content-Length`` is 400; a body
        larger than :data:`MAX_BODY` bytes is 413 (checked before reading the
        body); non-UTF-8 bytes are 400; and item text longer than
        :data:`MAX_TEXT` characters (or empty) is 400.
        """
        content_type = self.headers.get("Content-Type", "")
        if _FORM_CONTENT_TYPE not in content_type:
            self._send_error_page(
                415, "Unsupported Media Type", "Unsupported Media Type"
            )
            return
        length = self.headers.get("Content-Length")
        if length is None:
            self._send_error_page(400, "Bad Request", "Missing Content-Length")
            return
        try:
            length = _parse_content_length(length)
        except ValueError:
            self._send_error_page(400, "Bad Request", "Bad Content-Length")
            return
        if length > MAX_BODY:
            # Reject before reading the body so a huge upload never fills a
            # buffer or is partially consumed.
            self._send_error_page(413, "Request Entity Too Large", "Request Too Large")
            return
        raw = self.rfile.read(length)
        try:
            fields = urllib.parse.parse_qs(raw.decode("utf-8"), errors="strict")
        except UnicodeDecodeError:
            # The body is not valid UTF-8 (either raw bytes or a bad
            # percent-escape like %ff).
            self._send_error_page(400, "Bad Request", "Invalid UTF-8 in request body")
            return
        values = fields.get("text")
        text = values[0] if values else ""
        text = text.strip()
        if not text:
            self._send_error_page(400, "Bad Request", "Missing 'text'")
            return
        if len(text) > MAX_TEXT:
            self._send_error_page(400, "Bad Request", "Text too long")
            return
        try:
            core.add_item(text)
        except core.CorruptDataFile as exc:
            self._log_detail(f"add: corrupt data file: {exc}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        except Exception as exc:  # noqa: BLE001 - last-resort clean 500
            self._log_detail(f"add: unexpected error: {exc!r}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        self._redirect_to("/")

    def _handle_done(self, item_id):
        """Mark item ``item_id`` done, then redirect to ``/``.

        An id with no matching item is a 404 -- nothing is written.
        """
        try:
            result = core.mark_done(item_id)
        except core.CorruptDataFile as exc:
            self._log_detail(f"done {item_id}: corrupt data file: {exc}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        except Exception as exc:  # noqa: BLE001 - last-resort clean 500
            self._log_detail(f"done {item_id}: unexpected error: {exc!r}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        if result is None:
            self._send_error_page(404, "Not Found", "No item with that id")
            return
        self._redirect_to("/")

    def _handle_delete(self, item_id):
        """Remove item ``item_id``, then redirect to ``/``.

        An id with no matching item is a 404 -- the file is left untouched.
        Remaining ids are not renumbered (that is :func:`core.remove_item`'s
        contract, which we reuse rather than reimplementing).
        """
        try:
            result = core.remove_item(item_id)
        except core.CorruptDataFile as exc:
            self._log_detail(f"delete {item_id}: corrupt data file: {exc}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        except Exception as exc:  # noqa: BLE001 - last-resort clean 500
            self._log_detail(f"delete {item_id}: unexpected error: {exc!r}")
            self._send_error_page(500, "Internal error", "Internal error")
            return
        if result is None:
            self._send_error_page(404, "Not Found", "No item with that id")
            return
        self._redirect_to("/")

    # --- Unsupported methods -> 405 --------------------------------------

    def _method_not_allowed(self):
        """405 for any HTTP method this handler does not implement."""
        self._send_error_page(405, "Method Not Allowed", "Method Not Allowed")

    # Map the methods we explicitly do not support to the 405 handler.
    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed

    # --- request guards --------------------------------------------------

    def _server_port(self):
        """The port this server is actually bound to (for origin/Host checks)."""
        return self.server.server_address[1]

    def _host_ok(self):
        """True unless a present ``Host`` header names a non-loopback host."""
        return _is_allowed_host(self.headers.get("Host"), self._server_port())

    def _origin_ok(self):
        """True unless the request looks like a cross-origin submission.

        If ``Origin`` is present it must be this server's loopback origin.
        Otherwise, if ``Sec-Fetch-Site`` is present it must be ``same-origin``
        or ``none``. A request with neither header is allowed (303 on success)
        so the existing form-submission tests keep working.
        """
        origin = self.headers.get("Origin")
        if origin is not None:
            return _is_allowed_origin(origin, self._server_port())
        sec_fetch_site = self.headers.get("Sec-Fetch-Site")
        if sec_fetch_site is not None:
            return sec_fetch_site.lower() in _ALLOWED_SEC_FETCH_SITES
        return True

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _log_detail(message):
        """Write a single line of error detail to stderr only."""
        sys.stderr.write(f"todo web: {message}\n")

    def _send_error_page(self, status, title, message):
        """Send a small HTML error page (with a link to ``/``) at ``status``."""
        body = error_page(status, title, message).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect_to(self, location):
        """Send a 303 See Other redirect to ``location``."""
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


def make_server(port, host=LOOPBACK):
    """Create an HTTP server bound to ``host:port`` with :class:`TodoHandler`.

    Passing ``port=0`` binds an ephemeral port; the assigned one is readable
    via ``server.server_address`` -- which is how the tests drive a real server
    without hardcoding a port.
    """
    return http.server.ThreadingHTTPServer((host, port), TodoHandler)
