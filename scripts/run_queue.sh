#!/usr/bin/env bash
#
# Execute the Historiador build queue with agy.
#
# Dependency order and file ownership are enforced here, by the script, rather
# than being described to a model and hoped for. Each task gets its own agy
# session with a brief naming exactly the files it may touch; a task that reports
# a collision is parked and the loop moves on to whatever else is unblocked.
#
#   ./scripts/run_queue.sh              # run until the queue drains
#   ./scripts/run_queue.sh --dry-run    # show the wave plan, invoke nothing
#   ./scripts/run_queue.sh --wave       # run one wave, then stop
#   PARALLEL=6 ./scripts/run_queue.sh   # widen per-wave concurrency (default 4)
#
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

QUEUE=/tmp/task_queue.json
LOGDIR=logs/queue
LIB="scripts/queue_lib.py"
PARALLEL="${PARALLEL:-4}"
MODEL="${AGY_MODEL:-claude-sonnet-4-6}"
TIMEOUT="${AGY_TIMEOUT:-45m}"

DRY_RUN=0
ONE_WAVE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --wave)    ONE_WAVE=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

command -v agy >/dev/null || { echo "FATAL: agy not on PATH" >&2; exit 1; }
[ -f "$QUEUE" ] || { echo "FATAL: $QUEUE missing" >&2; exit 1; }
python3 -c "import json;json.load(open('$QUEUE'))" || { echo "FATAL: $QUEUE is not valid JSON" >&2; exit 1; }
mkdir -p "$LOGDIR"

q() { python3 "$LIB" "$@"; }

# Run one task in its own agy session. Returns non-zero if the task did not
# report success, so the caller can park it rather than marking it Completed.
run_task() {
  local id="$1"
  local log="$LOGDIR/${id}.log"
  local promptfile="$LOGDIR/${id}.prompt"

  q prompt "$id" > "$promptfile"
  q status "$id" InProgress

  echo "  ▸ $id  (log: $log)"
  # No --dangerously-skip-permissions. Permissions are granted explicitly and
  # scoped in ~/.gemini/antigravity-cli/settings.json under permissions.allow,
  # with this repo listed in trustedWorkspaces. `accept-edits` then lets a task
  # write its own files unattended without blanket-approving every tool.
  agy -p "$(cat "$promptfile")" \
      --model "$MODEL" \
      --mode accept-edits \
      --print-timeout "$TIMEOUT" \
      > "$log" 2>&1
  local rc=$?

  if grep -q "PAUSED_COLLISION" "$log"; then
    local detail
    detail="$(grep -m1 "PAUSED_COLLISION" "$log" | tr -d '\n' | cut -c1-200)"
    q status "$id" PAUSED_COLLISION "$detail"
    echo "  ⏸ $id PAUSED_COLLISION — $detail"
    return 1
  fi

  if [ $rc -ne 0 ]; then
    q status "$id" Failed "agy exited $rc — see $log"
    echo "  ✗ $id FAILED (agy rc=$rc)"
    return 1
  fi

  # rc=0 is NOT evidence of work. A session that dies after printing one line —
  # an auto-denied permission, a truncated run — exits cleanly, and trusting that
  # once already stamped 37 no-op sessions as Completed. Require the artifacts.
  local missing
  missing="$(q verify "$id")"
  if [ -n "$missing" ]; then
    local count
    count="$(printf '%s\n' "$missing" | wc -l | tr -d ' ')"
    q status "$id" Failed "produced no output for $count owned path(s); first: $(printf '%s' "$missing" | head -1)"
    echo "  ✗ $id FAILED — $count owned file(s) missing despite rc=0"
    return 1
  fi

  # A log this short means the session never got going, whatever it exited with.
  if [ "$(wc -c < "$log" | tr -d ' ')" -lt 200 ]; then
    q status "$id" Failed "suspiciously short log ($(wc -c < "$log" | tr -d ' ') bytes) — session likely died early"
    echo "  ✗ $id FAILED — log too short to be a real run"
    return 1
  fi

  q status "$id" Completed
  echo "  ✓ $id"
  return 0
}

# macOS ships bash 3.2, which has neither `mapfile` nor `wait -n`. Both are
# replaced below with 3.2-compatible equivalents so this runs on a stock Mac
# without anyone having to install a newer bash first.
read_ready() {
  READY=()
  while IFS= read -r line; do
    [ -n "$line" ] && READY+=("$line")
  done < <(q ready)
}

# Block until fewer than $1 background jobs remain.
throttle() {
  while [ "$(jobs -pr | wc -l | tr -d ' ')" -ge "$1" ]; do
    sleep 1
  done
}

wave=0
while :; do
  read_ready
  [ "${#READY[@]}" -eq 0 ] && break

  wave=$((wave + 1))
  echo ""
  echo "═══ wave $wave — ${#READY[@]} runnable, up to $PARALLEL at a time"

  if [ "$DRY_RUN" -eq 1 ]; then
    printf '    %s\n' "${READY[@]}"
    # Simulate completion so the dry run can show every subsequent wave.
    for id in "${READY[@]}"; do q status "$id" Completed; done
    [ "$ONE_WAVE" -eq 1 ] && break
    continue
  fi

  for id in "${READY[@]}"; do
    throttle "$PARALLEL"
    run_task "$id" &
  done
  wait

  echo "─── after wave $wave: $(q summary)"
  [ "$ONE_WAVE" -eq 1 ] && break
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo ""
  echo "DRY RUN — statuses were mutated for planning. Restore before a real run:"
  echo "  python3 -c \"import json;p='$QUEUE';d=json.load(open(p));[t.update(status='Pending') for t in d['tasks']];json.dump(d,open(p,'w'),indent=2)\""
  exit 0
fi

echo ""
echo "═══ queue drained"
q summary
echo ""
echo "Anything marked PAUSED_COLLISION or Failed needs orchestrator arbitration."
echo "Logs: $LOGDIR/"
