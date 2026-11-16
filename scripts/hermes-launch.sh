#!/usr/bin/env bash
# hermes-launch.sh — start run-beads.sh in a herdr tab named "hermes-run"
# (fallback: detached tmux session "hermes-run"). Refuses if a run is active.
#
# Usage: scripts/hermes-launch.sh [--timeout 120m] [--reason CLASS] [--issue ID] [--max N] [--dry-run]
# Needs GH_TOKEN (and GITHUB_REPO, default ericstiles/learn_hermes) in the environment
# (direnv loads .envrc.local). The token is never written to a file or printed.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TO=""; REASON=manual; ISSUE=unknown; MAX=10; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --timeout) TO=${2:?}; shift 2 ;;
    --reason)  REASON=${2:?}; shift 2 ;;
    --issue)   ISSUE=${2:?}; shift 2 ;;
    --max)     MAX=${2:?}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "${GH_TOKEN:-}" ] || { echo "GH_TOKEN is not set (run: direnv allow, or export it). Not starting." >&2; exit 1; }
if ps -axo command | grep -E 'run-beads\.sh|hermes chat' | grep -v grep | grep -qv hermes-launch; then
  echo "A run-beads.sh / hermes chat process is already running. Not starting." >&2; exit 1
fi
mkdir -p "$ROOT/logs"
cmd="cd '$ROOT' && GITHUB_REPO='${GITHUB_REPO:-ericstiles/learn_hermes}' ${TO:+RUN_TIMEOUT='$TO'} ./run-beads.sh $MAX"
if [ "$DRY" = 1 ]; then echo "DRY RUN: would start in herdr/tmux tab hermes-run: $cmd"; exit 0; fi
printf '%s %s %s\n' "$(date +%Y%m%d)" "$REASON" "$ISSUE" >> "$ROOT/logs/.relaunches"
if command -v herdr >/dev/null 2>&1 && herdr status >/dev/null 2>&1; then
  # New tab "hermes-run" in the current herdr workspace; its shell loads direnv
  # (GH_TOKEN etc.), so the token is never passed on a command line.
  out=$(herdr tab create --label hermes-run --cwd "$ROOT" ${HERDR_WORKSPACE_ID:+--workspace "$HERDR_WORKSPACE_ID"} 2>&1) || { echo "herdr tab create failed: $out" >&2; exit 1; }
  pane=$(printf '%s' "$out" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])' 2>/dev/null)
  [ -n "$pane" ] || { echo "could not parse herdr pane id" >&2; exit 1; }
  herdr pane run "$pane" "$cmd" >/dev/null 2>&1 || { echo "herdr pane run failed" >&2; exit 1; }
  echo "started in herdr tab hermes-run (pane $pane)"; exit 0
fi
if command -v tmux >/dev/null 2>&1; then
  tmux has-session -t hermes-run 2>/dev/null && tmux kill-session -t hermes-run
  tmux new-session -d -s hermes-run "$cmd" && echo "started tmux session hermes-run (tmux attach -t hermes-run)"
else
  echo "neither herdr nor tmux usable" >&2; exit 1
fi
