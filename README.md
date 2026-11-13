# OC Run

A small Python 3 standard-library timer for continuing one native OpenCode
session. Requires `opencode` on `PATH`; validated with OpenCode 2.0.28.

Run it from the project OpenCode should work in:

```sh
oc-run 15m "Research this question"
oc-run 10h "Research and improve this project"
```

Budgets accept positive seconds, minutes or hours (`30s`, `15m`, `2h`). The
original prompt is sent unchanged. Each completed turn is followed by a stable
continuation prompt in the same session if budget remains.

## Budget and failures

The budget is a soft deadline: an active OpenCode turn is allowed to finish,
even if it overruns. No new turn starts after expiry. OpenCode owns execution,
permissions, tools and provider retries. OC Run does not infer completion or
retry failures; a non-zero CLI exit, native error event, or conflicting session
ID stops the run. Empty answers are allowed. Three consecutive tool-free turns
under two seconds stop with a warning and a non-zero exit. There is no per-turn
timeout or workspace lock: a hung CLI can wait indefinitely, so run only one
controller per checkout.

## Logs and interruption

The command prints the session ID and log directory, normally under
`~/.local/state/oc-run/timer-*` (or `$XDG_STATE_HOME/oc-run`). It contains the
original prompt, session ID, controller journal, and per-turn raw stdout/stderr.
Logs and completed work are retained on failure or interruption.

Ctrl-C, SIGHUP and SIGTERM are forwarded once to the owned OpenCode CLI as the
same signal; OC Run waits for it to settle and starts no more turns. Repeated
signals do not force-kill OpenCode or change the first signal's exit status.
Exit codes are 0 for budget expiry, 130 for Ctrl-C, 129 for SIGHUP, 143 for
SIGTERM, 2 for invalid arguments and non-zero for execution failures or the
rapid-turn safeguard.

Resume or export the printed session from the project directory:

```sh
opencode --standalone --session SESSION_ID
opencode session export --standalone SESSION_ID > session.json
```

## Install and test

Back up an existing installation before updating it:

```sh
install -m 755 oc-run ~/.local/bin/oc-run
python3 -m unittest discover -s tests -v
```

The default tests use deterministic fixtures. Installed-CLI loopback tests are
opt-in via `OC_NATIVE_BIN` and `OC_NATIVE_AGENT`; they do not contact a model
provider or run research work. See [VALIDATION.md](VALIDATION.md) for results,
[ASSESSMENT.md](ASSESSMENT.md) for architecture and the deferred GPU handoff,
and [RELIABILITY.md](RELIABILITY.md) for historical retirement evidence.
