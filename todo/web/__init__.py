"""Web UI package for the todo tracer bullet.

Serves the todo list over HTTP so a browser can view it. The data layer is
``todo.core``; this package only renders it. See ``todo/web/server.py``.
"""

from .server import TodoHandler, make_server, render_page, resolve_port

__all__ = ["TodoHandler", "make_server", "render_page", "resolve_port"]
