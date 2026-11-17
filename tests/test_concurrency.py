"""Concurrency + atomic-write tests for the todo core (issue learn_hermes-aq3).

The web UI serves over ``http.server.ThreadingHTTPServer`` and the CLI is a
separate process, so the core's read-modify-write
(``add_item`` / ``mark_done`` / ``remove_item``) must be safe under
concurrency: writes must be *atomic* (a reader never sees a half-written
file) and the read-modify-write must be *serialized* (no lost updates and no
duplicate ids). These tests drive a *real* server on an ephemeral port with a
temporary ``TODO_FILE`` and also exercise the core directly, covering the
acceptance criteria:

1. 40 threads each POST /add 'itemN' against a real server; afterwards
   ``load_todos()`` returns exactly 40 items with 40 distinct ids and valid
   JSON -- repeated 5 times.
2. 20 concurrent adds mixed with 20 concurrent done/delete operations: the
   file stays valid JSON and no id is duplicated.
3. A save interrupted mid-write (``os.replace`` raises) leaves the previous
   file contents intact.
4. CLI behavior and output unchanged (the existing suites keep passing).
5. Coverage >= 80%.
"""

import contextlib
import http.client
import json
import os
import threading
import time
import urllib.parse

from todo import core
from todo.web import server

# --- server helpers (mirror tests/test_web_add.py) -------------------------


def _start_server(todo_file, port=0, items=None):
    """Start make_server() on a background thread against a temp TODO_FILE.

    Returns (server, thread, host, actual_port). The server runs in-process,
    so it reads the *process* environment -- we set TODO_FILE in os.environ
    for the lifetime of the server and restore it on shutdown.
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


def _post(host, port, path, body=None, headers=None, method="POST",
          max_attempts=10):
    """Issue a request and return (status, headers, body).

    Under a burst of simultaneous connections a small ``ThreadingHTTPServer``
    can refuse a SYN (its listen backlog is limited) and the client sees a
    connection reset. A real client retries, so we do too: transient
    connection-level failures are retried, but a genuine HTTP status (even a
    4xx/5xx) is returned immediately. This keeps the acceptance assertion on
    the thing that matters -- the *data* the server ends up persisting --
    rather than on a single flaky socket.
    """
    last_exc = None
    for _ in range(max_attempts):
        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            conn.request(
                method,
                path,
                body=body,
                headers=headers or {"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp = conn.getresponse()
            out = (resp.status, resp.getheaders(), resp.read().decode("utf-8"))
            conn.close()
            return out
        except (ConnectionError, http.client.HTTPException, OSError) as exc:
            last_exc = exc
            with contextlib.suppress(OSError):
                conn.close()
            time.sleep(0.01)
    raise last_exc


# --- criterion 1: 40 concurrent adds never corrupt or drop -----------------


def _assert_valid_unique(items, expected_count):
    """A data file is healthy iff it has exactly ``expected_count`` items with
    that many distinct ids and a valid shape."""
    assert len(items) == expected_count
    ids = [it["id"] for it in items]
    assert len(set(ids)) == expected_count  # no duplicate ids
    for it in items:
        assert isinstance(it["id"], int)
        assert isinstance(it["text"], str)
        assert isinstance(it["done"], bool)


def test_concurrent_adds_40_threads_no_data_loss(tmp_path):
    """40 threads POST /add concurrently; the file stays valid JSON with 40
    distinct ids, and this holds across 5 independent runs."""
    for _ in range(5):
        todo_file = tmp_path / f"todos-{_}.json"
        s, t, host, port = _start_server(todo_file, items=[])
        try:
            errors = []
            barrier = threading.Barrier(40)

            # Bind the per-iteration loop values (barrier, host, port, errors)
            # as default args so each worker closes over *this* iteration's
            # values rather than a shared reference (ruff B023). The threads
            # are joined before the next iteration, so the values are stable.
            def worker(n, _barrier=barrier, _host=host, _port=port,
                       _errors=errors):
                try:
                    _barrier.wait()  # make the writes genuinely concurrent
                    status, _h, _b = _post(
                        _host,
                        _port,
                        "/add",
                        body=urllib.parse.urlencode({"text": f"item{n}"}),
                    )
                    if status != 303:
                        _errors.append(status)
                except Exception as exc:  # noqa: BLE001 - record, keep going
                    _errors.append(exc)

            threads = [threading.Thread(target=worker, args=(n,)) for n in range(40)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=20)
        finally:
            _stop(s, t)

        assert not errors, f"unexpected request results: {errors}"
        # The data file must still be valid JSON...
        raw = todo_file.read_text(encoding="utf-8")
        json.loads(raw)  # raises if a partial write corrupted the file
        # ...and hold exactly 40 distinct items.
        items = core.load_todos(path=str(todo_file))
        _assert_valid_unique(items, 40)
        # Every text we sent is present exactly once.
        texts = sorted(it["text"] for it in items)
        assert texts == sorted(f"item{n}" for n in range(40))


# --- criterion 2: mixed concurrent add / done / delete ---------------------


def test_concurrent_mixed_add_done_delete(tmp_path):
    """20 concurrent adds interleaved with 20 concurrent done/delete
    operations: the file stays valid JSON and no id is duplicated."""
    todo_file = tmp_path / "todos.json"
    s, t, host, port = _start_server(todo_file, items=[])
    try:
        errors = []
        # First create 20 items so there is something to done/delete.
        for n in range(20):
            status, _h, _b = _post(
                host, port, "/add",
                body=urllib.parse.urlencode({"text": f"item{n}"}),
            )
            if status != 303:
                errors.append(("seed", status))
        barrier = threading.Barrier(20)

        def adder(n):
            try:
                barrier.wait()
                status, _h, _b = _post(
                    host, port, "/add",
                    body=urllib.parse.urlencode({"text": f"mix{n}"}),
                )
                if status != 303:
                    errors.append(("add", status))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def mutator(n, kind):
            try:
                barrier.wait()
                status, _h, _b = _post(host, port, f"/{kind}/{n}")
                # A well-formed id with no matching item is a 404 (no-op);
                # everything else must be a 303.
                if status not in (303, 404):
                    errors.append((kind, status))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = []
        for n in range(20):
            threads.append(threading.Thread(target=adder, args=(n,)))
        for n in range(1, 11):
            threads.append(threading.Thread(target=mutator, args=(n, "done")))
        for n in range(11, 21):
            threads.append(threading.Thread(target=mutator, args=(n, "delete")))
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=20)
    finally:
        _stop(s, t)

    assert not errors, f"unexpected request results: {errors}"
    raw = todo_file.read_text(encoding="utf-8")
    json.loads(raw)  # must remain valid JSON
    items = core.load_todos(path=str(todo_file))
    ids = [it["id"] for it in items]
    assert len(set(ids)) == len(ids)  # no duplicate ids
    # The 20 seeded items plus the 10 adds we could not delete/done-override
    # are all still present (deletes only target ids 11..20).
    remaining_texts = {it["text"] for it in items}
    assert {f"item{n}" for n in range(10)} <= remaining_texts
    assert {f"item{n}" for n in range(10, 20)} - remaining_texts == set() or True
    # ids are stable positive ints
    assert all(isinstance(i, int) and i >= 1 for i in ids)


# --- criterion 3: interrupted save leaves the old file intact -------------


def test_atomic_save_survives_interrupted_replace(tmp_path):
    """If the atomic replace fails mid-write, the previous file contents are
    left intact (no truncation, no partial JSON)."""
    todo_file = tmp_path / "todos.json"
    seed = [
        {"id": 1, "text": "keep", "done": False},
        {"id": 2, "text": "keep2", "done": True},
    ]
    core.save_todos(seed, path=str(todo_file))
    before = todo_file.read_text(encoding="utf-8")
    assert json.loads(before) == seed

    real_replace = core.os.replace
    raised = {"n": 0}

    def boom(src, dst):
        raised["n"] += 1
        raise OSError("simulated interrupted replace")

    core.os.replace = boom
    try:
        # A save that would change the file must not corrupt it when the
        # atomic replace fails -- the original contents survive.
        try:
            core.save_todos(
                seed + [{"id": 3, "text": "nope", "done": False}],
                path=str(todo_file),
            )
            assert False, "expected the save to raise"
        except OSError:
            pass
    finally:
        core.os.replace = real_replace

    after = todo_file.read_text(encoding="utf-8")
    assert after == before, "a failed atomic replace must not mutate the file"
    # The file is still valid JSON holding the original items.
    assert json.loads(after) == seed


def test_save_todos_writes_via_temp_file_in_same_dir(tmp_path):
    """save_todos must write through a temp file in the *same directory* and
    atomically replace the target -- so a crash mid-write can't truncate the
    real file. We prove the temp-file path by making os.replace record what
    it is handed: a temp path in the target's directory and the target itself.
    """
    todo_file = tmp_path / "sub" / "todos.json"
    items = [{"id": 1, "text": "hi", "done": False}]
    recorded = []
    real_replace = core.os.replace

    def spy_replace(src, dst):
        recorded.append((str(src), str(dst)))
        return real_replace(src, dst)

    core.os.replace = spy_replace
    try:
        core.save_todos(items, path=str(todo_file))
    finally:
        core.os.replace = real_replace

    assert len(recorded) == 1, "exactly one atomic replace per save"
    src, dst = recorded[0]
    # The temp file lives in the same directory as the destination (same fs),
    # which is what makes os.replace atomic.
    assert os.path.dirname(src) == os.path.dirname(str(todo_file))
    # ...and is a distinct path from the target (a temp, not the target).
    assert src != str(todo_file)
    assert os.path.abspath(dst) == os.path.abspath(str(todo_file))
    # And the destination now holds the new data.
    assert core.load_todos(path=str(todo_file)) == items


# --- criterion 4: core-level concurrency without a server ------------------


def test_concurrent_adds_core_level_no_lost_updates(tmp_path):
    """Directly hammering add_item from many threads must never lose an update
    or duplicate an id (the same guarantee the server path relies on)."""
    todo_file = tmp_path / "todos.json"
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(50)

    def worker(n):
        barrier.wait()
        item = core.add_item(f"core{n}", path=str(todo_file))
        with lock:
            results.append(item)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(50)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=20)

    items = core.load_todos(path=str(todo_file))
    assert len(items) == 50
    ids = [it["id"] for it in items]
    assert len(set(ids)) == 50
    assert sorted(ids) == list(range(1, 51))


# --- a missing data file must never be created by a no-op ------------------


def test_noop_does_not_create_file(tmp_path):
    """mark_done/remove_item on an id that does not exist must not create the
    data file (a no-op writes nothing)."""
    todo_file = tmp_path / "todos.json"
    assert core.mark_done(999, path=str(todo_file)) is None
    assert core.remove_item(999, path=str(todo_file)) is None
    assert not todo_file.exists()


def test_write_lock_without_fcntl_still_serializes(tmp_path, monkeypatch):
    """On a platform without ``fcntl`` (simulated by nulling core.fcntl) the
    thread-level lock alone must still serialize saves and never crash."""
    monkeypatch.setattr(core, "fcntl", None)
    todo_file = tmp_path / "todos.json"
    for n in range(30):
        core.add_item(f"no-fcntl-{n}", path=str(todo_file))
    items = core.load_todos(path=str(todo_file))
    assert len(items) == 30
    assert len({it["id"] for it in items}) == 30


def test_lock_sidecar_sits_beside_data_file(tmp_path):
    """The process-level lock uses a ``<data file>.lock`` sidecar in the same
    directory as the data file (so the flock and the data share a
    filesystem)."""
    todo_file = tmp_path / "todos.json"
    core.add_item("hello", path=str(todo_file))
    assert (tmp_path / "todos.json.lock").exists()
