#!/usr/bin/env bash
# Tests for hermes-classify / supervise / status / launch / run-beads. No network, no real agents.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); ROOT=$(cd "$HERE/../.." && pwd)
FX="$HERE/fixtures"; pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   - $1"; }
bad() { fail=$((fail+1)); echo "FAIL - $1 (got: ${2:-})"; }
eq()  { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2 != $3"; }
. "$ROOT/scripts/hermes-classify.sh"

# --- classification (one fixture per class + false-positive traps) ---
for pair in timeout_killed:TIMEOUT blocked:BLOCKED queue_empty:QUEUE_EMPTY model_api_error:MODEL_API_ERROR \
            beads_sync:BEADS_SYNC_ERROR auth_error:AUTH_ERROR sandbox_down:SANDBOX_DOWN ok_done:OK_DONE \
            trap_test_404_and_aux_timeout:OK_DONE trap_sentinel_in_prose:OK_DONE; do
  n=${pair%%:*}; want=${pair##*:}
  eq "classify $n" "$(hermes_classify "$FX/$n.log")" "$want"
done
eq "exit code 124 wins" "$(hermes_classify "$FX/ok_done.log" 124)" TIMEOUT
eq "missing file" "$(hermes_classify /nonexistent)" UNKNOWN
eq "supervise --classify" "$("$ROOT/scripts/hermes-supervise.sh" --classify "$FX/timeout_killed.log")" TIMEOUT
# real-log regression when logs exist locally (killed run, queue-empty run)
[ -f "$ROOT/logs/run-20261116-134832.log" ] && eq "real timed-out log" "$(hermes_classify "$ROOT/logs/run-20261116-134832.log")" TIMEOUT

# --- supervise: output contract, read-only, no secrets ---
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
before=$(cd "$ROOT" && git status --porcelain)
out=$(GH_TOKEN=SECRET_TOKEN_VALUE HERMES_LOG_DIR="$tmp" "$ROOT/scripts/hermes-supervise.sh" "$FX/timeout_killed.log")
echo "$out" | grep -q '^CLASS=TIMEOUT$' && ok "supervise prints CLASS" || bad "supervise CLASS" "$out"
echo "$out" | grep -q '^ACTION=AUTO_RELAUNCH$' && ok "timeout -> AUTO_RELAUNCH" || bad "timeout action" "$out"
echo "$out" | grep -q -- '--timeout 120m' && ok "timeout doubled and capped at 120m" || bad "timeout arg" "$out"
echo "$out" | grep -q SECRET_TOKEN_VALUE && bad "token leaked" || ok "no token in output"
eq "auth -> ASK_HUMAN" "$(HERMES_LOG_DIR=$tmp "$ROOT/scripts/hermes-supervise.sh" "$FX/auth_error.log" | sed -n 's/^ACTION=//p')" ASK_HUMAN
eq "blocked -> ASK_HUMAN" "$(HERMES_LOG_DIR=$tmp "$ROOT/scripts/hermes-supervise.sh" "$FX/blocked.log" | sed -n 's/^ACTION=//p')" ASK_HUMAN
eq "queue empty -> DONE" "$(HERMES_LOG_DIR=$tmp "$ROOT/scripts/hermes-supervise.sh" "$FX/queue_empty.log" | sed -n 's/^ACTION=//p')" DONE
# second timeout on same issue today -> stop and split
printf '%s TIMEOUT learn_hermes-abc\n%s TIMEOUT learn_hermes-abc\n' "$(date +%Y%m%d)" "$(date +%Y%m%d)" > "$tmp/.relaunches"
out=$(HERMES_LOG_DIR="$tmp" "$ROOT/scripts/hermes-supervise.sh" "$FX/timeout_killed.log")
echo "$out" | grep -q '^ACTION=ASK_HUMAN$' && echo "$out" | grep -q 'split' && ok "2nd timeout -> split issue" || bad "split rule" "$out"
eq "git status unchanged by supervise" "$(cd "$ROOT" && git status --porcelain)" "$before"

# --- launch: refusals ---
out=$(env -u GH_TOKEN "$ROOT/scripts/hermes-launch.sh" --dry-run 2>&1); rc=$?
[ $rc -eq 1 ] && echo "$out" | grep -q GH_TOKEN && ok "launch refuses without GH_TOKEN" || bad "launch token refusal" "$rc $out"

# --- run-beads.sh in a sandboxed copy with stubbed hermes/bd/docker ---
W="$tmp/repo"; mkdir -p "$W/scripts" "$tmp/bin"; cp "$ROOT/run-beads.sh" "$W/"; cp "$ROOT/scripts/hermes-classify.sh" "$W/scripts/"
cat > "$tmp/bin/docker" <<'S'
#!/bin/sh
exit 0
S
cat > "$tmp/bin/bd" <<'S'
#!/bin/sh
echo "bd $*" >> "$STUB_LOG"
case "$1 $2" in "list --status=in_progress") echo "◐ learn_hermes-abc P2 stuck" ;; esac
exit 0
S
cat > "$tmp/bin/hermes" <<'S'
#!/bin/sh
# config get -> value; chat -> first call hangs (killed by timeout), later calls finish
[ "$1" = config ] && { echo stub; exit 0; }
n=$(cat "$STUB_COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$STUB_COUNT"
echo "  ┊ 💻 \$ bd update learn_hermes-abc --claim --json"
if [ "$n" = 1 ] && [ "$STUB_HANG_FIRST" = 1 ]; then sleep 30; exit 0; fi
echo "PR https://github.com/o/r/pull/1"; echo; echo "Resume this session with:"; echo "Messages:       9 (1 user, 8 tool calls)"
S
chmod +x "$tmp/bin/"*
export STUB_LOG="$tmp/stub.log" STUB_COUNT="$tmp/count" GH_TOKEN=x GITHUB_REPO=o/r
TOUT=$(command -v timeout || command -v gtimeout)
if [ -z "$TOUT" ]; then echo "skip - run-beads tests need timeout/gtimeout"; else
  # lock: a live pid holding the lock blocks a second instance
  mkdir -p "$W/logs/.run-beads.lock"; echo $$ > "$W/logs/.run-beads.lock/pid"
  out=$(cd "$W" && PATH="$tmp/bin:$PATH" ./run-beads.sh 1 2>&1); rc=$?
  [ $rc -eq 3 ] && echo "$out" | grep -q 'already running' && ok "second instance refused by lock" || bad "lock" "$rc $out"
  rm -rf "$W/logs/.run-beads.lock"
  # hang first call; no retry -> TIMEOUT, claim released, RUN_RESULT line written
  : > "$STUB_LOG"; rm -f "$STUB_COUNT"
  out=$(cd "$W" && PATH="$tmp/bin:$PATH" STUB_HANG_FIRST=1 RUN_TIMEOUT=1s ./run-beads.sh 1 2>&1); rc=$?
  [ $rc -eq 1 ] && ok "timeout run exits non-zero" || bad "timeout rc" "$rc"
  grep -q '^RUN_RESULT=TIMEOUT$' "$W"/logs/run-*.log && ok "RUN_RESULT=TIMEOUT written to log" || bad "RUN_RESULT line" "$out"
  grep -q 'bd unclaim learn_hermes-abc' "$STUB_LOG" && ok "stale claim released after timeout" || bad "unclaim" "$(cat "$STUB_LOG")"
  # retry-on-timeout: second attempt (bigger timeout) completes
  rm -f "$W"/logs/run-*.log "$STUB_COUNT"; : > "$STUB_LOG"
  out=$(cd "$W" && PATH="$tmp/bin:$PATH" STUB_HANG_FIRST=1 RUN_TIMEOUT=1s HERMES_RETRY_ON_TIMEOUT=1 ./run-beads.sh 1 2>&1); rc=$?
  [ $rc -eq 0 ] && echo "$out" | grep -q 'retrying the issue once' && echo "$out" | grep -q 'FINAL_RESULT=OK_DONE' && ok "retry-on-timeout recovers" || bad "retry" "$rc $out"
  [ ! -d "$W/logs/.run-beads.lock" ] && ok "lock released on exit" || bad "lock cleanup"
fi
echo; echo "passed=$pass failed=$fail"; [ "$fail" -eq 0 ]
