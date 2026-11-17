"""`python -m todo.web` entry point.

Serves the todo list on 127.0.0.1. The port comes from --port, else the
TODO_PORT env var, else 8000. The data file comes from TODO_FILE
(see todo.core.data_file()).
"""

import argparse
import sys

from .server import DEFAULT_PORT, LOOPBACK, make_server, resolve_port


def build_parser():
    parser = argparse.ArgumentParser(
        prog="todo.web",
        description="Serve the todo list over HTTP on 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port to bind (default: TODO_PORT env, else {DEFAULT_PORT})",
    )
    return parser


def main(argv=None):
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    port = resolve_port(args.port)
    server = make_server(port, LOOPBACK)
    # flush=True so the "serving on" line appears promptly when stdout is a
    # pipe (e.g. a CI log or a test that waits for it) instead of being
    # buffered until the process exits.
    print(f"todo web serving on http://{LOOPBACK}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
