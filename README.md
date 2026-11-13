# OC Run

A timer that gives the same OpenCode session another turn while time remains.
Python 3 standard library only; requires the installed `opencode` on PATH.
Validated with OpenCode **2.0.28**; no upgrade or third-party plugin is required.

Run from the project you want OpenCode to work in:

```sh
cd ~/Projects/Automatic-Subtitling-for-Romansh-TV
oc-run 15m "Research task"
oc-run 10h "Research and improve this project"
```

Durations accept positive seconds, minutes or hours (`30s`, `15m`, `2h`, `10h`).
The original prompt is sent unchanged through stdin. OpenCode selects the
project's normal agent and model; this research project selects `sage-research`.
Each completed native CLI invocation is followed by the same stable continuation
prompt if the monotonic budget still has time. It asks the agent to review its
work, choose the next useful action and carry it out.

**The budget is not a timeout.** The timer never interrupts an active turn at
expiry. A turn can overrun the budget for as long as OpenCode needs. There is no
per-turn timeout, completion judgement, repair inference or external retry.
OpenCode owns permissions, execution, models, tools and compaction.

## Logs, interruption and resume

The command prints a session ID and a private log directory, normally under
`~/.local/state/oc-run/timer-*` (`$XDG_STATE_HOME/oc-run` when set). It contains
`prompt.txt`, `session-id`, `controller.log` and numbered raw stdout/stderr files.
Raw model output goes to these files, not the terminal. While a turn is running:

```sh
tail -f /printed/log/directory/0001.stdout.jsonl /printed/log/directory/0001.stderr.log
```

Ctrl-C stops further continuation and forwards **one** SIGINT to the owned
OpenCode CLI, then waits for native interruption to settle. Repeated Ctrl-C does
not force-kill it. Logs and completed work remain; inspect unfinished tools
before resuming. Unrelated processes are never signalled. Exit codes: 0 for
budget exhaustion, 130 for Ctrl-C, 2 for invalid arguments, non-zero for execution
failure or the rapid-turn safeguard. OpenCode may perform its own provider retries.

From the original project directory, use the printed ID:

```sh
opencode --standalone --session SESSION_ID
opencode session export --standalone SESSION_ID > session.json
```

The first command opens the native session; the second saves a transcript (choose
an appropriate private location). A failed initial launch may leave a reserved ID
without a created session. `oc-run` itself always starts a new session for a new
invocation. Run only one writer/controller per checkout; there is no workspace
lock or terminal-disconnection/reboot recovery service.

Three consecutive **tool-free turns each under two seconds** stop with a warning.
A single text-only answer is accepted; slower text-only turns and tool failures
that OpenCode handles are accepted. This is only a rapid-loop guard, not a claim
about useful work. Empty final answers are accepted. Native execution errors,
non-zero exits or conflicting session IDs stop without sending another prompt.

## Install and check

The local installation is `~/.local/bin/oc-run`. To install this reviewed source
manually, back up any existing executable first, then:

```sh
install -m 755 oc-run ~/.local/bin/oc-run
OC_NATIVE_BIN="$HOME/.opencode/bin/opencode" \
OC_NATIVE_AGENT="$HOME/Projects/Automatic-Subtitling-for-Romansh-TV/.opencode/agents/sage-research.md" \
python3 -m unittest discover -s tests -v
```

The tests use deterministic local fixtures, including the installed CLI against
a loopback provider. They do not run Sage or research experiments. A separate
short live Sage smoke was run; no ten-hour reliability claim is made.
See [ASSESSMENT.md](ASSESSMENT.md) for native/plugin research and
[VALIDATION.md](VALIDATION.md) for results and limitations.

Historical logs and [retirement evidence](RELIABILITY.md) remain untouched.
The old controller is recoverable from `backup/pre-native-20261113` (`1c36a97`)
and `~/.local/share/oc-run/retirement-20261113T113106Z/`.
