#!/usr/bin/env bash
# run-beads.sh — work up to N beads issues via one-shot Hermes runs.
# Stops when the queue is empty, an issue is blocked, or a run fails/times out.
#
# Usage:  GITHUB_REPO=owner/name ./run-beads.sh [MAX_ISSUES]
# Needs:  GH_TOKEN exported (forwarded into the sandbox via docker_forward_env),
#         Docker/colima running, hermes + gh on PATH.
set -uo pipefail

MAX=${1:-10}
REPO=${GITHUB_REPO:?set GITHUB_REPO=owner/name}
NAME=${REPO##*/}
TIMEOUT=${RUN_TIMEOUT:-45m}
: "${GH_TOKEN:?export GH_TOKEN (fine-grained, this repo only)}"

# macOS has no `timeout` by default; coreutils provides gtimeout.
TO=$(command -v timeout || command -v gtimeout || true)
[ -n "$TO" ] || { echo "install coreutils for timeout/gtimeout" >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon not running (try: colima start)" >&2; exit 2; }

PROMPT="Follow AGENTS.md \"Autonomous Beads workflow\" for the repo in /workspace/$NAME \
(clone $REPO with gh if missing, otherwise git pull). Do one issue, then stop."

mkdir -p logs
for i in $(seq 1 "$MAX"); do
  log="logs/run-$(date +%Y%m%d-%H%M%S).log"
  echo "== run $i/$MAX -> $log"
  "$TO" "$TIMEOUT" hermes chat -q "$PROMPT" 2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  grep -q NO_READY_WORK "$log" && { echo "Queue empty."; break; }
  grep -q RUN_BLOCKED "$log" && { echo "Issue blocked — stopping. See $log"; break; }
  [ "$status" -ne 0 ] && { echo "Run failed/timed out ($status) — stopping. See $log"; break; }
done
