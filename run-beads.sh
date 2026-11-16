#!/usr/bin/env bash
# run-beads.sh — work up to N beads issues via one-shot Hermes runs.
# Stops when the queue is empty, an issue is blocked, or a run fails/times out.
#
# Usage:  GITHUB_REPO=owner/name ./run-beads.sh [MAX_ISSUES]
# Model:  HERMES_ARGS="--provider ollama-launch -m qwen3.8:27b-mlx" overrides the config default.
# Needs:  GH_TOKEN exported (forwarded into the sandbox via docker_forward_env),
#         Docker/colima running, hermes + gh on PATH.
#
# Env (all optional):
#   RUN_TIMEOUT=90m              per-run kill timeout (local 27B model needs > 45m)
#   HERMES_RETRY_ON_TIMEOUT=0|1  on a timeout, retry the same issue once with a
#                                larger timeout (2x, capped at HERMES_TIMEOUT_CAP=120m)
#   HERMES_UNCLAIM_ON_TIMEOUT=1  after a timeout, release the stuck claim so
#                                `bd ready` lists the issue again
#
# Every run's log ends with a line  RUN_RESULT=<CLASS>  (see scripts/hermes-classify.sh)
# so scripts/hermes-supervise.sh can parse the outcome instead of grepping prose.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT" || exit 2
# shellcheck source=scripts/hermes-classify.sh
. "$ROOT/scripts/hermes-classify.sh"

MAX=${1:-10}
REPO=${GITHUB_REPO:?set GITHUB_REPO=owner/name}
NAME=${REPO##*/}
TIMEOUT=${RUN_TIMEOUT:-90m}
RETRY=${HERMES_RETRY_ON_TIMEOUT:-0}
UNCLAIM=${HERMES_UNCLAIM_ON_TIMEOUT:-1}
TIMEOUT_CAP_MIN=${HERMES_TIMEOUT_CAP:-120}; TIMEOUT_CAP_MIN=${TIMEOUT_CAP_MIN%m}
: "${GH_TOKEN:?export GH_TOKEN (fine-grained, this repo only)}"

# macOS has no `timeout` by default; coreutils provides gtimeout.
TO=$(command -v timeout || command -v gtimeout || true)
[ -n "$TO" ] || { echo "install coreutils for timeout/gtimeout" >&2; exit 2; }

# --- single-instance lock (mkdir is atomic and portable; macOS has no flock) ---
mkdir -p logs
LOCK="$ROOT/logs/.run-beads.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  old=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    echo "run-beads.sh is already running (pid $old). Refusing to start a second instance." >&2
    exit 3
  fi
  echo "removing stale lock (pid ${old:-unknown} is gone)" >&2
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 3
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

docker info >/dev/null 2>&1 || { echo "Docker daemon not running (try: colima start)" >&2; echo "RUN_RESULT=SANDBOX_DOWN"; exit 2; }

PROMPT="Follow AGENTS.md \"Autonomous Beads workflow\" for the repo in /workspace/$NAME \
(clone $REPO with gh if missing, otherwise git pull). Do one issue, then stop."

# Effective model: HERMES_ARGS (-m/--model, --provider) wins over config.yaml.
read -ra _args <<< "${HERMES_ARGS:-}"
_cfg() { # _cfg <key>  -> value, or warn on stderr (never silent)
  local v; v=$(hermes config get "$1" 2>/dev/null | tail -n1)
  [ -n "$v" ] || echo "warning: 'hermes config get $1' returned nothing" >&2
  printf '%s' "$v"
}
MODEL=$(_cfg model.default)
PROVIDER=$(_cfg model.provider)
for ((j = 0; j < ${#_args[@]}; j++)); do
  case "${_args[j]}" in
    -m|--model) MODEL=${_args[j+1]:-$MODEL} ;;
    --model=*) MODEL=${_args[j]#--model=} ;;
    --provider) PROVIDER=${_args[j+1]:-$PROVIDER} ;;
    --provider=*) PROVIDER=${_args[j]#--provider=} ;;
  esac
done
IMAGE=$(_cfg terminal.docker_image)
echo "== repo: $REPO | model: ${MODEL:-unknown} | provider: ${PROVIDER:-unknown} | sandbox: ${IMAGE:-default} | timeout: $TIMEOUT | retry-on-timeout: $RETRY | max issues: $MAX"

# Release a claim left behind by a killed run so the next run can pick it up.
unclaim_stale() { # <logfile>
  [ "$UNCLAIM" = 1 ] || return 0
  local id
  id=$(tr -d '\r' < "$1" | sed -n 's/.*bd update \(learn_hermes-[a-z0-9]*\) --claim.*/\1/p' | head -n 1)
  [ -n "$id" ] || { echo "note: could not find a claimed issue id in $1"; return 0; }
  bd dolt pull >/dev/null 2>&1 || echo "warning: bd dolt pull failed; claim state may be stale"
  if bd list --status=in_progress 2>/dev/null | grep -q "$id"; then
    if bd unclaim "$id" >/dev/null 2>&1; then
      echo "released stale claim on $id"; bd dolt push >/dev/null 2>&1 || echo "warning: bd dolt push failed (unclaim is local only)"
    else echo "warning: bd unclaim $id failed"; fi
  else
    echo "note: $id is not in_progress in beads; nothing to release"
  fi
}

# One Hermes run. Sets: log, status, class.
run_once() { # <timeout>
  log="logs/run-$(date +%Y%m%d-%H%M%S).log"
  echo "== run $i/$MAX | model: ${MODEL:-unknown} | timeout: $1 -> $log"
  # shellcheck disable=SC2086  # HERMES_ARGS is intentionally word-split
  "$TO" "$1" hermes chat ${HERMES_ARGS:-} -q "$PROMPT" 2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  class=$(hermes_classify "$log" "$status")
  echo "RUN_RESULT=$class" | tee -a "$log"
}

final=OK_DONE
for i in $(seq 1 "$MAX"); do
  run_once "$TIMEOUT"
  if [ "$class" = TIMEOUT ]; then
    unclaim_stale "$log"
    if [ "$RETRY" = 1 ]; then
      cur=${TIMEOUT%m}; case "$cur" in ''|*[!0-9]*) cur=90 ;; esac
      bigger=$(( cur * 2 )); [ "$bigger" -gt "$TIMEOUT_CAP_MIN" ] && bigger=$TIMEOUT_CAP_MIN
      echo "Timed out; retrying the issue once with ${bigger}m."
      run_once "${bigger}m"
      [ "$class" = TIMEOUT ] && unclaim_stale "$log"
    fi
  fi
  final=$class
  case "$class" in
    OK_DONE) continue ;;
    QUEUE_EMPTY) echo "Queue empty."; final=QUEUE_EMPTY; break ;;
    BLOCKED) echo "Issue blocked — stopping. See $log"; break ;;
    MODEL_API_ERROR) echo "Agent made no progress (model/API error) — stopping. See $log"; break ;;
    TIMEOUT) echo "Run timed out — stopping. See $log"; break ;;
    *) echo "Run ended as $class — stopping. See $log"; break ;;
  esac
done
echo "FINAL_RESULT=$final"
case "$final" in OK_DONE|QUEUE_EMPTY) exit 0 ;; *) exit 1 ;; esac
