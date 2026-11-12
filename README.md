# OC Run

Give [OpenCode](https://opencode.ai/) a task and a working budget.
Let it work continuously. Check progress, request a safe stop, then resume later.

A small Python controller for long coding and research tasks.
One worker. No milestone review calls.

```mermaid
flowchart TD
    U["User controls<br/>start · status · stop · resume"] --> C["OC Run"]
    C --> W["Worker: OpenCode<br/>One continuous session"]
    W --> J[("Private event journal<br/>Raw events + control decisions")]
    C --> J
    W --> O["Event observer<br/>Warn on repeated identical failures"]
    O -. "Steer at the next step boundary" .-> W
    S["Independent model supervisor<br/>Not shipped: concurrency unverified"]
    classDef work fill:#d7f0df,stroke:#24613b,color:#123820
    classDef control fill:#deebf7,stroke:#365c85,color:#18334d
    classDef caution fill:#fff0c2,stroke:#8a6400,color:#493600
    class W,J work
    class U,C control
    class O,S caution
    style S stroke-dasharray: 5 5
```

The observer uses tool outcomes, not private reasoning or model calls.
Independent model supervision is not included.

## Quick start

Needs macOS or Linux, Python 3.10+, Git and a configured OpenCode provider.
Tested with OpenCode 2.0.28's native V2 APIs.

Inspect this checkout, then install the local executable:

```sh
mkdir -p ~/.local/bin
install -m 755 oc-run ~/.local/bin/oc-run
```

Keep `~/.local/bin` on your PATH. Back up any old installation. In your project:

```sh
oc-run 10h "Research and improve this project"
```

Your model, tools and permissions stay configured as before.
The budget requests a handoff. No fixed rounds or silence timeouts.

## Commands

```sh
oc-run status
oc-run stop --latest          # request a safe handoff; return promptly
oc-run stop --latest --force  # interrupt the active invocation
oc-run handoff --latest
oc-run resume 2h --latest     # inspect interrupted work; give a new budget
```

- `--run /path/to/run` selects a recorded run explicitly.
- Controls select only the current directory's active run, then its newest.
- `handoff --latest` also allows historical runs from other directories.
- `--dry-run` shows intent without starting OpenCode or creating state.
- `--push` permits checked, reviewed pushes. Off by default.
- Durations: `s`, `m`, `h`. Bare numbers mean minutes.
- Reported completion stops by default.

Soft stop saves the request and uses OpenCode's native steering inbox.
`status` shows pending, confirmed, rejected or uncertain admission. Confirmed means
accepted by OpenCode; delivery waits for a step boundary. Unknown outcomes are
reconciled before retrying the same message ID. `CONTROL.md` is the fallback.
There is no automatic escalation. Resume starts a new budget and clears stale steering.

Force stop, Ctrl-C, SIGTERM and terminal closure interrupt work.
Cleanup sends TERM, then KILL to managed process groups. Other OpenCode services
are untouched. `status` distinguishes stopping, stopped and interrupted runs.

## Recovery and safety

Private state lives in `~/.local/state/oc-run`, outside your project:

| File | Purpose |
| --- | --- |
| `HANDOFF.md` | Short account of work, failures, uncertainty and next steps |
| `run.json` | Small control snapshot, session ID and recent excerpts |
| `*-work.jsonl` | Incremental native OpenCode events |
| `journal.jsonl` | Session identity, requests, warnings and state transitions |

Full output and incidents stay in logs. Oversized old snapshots remain readable;
resume preserves the original in `legacy-state.json` before compacting it.

Keep logs private: they may contain secrets. `OC_RUN_STATE_DIR` selects another
private directory. Repository locks prevent overlapping workers.

After a crash, resume preserves partial logs, reconstructs complete events and
checks OpenCode's persisted session. The worker must inspect files, jobs and
uncertain side effects before repeating non-idempotent actions. Legacy handoffs
remain readable.

Raw logs use `fsync` on useful events and roughly one-second polling boundaries.
Control records are synced; atomic snapshots also sync their parent directory.
This requests filesystem durability, not guaranteed power-loss recovery.
Unsynced tokens and unrecorded effects may be lost. No physical reboot was tested.

## Limits and checks

- Four identical consecutive failures trigger one warning per invocation.
  Changed inputs or successful tools break the streak. Warnings never kill work.
- No reasoning-loop, drift or overengineering judgement; no automatic restarts.
  Provider and process errors stop with evidence preserved.
- OpenCode 2.0.28 omits child-session events from the parent's CLI stream.
  Child tool failures and progress may be absent; inspect native sessions before recovery.
- Stop and Git rules are cooperative, not a sandbox. Detached jobs can escape
  cleanup. Other OpenCode versions may change APIs or events.
- Exit `0`: model-reported completion with evidence and successful tools, not
  independent proof. Run your own acceptance checks. `3`: stopped/incomplete.
  `1`: invocation/report failure.
  `2`: setup error. Signals: `128 + signal`.

Run deterministic tests without a model:

```sh
python3 -m unittest discover -s tests -v
```

MIT licence. See [LICENSE](LICENSE).
