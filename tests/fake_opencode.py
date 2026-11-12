#!/usr/bin/env python3
"""Deterministic CLI fixture. No network or model calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

prompt = sys.stdin.read()
scenario = os.environ.get("FAKE_SCENARIO", "success")
session = "ses_fixture"
if "--session" in sys.argv:
    assert sys.argv[sys.argv.index("--session") + 1] == session
review = "REVIEW ONLY." in prompt
Path("prompts.txt").open("a").write(prompt + "\n---\n")


def emit(kind, part=None, **extra):
    print(json.dumps({"type": kind, "sessionID": session, "part": part or {}, **extra}), flush=True)


def tool(name, inputs, output, bad=False):
    emit("tool_use", {"id": "call_" + name, "tool": name, "state": {
        "status": "error" if bad else "completed", "input": inputs,
        "output": output, "error": output if bad else None,
        "metadata": {"exit": 1 if bad else 0}}})


emit("step_start")
if not review:
    if scenario in ("stall", "crash"):
        child = subprocess.Popen([sys.executable, "-c",
                                  "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)"])
        Path("child.pid").write_text(str(child.pid))
        if scenario == "crash":
            Path("partial.txt").write_text("Useful output before runner crash\n")
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(.1)
    if scenario == "long":
        time.sleep(.5)
    if scenario in ("tool_failure", "repeat", "pivot"):
        tool("shell", {"command": "bad-command"}, "Tool unavailable", True)
    if scenario == "transport":
        emit("error", error={"message": "socket closed"})
        sys.exit(0)
    if scenario == "nonzero":
        emit("text", {"text": "Useful partial work survived."})
        sys.exit(7)
    if scenario not in ("premature", "repeat", "pivot") and not (scenario == "prior_evidence" and Path('prior').exists()):
        Path("answer.txt").write_text("12\n")
        tool("read", {"path": str(Path("answer.txt").absolute())}, "12")
    if scenario == "pivot" and Path("pivoted").exists():
        assert "different" in prompt
        tool("read", {"path": "facts.txt"}, "new evidence")
    emit("text", {"text": "Milestone complete. Evidence: answer.txt contains 12. Next: review."})
else:
    if scenario == "malformed":
        emit("text", {"text": "not JSON; useful work should remain"})
        sys.exit(0)
    decision = "CONTINUE" if scenario == "repeat" else "STOP"
    complete = scenario not in ("repeat", "pivot")
    if scenario == "pivot":
        if not Path("pivoted").exists():
            Path("pivoted").touch()
            decision, complete = "PIVOT", False
        else:
            decision, complete = "STOP", True
    if scenario == 'prior_evidence' and not Path('prior').exists():
        Path('prior').touch()
        decision, complete = 'CONTINUE', False
    report = {"decision": decision, "complete": complete,
              "reason": "Repeated failure needs a different approach" if not complete else "Required work checked",
              "summary": "Completed: read/write fixture. Failed: unavailable tool; later read succeeded. Unverified: none in fixture.",
              "evidence": ["read answer.txt: 12"], "next": "Use a different direct read" if not complete else "none"}
    emit("text", {"text": json.dumps(report)})
