# Validation: 13 November 2026

## Executed checks

The initial timer-branch validation passed 19 tests. The post-review consolidation
run passed **24 tests, no skips, exit 0, 26.643 seconds**, using `python3` and
OpenCode `~/.opencode/bin/opencode` **2.0.28**. It includes the deterministic
suite and installed-CLI loopback integration tests:

```sh
python3 -m unittest discover -s tests -v
```

For the installed-CLI run, a temporary synthetic `sage-research` agent was used:
the research-agent path recorded in the earlier validation was no longer
present. All provider responses came from the tests' loopback fixture; no model
provider or research project was contacted or modified.
The installed-CLI suite verified that SIGINT, SIGTERM and SIGHUP each reach the
native CLI, preserve completed work and prevent another turn. Deterministic
tests also verify that repeated signals are forwarded only once and retain the
first signal's exit status.

The original timer-branch validation used:

Interpreter: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`
(Python **3.12.4**).

```sh
OC_NATIVE_BIN="$HOME/.opencode/bin/opencode" \
OC_NATIVE_AGENT="$HOME/Projects/Automatic-Subtitling-for-Romansh-TV/.opencode/agents/sage-research.md" \
python3 -m unittest discover -s tests -v
```

Nine deterministic CLI-fixture tests check duration parsing, multiple turns,
unchanged prompt delivery, explicit session IDs, overrun, errors, changed session
IDs, rapid-loop stopping, slower text-only answers, interruption and monotonic
timekeeping. Ten tests use the actual installed CLI with an isolated loopback
provider and a copy of the existing `sage-research` agent. These are execution
tests, not live-model or scientific-quality evaluations.

| Requirement | Observed result |
| --- | --- |
| Correct agent and original prompt | Native provider received the existing research instructions; exported assistant records use `sage-research`; initial user text equals the original prompt exactly. |
| Same session and multiple turns | Three turns in `ses_cea88b6c522d4e629d1e835ff1dfaeb8`; exports contain one original message and two identical continuation messages. |
| No admission after budget | In the two-second native fixture, turns started at +0.000, +1.115 and +1.844 seconds. Turn three finished at +2.572; no turn four. |
| Active turn survives deadline | A separate 0.1-second fixture stayed alive while its provider was blocked beyond the deadline. After explicit fixture release it returned a complete answer at +0.633 seconds, exit 0; exactly one turn. |
| Empty or imperfect answers | Native empty answer emits no JSON events, yet successfully continues using its predetermined ID. A native shell exit 7 and partial final answer remain in the transcript and permit continuation. |
| Provider failure | Native HTTP 400/OOM gives one provider invocation, CLI/wrapper exit 1, raw error retained, no continuation. A fixture emitting a terminal error with process exit 0 also stops; ambiguous exit 7 is not retried. |
| Ctrl-C | Wrapper forwards SIGINT to its owned CLI; native interruption exits 130. Completed shell file, raw events and session export survive; no second turn. The deterministic fixture checks stderr preservation too. |
| Rapid turns | Three tool-free turns under two seconds each stop with a warning and exit 1. Text-only turns lasting over two seconds continue until budget exhaustion. |

An early native test exposed the empty-answer/no-events case. Its failure and
logs are retained in `validation-tests.log` and `validation/`. The fix uses the
CLI's documented create-if-missing session ID support. A second run passed all
19 tests; final strengthened prompt assertions also passed. The positional
prompt quoting/duplication observed during that investigation was eliminated
by stdin delivery, verified against exported message text.

## Live Sage smoke

One short authorised live test used the unchanged global configuration and a
copy of the research agent in an isolated fixture directory outside the research
repository. Sage read `SMOKE.txt` and returned its phrase, using only the native
`read` tool. Exported assistant records identify `sage-research` and
`mtplx/internscience-sage-a1-5-mlx-bf16-validated`.

- Session: `ses_668836fd453b419aa0da274fdf00e700`.
- Budget: 0.1 seconds; completed native turn: **7.217 seconds**; wrapper exit 0.
- One turn, no deadline interruption, no continuation after expiry.
- Output: `Timer smoke fixture: amber finch 42.` No research experiment ran.
- Raw logs: `~/.local/state/oc-run/timer-20261113T133440-bbyqlt2o/`.
- Export: `~/.local/share/oc-run/timer-assessment-20261113/live-session.json`.

This checks live execution and overrun; same-session continuation is established
by the installed-CLI loopback tests, not by this single-turn live smoke.

## Preservation and limits

All **384 pre-existing files** in the preservation baseline (historical run
files and relevant OpenCode configuration/agent files) retained their SHA-256
hashes. Research Git refs are identical and its checkout remains clean on
`ai/development`; neither `main` nor `Trimming` was modified. The old controller
backup branch and all existing refs remain intact. No push or merge.

Read-only tensor headers show only BF16 in the configured Sage model. MTPLX
settings still report context 262144 and `paged_kv_quantization: off`; OpenCode's
configuration retains context 262144 and output 32000. No model, server or
research configuration was changed. Native session/log creation is expected.

Detailed local evidence, source snapshots, preservation hashes and fixture
transcripts are under `~/.local/share/oc-run/timer-assessment-20261113/`.
`validation-final-tests.log` and `validation-final/` are the final passing run.

Installed the **168-line** wrapper at `~/.local/bin/oc-run`. That path was absent
before installation; existing dated backup executables were not replaced.
Source and installation have identical SHA-256
`2d903683a59518fce6aec7d02045a68e68e15ef27c31f5786a991a2d14b00c15`.
The installed command's help ran successfully. Two additional installed-copy
native tests passed (same-session continuation and active-turn overrun; exit 0,
4.208 seconds); see `validation-installed-tests.log` and `validation-installed/`.
Installation provenance is in `installation.json` alongside the local evidence.

No ten-hour, compaction-stress, reboot, terminal-disconnection, managed-background
job survival or power-loss test was run. OpenCode/provider internal retry policy
remains native; a hung native invocation can wait indefinitely because this
wrapper intentionally has no turn timeout. The rapid-turn guard is a conservative
rate safeguard and can stop three legitimate very short text-only answers;
it does not assess research quality. Raw files are not size-capped. The timer
does not serialise competing controllers in the same checkout.
