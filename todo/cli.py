"""Command-line interface for the todo tracer bullet.

Commands:
  todo add <text>   Append a new item, persisted to the JSON data file.
  todo list         Print items as "<id> [ ] text" (one per line).

The data file path is read from the TODO_FILE env var (see core.TODO_ENV).
"""

import argparse
import sys

from .core import add_item, load_todos, mark_done


def cmd_add(args):
    """Handle `todo add <text...>`."""
    text = " ".join(args.text).strip()
    if not text:
        print("error: no text given", file=sys.stderr)
        return 1
    item = add_item(text)
    print(f"added {item['id']}: {item['text']}")
    return 0


def cmd_list(args):
    """Handle `todo list` -> prints "<id> [x ] text" per item."""
    items = load_todos()
    for item in items:
        box = "x" if item.get("done") else " "
        print(f"{item['id']} [{box}] {item['text']}")
    return 0


def cmd_done(args):
    """Handle `todo done <id>` -> mark an item complete."""
    try:
        item_id = int(args.id)
    except ValueError:
        print(f"error: invalid id {args.id!r}", file=sys.stderr)
        return 1
    item = mark_done(item_id)
    if item is None:
        print(f"error: no item with id {item_id}", file=sys.stderr)
        return 1
    print(f"done {item['id']}: {item['text']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="todo",
        description="A tiny CLI todo list (tracer bullet).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a new item")
    p_add.add_argument("text", nargs="+", help="text of the new item")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="list all items")
    p_list.set_defaults(func=cmd_list)

    p_done = sub.add_parser("done", help="mark an item complete")
    p_done.add_argument("id", help="id of the item to mark done")
    p_done.set_defaults(func=cmd_done)

    return parser


def main(argv=None):
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
