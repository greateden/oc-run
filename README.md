# Use OpenCode directly

`oc-run` is retired. There is no replacement controller or compatibility command.
OpenCode already supplies non-interactive execution, project agents, tools,
context compaction, persisted sessions and transcripts. Scientific completion
belongs to the research deliverables. See [RELIABILITY.md](RELIABILITY.md) for the
investigation and validation.

## Start a Romansh session

These commands use the installed CLI **2.0.28** and the existing project agent.
`--standalone` avoids attaching that CLI to the separately installed Desktop
service (observed running 2.2.7). It does not isolate model memory or files.
The model, context capacity and KV settings are unchanged.

Paste into a macOS terminal:

```sh
cd ~/Projects/Automatic-Subtitling-for-Romansh-TV
umask 077
research_log=$(mktemp -d "$HOME/.local/state/opencode/research-XXXXXXXX")
research_deadline=$(date -u -v+15M '+%Y-%m-%dT%H:%M:%SZ')
printf 'Logs=%s; advisory deadline=%s\n' "$research_log" "$research_deadline"
opencode run --standalone --agent sage-research --format json --print-logs \
  "Direct OpenCode session: no external controller or oc-run reporting contract applies. Work towards a soft deadline of $research_deadline. Check the time at natural boundaries; finish the active action safely and preserve results. Review the saved German-to-Romansh evaluation evidence and identify the next smallest authorised experiment. Reuse saved predictions; do not run training or translation batches. Follow the existing project research instructions." \
  > "$research_log/stdout.jsonl" 2> "$research_log/stderr.log"
research_exit=$?
printf '%s\n' "$research_exit" > "$research_log/exit-status"
printf 'OpenCode exit=%s; logs=%s\n' "$research_exit" "$research_log"
```

The parent state directory already exists on this installation. If using this
recipe elsewhere, create it first with `mkdir -p ~/.local/state/opencode`.
Replace the research objective in the prompt when needed. Native permissions
still apply; no extra auto-approval flag is added.

**The deadline is advisory.** There is no external timer, timed steering request,
forced termination or promise of 15-minute execution. The model can finish early,
overrun or fail to check the clock. For a longer session, change `-v+15M` to
`-v+10H` and supply the intended research objective. Keep a terminal open; this
recipe does not provide unattended terminal-disconnection survival.

## Monitor, interrupt and resume

In another terminal, use the printed log directory:

```sh
tail -f /path/printed/above/stdout.jsonl /path/printed/above/stderr.log
```

Ctrl-C in the launching terminal interrupts native execution. It is not a safe
checkpoint request. Completed output remains in the logs and native session;
in-flight tools or external effects need inspection. Closing the terminal may
also prevent the shell from writing `exit-status`.

From the same project directory, list sessions and choose the explicit ID:

```sh
opencode session list --standalone --max-count 10
opencode session export --standalone SESSION_ID > "$research_log/session.json"
opencode --standalone --session SESSION_ID
```

The last command opens the native interactive interface for inspection. To
continue non-interactively, use fresh stdout/stderr logs as above and a new
advisory deadline in the prompt:

```sh
opencode run --standalone --agent sage-research --session SESSION_ID \
  --format json --print-logs \
  "Direct OpenCode session: no external controller or oc-run contract applies. Inspect saved outputs and active jobs first; do not duplicate uncertain actions. Continue the authorised task."
```

Use an explicit session ID rather than whichever session happens to be latest.
Old controller run IDs are not native session IDs; read the `Session:` line in
an old `HANDOFF.md` or the `session` field of its `run.json`. Inspect historical
instructions and queued input before resuming an old session.

## Failure behaviour

- No final answer: retain the transcript; do not launch a repair request or
  infer that the research succeeded. The native CLI can exit 0 with no answer.
- Tool failure: the agent may continue; failed tool details remain in the native
  transcript. A process exit of 0 does not validate scientific results.
- Provider OOM: preserve the native error and actual exit status. No external
  retry, automatic resumption or model-setting change. Inspect memory, outputs
  and jobs before deciding whether to resume. OpenCode may retry some provider
  errors internally; this repository adds no retry policy.
- Long experiments: there is no budget-triggered signal or process-group cleanup.
  A deliberately detached fixture survived native CLI exit. Native managed jobs
  can have different lifetimes; do not assume private-server shutdown preserves
  them. Follow the agent's existing bounded-job and persistent-log instructions.
- No wrapper lock: do not start competing research sessions in the same checkout.
  OpenCode sessions do not serialise writes from separate sessions. Use an
  isolated worktree if concurrent work is necessary; keep heavy experiments
  sequential under the existing agent policy.

## Checks and rollback

No dependencies beyond Python's standard library and the installed OpenCode:

```sh
OC_NATIVE_BIN="$HOME/.opencode/bin/opencode" \
OC_NATIVE_AGENT="$HOME/Projects/Automatic-Subtitling-for-Romansh-TV/.opencode/agents/sage-research.md" \
python3 -m unittest discover -s tests -v
```

These five native CLI tests use a loopback provider, not live Sage inference.
The former controller is retained at Git reference `backup/pre-native-20261113`
(commit `1c36a97`) and in an external Git bundle. Local installation and global
instruction backups are in:

```text
~/.local/share/oc-run/retirement-20261113T113106Z/
```

For rollback, restore `oc-run.installed` to `~/.local/bin/oc-run` using
`install -m 755`, and restore `global-AGENTS.md.before` only after comparing it
with the current global instructions. To inspect the old source without changing
this checkout, run `git worktree add --detach /a/new/path 1c36a97`.
Historical `~/.local/state/oc-run/` directories remain untouched.

Native command documentation: [CLI](https://opencode.ai/docs/cli/commands/).
The installed `opencode run --help` is authoritative for this installation;
the website also documents newer flags absent from 2.0.28.
