#!/usr/bin/env python3
"""Queue helpers for run_queue.sh.

The scheduling decisions live here rather than in the shell script or in a model
prompt, because dependency order and file ownership are exactly the things that
must not be improvised. The shell script drives the loop; this module answers
"what is runnable now", "what should this worker be told", and "what changed".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

QUEUE = Path("/tmp/task_queue.json")
DONE = {"Completed"}
BLOCKED = {"PAUSED_COLLISION", "Failed"}


def load() -> dict[str, Any]:
    return json.loads(QUEUE.read_text())


def save(data: dict[str, Any]) -> None:
    """Write atomically — a half-written queue would strand the whole run."""
    tmp = QUEUE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(QUEUE)


def ready(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Tasks whose dependencies are all Completed and which are not yet done."""
    done = {t["id"] for t in data["tasks"] if t.get("status") in DONE}
    out = []
    for t in data["tasks"]:
        if t.get("status") in DONE | BLOCKED or t.get("status") == "InProgress":
            continue
        if all(d in done for d in (t.get("dependsOn") or [])):
            out.append(t)
    return out


def get(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    for t in data["tasks"]:
        if t["id"] == task_id:
            return t
    raise KeyError(task_id)


def set_status(task_id: str, status: str, note: str = "") -> None:
    data = load()
    t = get(data, task_id)
    t["status"] = status
    if note:
        t["note"] = note
    save(data)


def prompt_for(task: dict[str, Any]) -> str:
    """The full worker brief. Everything a cold agent needs, nothing it must guess."""
    owns = "\n".join(f"  - {p}" for p in (task.get("ownsFiles") or []))
    acc = "\n".join(f"  - {a}" for a in (task.get("acceptance") or []))
    deps = ", ".join(task.get("dependsOn") or []) or "none"
    return f"""You are implementing ONE task in the Historiador rewrite.
Working directory: /Users/edmundo/historiador

TASK: {task['id']} — {task['name']}

{task['description']}

READ FIRST (authoritative contract, do not deviate from it):
  /Users/edmundo/historiador/ARCHITECTURE.md
It defines the package layout (§2), runtime contracts (§3), the event taxonomy
(§4), the LLM layer (§5), the data schema (§6), the API + WebSocket protocol (§7),
the daemon (§8), the dashboard (§9), and the coding conventions (§10).
Also read README.md for the product end-state.

FILE OWNERSHIP — THE HARD RULE.
You may create or edit ONLY these paths:
{owns or "  (none — this is an audit/report task; write no source files)"}

Any other path is owned by a different task and may already be someone else's
work in progress. If you believe you must change a file outside your list, DO NOT
edit it. Stop, print exactly:
    PAUSED_COLLISION: <path> needed by {task['id']}
and explain what contract change you need. The orchestrator arbitrates. Editing
another task's file is the one failure mode this whole queue exists to prevent.

Dependencies already completed: {deps}
Their files exist on disk — read them to match the established style and imports.
Do not rewrite them.

ACCEPTANCE — you are not done until these actually pass:
{acc or "  - code compiles and imports cleanly"}

Environment: Python deps are installed via uv. Use `uv run python`, `uv run pytest`,
`uv run mypy`, `uv run ruff check`. For web tasks use npm inside web/.

Run the acceptance checks yourself and iterate until they genuinely pass. Paste the
real command output in your final message. Never report success on a failing check —
a false Completed corrupts every downstream task in the queue.
"""


def verify(task: dict[str, Any]) -> list[str]:
    """Owned paths the task was supposed to produce but did not.

    Exit code 0 from a worker is not evidence of work: a session that dies after
    printing one sentence exits cleanly and would otherwise be recorded as
    Completed. Checking the artifacts it claimed to own is the cheapest honest
    signal that anything actually happened.
    """
    missing = []
    for p in task.get("ownsFiles") or []:
        path = Path(p)
        # A path a task owns purely to DELETE is satisfied by its absence, so
        # only flag files the description does not mark for removal.
        if "to DELETE" in (task.get("description") or "") and not path.exists():
            continue
        if not path.exists() or path.stat().st_size == 0:
            missing.append(p)
    return missing


def main() -> int:
    cmd = sys.argv[1]
    if cmd == "verify":
        data = load()
        task = get(data, sys.argv[2])
        missing = verify(task)
        if missing:
            print("\n".join(missing))
            return 1
        return 0
    if cmd == "ready":
        print("\n".join(t["id"] for t in ready(load())))
    elif cmd == "prompt":
        print(prompt_for(get(load(), sys.argv[2])))
    elif cmd == "status":
        set_status(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    elif cmd == "summary":
        data = load()
        from collections import Counter

        counts = Counter(t.get("status", "Pending") for t in data["tasks"])
        total = len(data["tasks"])
        print(f"total={total} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        for t in data["tasks"]:
            if t.get("status") in BLOCKED:
                print(f"  !! {t['id']}: {t.get('status')} {t.get('note','')}")
    elif cmd == "remaining":
        data = load()
        print(sum(1 for t in data["tasks"] if t.get("status") not in DONE | BLOCKED))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
