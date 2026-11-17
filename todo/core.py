"""Core data layer for the todo tracer bullet.

Storage: a single JSON file (path from the TODO_FILE env var, else
./todos.json). The file holds a JSON array of items, each an object with the
shape ``{"id": int, "text": str, "done": bool}``. Ids are stable positive
integers starting at 1.
"""

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path

# fcntl provides the process-level file lock (flock) on POSIX. It is guarded
# so that on a platform without it (e.g. Windows) the code still works using
# only the thread-level lock below -- the process-level lock is simply skipped.
try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

# Environment variable that overrides the default data file location so tests
# can use a temp file and users can keep separate lists per context.
TODO_ENV = "TODO_FILE"

# Default location when TODO_FILE is not set.
DEFAULT_TODO_FILE = "todos.json"

# Serialize a whole read-modify-write across threads in *this* process. One
# data file is in use per process (the TODO_FILE env var), so a single
# module-level lock is enough for the thread case; the process-level flock in
# :func:`_write_lock` handles races between *different* processes.
_thread_lock = threading.Lock()


class CorruptDataFile(Exception):
    """The data file exists but cannot be loaded safely.

    Raised by :func:`load_todos` when the file is present but its contents are
    not parseable JSON, not the expected array shape, or unreadable. The CLI
    catches this and reports it as a single clean stderr line with a non-zero
    exit -- never a traceback. A *missing* file is deliberately *not* corrupt
    (it just means "no data yet" on a fresh run), so it is not raised here.
    """

    def __init__(self, message, path=None):
        self.path = path
        super().__init__(message)


def data_file():
    """Return the Path to the data file, honoring the TODO_FILE env var."""
    override = os.environ.get(TODO_ENV)
    return Path(override) if override else Path(DEFAULT_TODO_FILE)


@contextlib.contextmanager
def _write_lock(path=None):
    """Serialize a whole read-modify-write across threads *and* processes.

    Two layers, held for the entire duration of the block:

    * a module-level :class:`threading.Lock` (:data:`_thread_lock`) guards
      against concurrent threads writing the same data file in this process;
    * an :func:`fcntl.flock` exclusive lock on a ``<data file>.lock`` sidecar
      guards against *other* processes doing the same. The sidecar lives in
      the same directory as the data file so the flock and the data are on the
      same filesystem. On a platform without ``fcntl`` only the thread lock is
      taken (the process-level lock is skipped).
    """
    target = Path(path) if path is not None else data_file()
    with _thread_lock:
        if fcntl is None:
            # No process-level lock available; the thread lock suffices.
            yield
            return
        # The sidecar lock must sit beside the data file, so make sure its
        # parent directory exists first (a fresh TODO_FILE may not have one).
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_path = str(target) + ".lock"
        # A fresh open per lock so the flock is tied to this open file
        # description; the thread lock guarantees only one thread is here at a
        # time, so the blocking flock can never self-deadlock.
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def load_todos(path=None):
    """Load items from the JSON file.

    A *missing* file or a *blank* file yields ``[]`` so that ``list`` and
    ``add`` both work on a fresh checkout (the data simply does not exist
    yet). A file that *exists but is unusable* -- malformed JSON, not the
    expected array/``{"items": [...]}`` shape, an I/O error reading it, or an
    entry that is not a well-formed item (non-object entry, non-positive-integer
    id, non-string text, non-boolean done) -- is raised as
    :class:`CorruptDataFile` so the caller can report it cleanly instead of
    crashing with a traceback. Malformed entries are never silently dropped.
    """
    p = Path(path) if path is not None else data_file()
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError as exc:
        # The file exists but we cannot read it (permissions, is a directory,
        # ...). Treat that as corruption rather than a clean empty start.
        raise CorruptDataFile(
            f"error: cannot read data file {p!s} ({exc.strerror or exc})", p
        )
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CorruptDataFile(
            f"error: data file {p!s} is not valid JSON ({exc.msg})", p
        )
    # Accept either a bare list of items or {"items": [...]}.
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        raise CorruptDataFile(
            f"error: data file {p!s} does not contain a JSON array of items", p
        )
    # Validate every entry. A damaged file (a non-object entry, a non-positive-
    # integer id, a non-string text, or a non-boolean done) is raised as
    # :class:`CorruptDataFile` -- never silently dropped or type-coerced. The
    # old int()/bool() coercion crashed on a non-int id and rendered done:"false"
    # (a string) as done because bool("false") is True; strict validation fixes
    # both. A one-line message names the file and the offending entry index.
    items = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise CorruptDataFile(
                f"error: data file {p!s} entry index {index} is not an object",
                p,
            )
        item_id = entry.get("id")
        # bool is a subclass of int, so exclude it explicitly: id True/False is
        # not a valid id. id must be a real positive int (>= 1).
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
            raise CorruptDataFile(
                f"error: data file {p!s} entry index {index} has an invalid id "
                f"{item_id!r} (must be a positive integer)",
                p,
            )
        # 'text' is optional in the JSON but, when present, must be a string.
        # Missing 'done' defaults to False; a present 'done' must be a real bool
        # (not the string "false"/"true", which coerce truthily).
        if "text" in entry and not isinstance(entry["text"], str):
            raise CorruptDataFile(
                f"error: data file {p!s} entry index {index} has a non-string "
                f"text {entry['text']!r}",
                p,
            )
        done = entry.get("done", False)
        if not isinstance(done, bool):
            raise CorruptDataFile(
                f"error: data file {p!s} entry index {index} has a non-boolean "
                f"done {done!r}",
                p,
            )
        items.append(
            {
                "id": item_id,
                "text": entry.get("text", ""),
                "done": done,
            }
        )
    return items


def save_todos(items, path=None):
    """Persist items to the JSON file, creating parent dirs as needed.

    The write is *atomic*: the new contents are written to a temporary file in
    the *same directory* as the target, flushed to disk, and then swapped into
    place with :func:`os.replace`. A reader therefore never observes a
    half-written file, and a crash (or a failed ``os.replace``) leaves the
    previous contents intact instead of truncating them. Writing to the same
    directory is what keeps the ``os.replace`` a single atomic rename on the
    same filesystem.
    """
    p = Path(path) if path is not None else data_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    # The temp file shares the target's directory (same filesystem) so that the
    # final os.replace is an atomic rename rather than a cross-device copy.
    fd, tmp_name = tempfile.mkstemp(
        prefix=".todos-", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(json.dumps(items, indent=2) + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, str(p))
    except BaseException:
        # On any failure, clean up the temp file so a crash never leaves a
        # stray .tmp behind; the target file is never touched by a failed save.
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise


def next_id(items):
    """Next stable integer id: 1 when empty, else max(existing) + 1."""
    ids = [it["id"] for it in items if isinstance(it.get("id"), int)]
    return (max(ids) + 1) if ids else 1


def add_item(text, path=None):
    """Append a new item and return the new item dict (persisted).

    The whole read-modify-write (load -> assign the next id -> save) is
    serialized by :func:`_write_lock` so concurrent callers can neither lose
    updates nor hand two items the same id.
    """
    with _write_lock(path):
        items = load_todos(path)
        item = {"id": next_id(items), "text": text, "done": False}
        items.append(item)
        save_todos(items, path)
        return item


def mark_done(item_id, path=None):
    """Mark the item with ``item_id`` complete and persist.

    Returns the updated item dict, or ``None`` when no item has that id.
    (Unknown-id *error reporting* is owned by the validation issue; the core
    contract is simply "update if present, else no-op".)

    The read-modify-write is serialized by :func:`_write_lock`.
    """
    with _write_lock(path):
        items = load_todos(path)
        for item in items:
            if item["id"] == item_id:
                item["done"] = True
                save_todos(items, path)
                return item
        return None


def remove_item(item_id, path=None):
    """Delete the item with ``item_id`` and persist.

    Returns the removed item dict, or ``None`` when no item has that id.
    Remaining ids are left unchanged -- deletion does *not* renumber, so a gap
    is expected (e.g. removing 2 from [1,2,3] leaves [1,3]). The core contract
    is "delete if present, else no-op"; unknown-id *error reporting* is owned
    by the validation issue.

    The read-modify-write is serialized by :func:`_write_lock`.
    """
    with _write_lock(path):
        items = load_todos(path)
        kept, removed = [], None
        for item in items:
            if item["id"] == item_id and removed is None:
                removed = item  # remove only the first matching id
            else:
                kept.append(item)
        if removed is None:
            return None  # no item matched -> no-op, nothing written
        save_todos(kept, path)
        return removed
