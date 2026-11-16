#!/usr/bin/env bash
# hermes-supervise.sh — READ-ONLY diagnosis of the newest Hermes run, with the
# recommended next action. Claude Code runs this, then acts on the action.
#
# Usage:
#   scripts/hermes-supervise.sh                 diagnose newest log in $HERMES_LOG_DIR (default logs)
#   scripts/hermes-supervise.sh <logfile>       diagnose a specific log
#   scripts/hermes-supervise.sh --classify <f>  print only the class name
#
# Output (parseable): CLASS=..., ISSUE=..., ACTION=<AUTO_RELAUNCH|WAIT|DONE|ASK_HUMAN>,
# NEXT=<exact command to run>, then evidence lines.
#
# Remediation policy (Claude follows ACTION without asking, except ASK_HUMAN):
#   TIMEOUT          AUTO_RELAUNCH with doubled timeout (cap 120m). 2nd timeout on
#                    the same issue today -> ASK_HUMAN "split the issue" (file a
#                    discovered-from issue, bd update --status blocked).
#   SANDBOX_DOWN     AUTO_RELAUNCH after `colima start`.
#   BEADS_SYNC_ERROR AUTO_RELAUNCH after `bd dolt pull` (never force-push).
#   MODEL_API_ERROR  AUTO_RELAUNCH once Ollama answers; stop after 3 in a row.
#   QUEUE_EMPTY / OK_DONE  DONE / WAIT: nothing to do.
#   AUTH_ERROR / BLOCKED / UNKNOWN   ASK_HUMAN with evidence.
# Hard limit: 3 automatic relaunches per issue per day (counted in
# logs/.relaunches, written by hermes-launch.sh). Never prints GH_TOKEN.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=hermes-classify.sh
. "$ROOT/scripts/hermes-classify.sh"
LOG_DIR=${HERMES_LOG_DIR:-$ROOT/logs}
STATE="$LOG_DIR/.relaunches"          # lines: YYYYMMDD CLASS ISSUE
MAX_RELAUNCH=3; TIMEOUT_CAP=120

if [ "${1:-}" = "--classify" ]; then hermes_classify "${2:?logfile}"; exit 0; fi

log=${1:-$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -n 1)}
[ -n "$log" ] && [ -r "$log" ] || { echo "CLASS=UNKNOWN"; echo "ACTION=ASK_HUMAN"; echo "evidence: no readable log in $LOG_DIR"; exit 0; }

active=$(ps -axo command 2>/dev/null | grep -E 'run-beads\.sh|hermes chat' | grep -v grep | wc -l | tr -d ' ')
newest=$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -n 1)
if [ "$active" -gt 0 ] && [ "$log" = "$newest" ]; then class=RUNNING; else class=$(hermes_classify "$log"); fi

issue=$(tr -d '\r' < "$log" | sed -n 's/.*bd update \(learn_hermes-[a-z0-9]*\) --claim.*/\1/p' | head -n 1)
today=$(date +%Y%m%d)
count_today() { # <issue> [class]
  [ -f "$STATE" ] || { echo 0; return; }
  awk -v d="$today" -v i="$1" -v c="${2:-}" '$1==d && $3==i && (c=="" || $2==c){n++} END{print n+0}' "$STATE"
}
cur=${RUN_TIMEOUT:-90m}; cur=${cur%m}; case "$cur" in ''|*[!0-9]*) cur=90 ;; esac
next_to=$(( cur * 2 )); [ "$next_to" -gt "$TIMEOUT_CAP" ] && next_to=$TIMEOUT_CAP
relaunches=0; [ -n "$issue" ] && relaunches=$(count_today "$issue")

action=ASK_HUMAN; next=""; why=""
case "$class" in
  RUNNING)  action=WAIT; why="a run is in progress; check again in 20-30 min" ;;
  OK_DONE)  action=DONE; why="run finished and opened a PR; review/merge is the human's step" ;;
  QUEUE_EMPTY) action=DONE; why="no ready beads issues (bd dolt pull to confirm, then create issues)" ;;
  TIMEOUT)
    if [ -n "$issue" ] && [ "$(count_today "$issue" TIMEOUT)" -ge 2 ]; then
      why="issue $issue timed out twice today: split it (bd create ... --deps discovered-from:$issue), bd update $issue --status blocked, then relaunch"
    elif [ "$relaunches" -ge "$MAX_RELAUNCH" ]; then why="relaunch limit ($MAX_RELAUNCH/day) reached for $issue"
    else action=AUTO_RELAUNCH; next="scripts/hermes-launch.sh --reason TIMEOUT --issue ${issue:-unknown} --timeout ${next_to}m"
         why="killed by timeout before finishing; relaunch with ${next_to}m"; fi ;;
  SANDBOX_DOWN)
    if [ "$relaunches" -ge "$MAX_RELAUNCH" ]; then why="relaunch limit reached"
    else action=AUTO_RELAUNCH; next="colima start && scripts/hermes-launch.sh --reason SANDBOX_DOWN --issue ${issue:-unknown}"; why="Docker/colima not running"; fi ;;
  BEADS_SYNC_ERROR)
    if [ "$relaunches" -ge "$MAX_RELAUNCH" ]; then why="relaunch limit reached"
    else action=AUTO_RELAUNCH; next="bd dolt pull && scripts/hermes-launch.sh --reason BEADS_SYNC_ERROR --issue ${issue:-unknown}"; why="beads remote is ahead; pull then relaunch (never force-push)"; fi ;;
  MODEL_API_ERROR)
    if [ "$(awk '$2=="MODEL_API_ERROR"{n++} END{print n+0}' "$STATE" 2>/dev/null)" -ge 3 ]; then why="3 model/API failures in a row"
    else action=AUTO_RELAUNCH; next="curl -sf http://localhost:11434/api/tags >/dev/null && scripts/hermes-launch.sh --reason MODEL_API_ERROR --issue ${issue:-unknown}"
         why="model server error; confirm Ollama answers, then relaunch"; fi ;;
  AUTH_ERROR) why="credentials problem (GH_TOKEN scope/expiry); needs the human" ;;
  BLOCKED)    why="Hermes marked the issue blocked and stopped; read its notes (bd show) and decide" ;;
  *)          why="unclassified; read the evidence" ;;
esac

echo "CLASS=$class"; echo "ISSUE=${issue:-unknown}"; echo "LOG=$log"
echo "ACTION=$action"; [ -n "$next" ] && echo "NEXT=$next"; echo "WHY=$why"
echo "relaunches_today=$relaunches"
echo "--- evidence (last 12 lines, CR stripped)"; tail -n 12 "$log" | tr -d '\r' | sed 's/^/  /'
exit 0
