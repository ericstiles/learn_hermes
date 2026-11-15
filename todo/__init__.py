"""todo package: a tiny CLI todo list (tracer bullet).

Stdlib only. The data file path is overridable via the TODO_FILE environment
variable so tests (and users) can point at a temp file.
"""

from .core import TODO_ENV, add_item, load_todos, mark_done, save_todos

__all__ = ["TODO_ENV", "add_item", "load_todos", "mark_done", "save_todos"]
