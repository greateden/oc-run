# OC Run

OC Run is a small controller for long OpenCode sessions, including overnight
research and coding. It uses one session and the configured OpenCode model.
It has no Python dependencies outside the standard library.

## Requirements

- macOS or Linux, Python 3.10 or newer, and Git.
- [OpenCode](https://opencode.ai/) on your PATH, with a working model provider.
- The CLI must support `run --standalone --format json --session`.
- Tested locally with OpenCode 2.0.28. Other versions may change the event format.

## Install

Clone this repository and inspect `oc-run` before installing it. From the checkout:

```sh
mkdir -p ~/.local/bin
install -m 755 oc-run ~/.local/bin/oc-run
```

Add `~/.local/bin` to your PATH if needed. Keep one installed copy. Save a copy
of an existing installation before replacing it. No remote install script is needed.

## Run overnight

Start inside the project you want OpenCode to work on:

```sh
oc-run 10h "Research and improve this project"
```

- `--dry-run`: show the budget and directory without running commands or writing state.
- `--push`: allow the agent to push after checks and a privacy review. Off by default.
- `--stop-when-done`: ask it to stop once the required work is complete.
- Durations accept `s`, `m` or `h`. A bare number means minutes.
- OpenCode keeps its configured model, tools and permissions. OC Run does not use `--auto`.

The budget is a target, not a kill timer. The agent works to a meaningful milestone,
then the same model reviews the evidence and returns CONTINUE, PIVOT or STOP.
It checks for repeated failure, drift and unnecessary complexity. No useful work
is invented to fill the budget. A repeated identical set of tool results stops
the run for inspection.

At the budget end, a local control file requests a safe handoff. The agent is told
to read it at checkpoints and before substantial new work. An active model call
or tool operation can run past the budget. The next review asks it to stop.

## See what happened

```sh
oc-run handoff --latest
oc-run handoff --run /path/to/run
```

- The terminal prints the run directory and runner PID.
- `HANDOFF.md` holds the task, directory, recorded elapsed time, last useful work,
  model review, Git changes, failures, unverified claims and next action.
- Long sections are shown as excerpts. Full task text and replies stay in the run directory.
- `run.json` holds controller state. Each invocation has a raw JSONL log and reply.
- Handoff commands read local files. They make no model call and do not upload anything.
- State is private to your account under `~/.local/state/oc-run`.
  `OC_RUN_STATE_DIR` can select another private directory outside the project repository.
- Logs and handoffs can contain private prompts, paths, tool output and secrets.
  Keep them private. Review before sharing. They are never added to this repository.

## Failures and recovery

- A failed tool stays in the record. It does not discard unrelated useful work.
- A provider error or failed OpenCode process stops the runner. There are no automatic retries.
- A missing or malformed review preserves the work and reports failure.
- Exit `0` means the model reviewed the task as complete with cited evidence and
  observed successful tool calls. It is not independent proof of task correctness.
- Exit `3` means incomplete or unverified. Exit `1` means invocation or review failure.
  Exit `2` means a command or setup error. Interrupts use `128 + signal`.
- Ctrl-C or SIGTERM stops a stalled run. Cleanup sends TERM, then KILL within a
  few seconds. A small watchdog also cleans the process group if the runner crashes.
- After interruption, inspect partial outputs and running jobs before resuming.
  From the original project directory, give a new working budget:

```sh
oc-run resume 2h --latest
```

Use `--run /path/to/run` to resume a specific run. It reuses the session and logs,
preserves the original task, and asks the agent to inspect interrupted work first.
Push permission must be enabled again. Old-format runs can be read with `handoff`;
they cannot be resumed automatically.

## Limits

- Supervision uses the working model. It can misjudge evidence or ignore instructions.
- There is no automatic silence timeout: quiet inference and a hang can look alike.
  A hung run needs a signal. Budget expiry does not interrupt an active call.
- Git safety rules are instructions to OpenCode, not a sandbox. The runner itself
  does not commit, push, merge, reset or delete project files. Use restrictive
  OpenCode permissions when stronger enforcement is needed.
- Cleanup covers the managed process group. A tool that deliberately detaches a job
  can escape it. Inspect such jobs before recovery.
- State files are written atomically. A crash may leave a partial raw log or an
  older handoff. Recorded elapsed time is refreshed every 30 seconds during work;
  time between its last refresh and a crash is unknown.
- Keep the machine awake. Model costs and provider limits still apply.
- The former `--round-time`, `--fin-time` and `--safety-grace` options are removed.

Run the deterministic tests with `python3 -m unittest discover -s tests -v`.
They use a fake CLI and make no model calls. MIT licence; see [LICENSE](LICENSE).
