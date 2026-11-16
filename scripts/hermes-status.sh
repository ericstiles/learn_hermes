#!/usr/bin/env bash
# hermes-status.sh — READ-ONLY snapshot of the Hermes agent loop.
#
# Usage: scripts/hermes-status.sh [--tests]
#   --tests   also run pytest on origin/main in a throwaway worktree (cleaned up)
# Env (all optional): HERMES_LOG_DIR=logs HERMES_LOG_LINES=30 HERMES_PR_LIMIT=8
#
# Never commits, pushes, pulls beads, or writes in the repo. Each section
# tolerates failure and prints "unavailable: <reason>".
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT" || exit 0
LOG_DIR=${HERMES_LOG_DIR:-logs}; LINES_N=${HERMES_LOG_LINES:-30}; PRS=${HERMES_PR_LIMIT:-8}
RUN_TESTS=0; [ "${1:-}" = "--tests" ] && RUN_TESTS=1
# shellcheck source=hermes-classify.sh
. "$ROOT/scripts/hermes-classify.sh"

hdr() { printf '\n== %s ==\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
try() { # try <label> cmd...  : run, print "unavailable" on failure
  local label=$1; shift
  if ! "$@" 2>&1; then echo "unavailable: $label failed"; fi
}

hdr "origin/main"
if have git; then
  git fetch --quiet 2>/dev/null || echo "unavailable: git fetch failed (offline?)"
  try "git log" git log origin/main --oneline -n 8
else echo "unavailable: git not found"; fi

hdr "pull requests"
if have gh; then try "gh pr list" gh pr list --state all --limit "$PRS"; else echo "unavailable: gh not found"; fi

hdr "beads (local copy; not synced by this script)"
if have bd; then
  echo "-- ready"; try "bd ready" bd ready
  echo "-- in progress"; try "bd list" bd list --status=in_progress
  echo "-- blocked"; try "bd blocked" bd blocked
  echo "-- all"; try "bd list --all" bd list --all
else echo "unavailable: bd not found"; fi

hdr "active run"
procs=$(ps -axo pid,etime,command 2>/dev/null | grep -E 'run-beads\.sh|hermes chat' | grep -v grep | cut -c1-140)
if [ -n "$procs" ]; then echo "RUNNING:"; echo "$procs"; ACTIVE=1; else echo "no run-beads.sh / hermes chat process"; ACTIVE=0; fi

hdr "latest log"
newest=$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -n 1)
if [ -n "$newest" ]; then
  age=$(( $(date +%s) - $(stat -f %m "$newest" 2>/dev/null || stat -c %Y "$newest" 2>/dev/null || date +%s) ))
  echo "file: $newest   last write: ${age}s ago"
  if [ "$ACTIVE" = 1 ] && [ "$age" -lt 1800 ]; then echo "class: RUNNING"; else echo "class: $(hermes_classify "$newest")"; fi
  echo "-- last $LINES_N lines"; tail -n "$LINES_N" "$newest" | tr -d '\r'
else echo "unavailable: no logs in $LOG_DIR"; fi

if [ "$RUN_TESTS" = 1 ]; then
  hdr "tests on origin/main (throwaway worktree)"
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/hermes-status.XXXXXX")
  cleanup() { git worktree remove --force "$tmp/wt" >/dev/null 2>&1; rm -rf "$tmp"; git worktree prune >/dev/null 2>&1; }
  trap cleanup EXIT
  if git worktree add -q --detach "$tmp/wt" origin/main 2>/dev/null; then
    ( cd "$tmp/wt" && python3 -m venv "$tmp/v" >/dev/null 2>&1 \
        && "$tmp/v/bin/pip" -q install pytest pytest-cov >/dev/null 2>&1 \
        && "$tmp/v/bin/python" -m pytest -q 2>&1 | tail -n 15 ) || echo "unavailable: test run failed"
  else echo "unavailable: could not create worktree"; fi
fi
exit 0
