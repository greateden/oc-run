# Controller retirement: 13 November 2026

Historical retirement record, preserved below. The later explicit working-budget
requirement is implemented by the minimal timer described in [README.md](README.md).
See [ASSESSMENT.md](ASSESSMENT.md) and [VALIDATION.md](VALIDATION.md) for the new
decision and executed checks. The advisory-deadline recommendation below is
superseded; historical logs, backups and conclusions about research remain intact.

## Decision

**Option A: remove oc-run from the active workflow.** There is no production
implementation left to maintain. A thin wrapper would still own signals,
timing, pipes and another status interpretation. No observed failure justifies
that additional layer for the current workflow. Shell redirection and native
session export provide the optional logging convenience.

Removed: completion schemas, checkpoint acceptance, handoff repair, provider
classification, recovery retries, event summaries, tool-error accounting,
journals, private-server supervision, process guardians, workspace locks and
controller Git policy. Native permissions and the existing research agent
remain responsible for their respective work. A soft deadline is an instruction,
not an external timer. Loss of wrapper locking is addressed by one active session
per checkout, not a replacement lock service.

The installed executable and repository source had identical SHA-256
`0d7150af0e4cd33d22ffda94302029aa7479437bb033ec99a1fe96182af8f6db`.
Both matched the implementation at `1c36a97` on `fix/bounded-session-recovery`.
Implementation was 997 lines; the four old test/fixture files totalled 1,324.
All are removed; only five opt-in native workflow tests remain.

## Installed native capabilities

`~/.opencode/bin/opencode --version` returned **opencode v2.0.28**.
A separate Desktop background service was running its **2.2.7** binary. The
recommended command uses `--standalone` to execute the tested CLI's own server;
no service was stopped or upgraded.

| Responsibility | Installed evidence and chosen use |
| --- | --- |
| Non-interactive execution | `run --help`: message arguments, `--format json`, `--standalone`, `--print-logs`; exercised with fixtures and Sage |
| Project agent | Existing `default_agent: sage-research`; `debug agents` identified it as primary; copied unchanged into fixture project and observed in provider prompts |
| Model | Native `--model` exists; deliberately omitted; live exported session identified MTPLX `internscience-sage-a1-5-mlx-bf16-validated` |
| Tools and jobs | Native shell execution, failed exit and continued generation exercised; short explicitly detached process completed; managed background-job survival across shutdown is not established |
| Context | Effective config: native auto compaction with buffer 16000; context 262144 and output 32000; no setting changed, compaction not stress-tested |
| Logs and persistence | Raw JSON stdout, diagnostic stderr, native session list/export; same-session continuation after private-server exit tested |
| Interruption | Native CLI SIGINT exited 130, completed tool file/events retained; no external group kill |
| Time limits | No overall duration/deadline flag in installed `run --help`; use advisory absolute UTC deadline in task; no timed stop guarantee |

Consulted official [CLI commands](https://opencode.ai/docs/cli/commands/),
[configuration](https://opencode.ai/docs/config),
[tools](https://opencode.ai/docs/tools) and
[compaction](https://opencode.ai/docs/compaction/) documentation. These pages
also describe newer releases; installed help and observed 2.0.28 behaviour take
precedence. No software was downloaded or installed.

## Historical failures

All paths below are under `~/.local/state/oc-run/` and remain unchanged.

| Run | Execution evidence | Failure attribution |
| --- | --- | --- |
| `20261111T232818-p39280-p56kfrha` | Controller log records three 1,500-second safety timeouts; finalisation exited 0 after 1,386.90 seconds; overall 5,932.52 seconds, controller exit 124 | Controller killed its work rounds, then rejected finalisation for missing disclosure of two historical tool call IDs. Removing it removes both mechanisms. Scientific completion was not established. |
| `20261112T233339-yby2phrg` | 10-hour budget; stopped after 5,281.41 seconds; native exit 1; stream contains `provider.internal` prefill insufficient-memory error | Real provider request failure, not proof the MTPLX engine died. Removing the wrapper does not cure OOM. Saved work remains partial. |
| `20261113T111742-7_wqmpm1` | 30-minute budget; 470.76 seconds; native exit 0, no error event; last assistant output was an unexecuted shell command | Model output/tool-use failure and unfinished scientific task. Controller additionally imposed exit 1 for missing contract. Native execution alone does not repair the unfinished task. |
| `20261113T120858-tauv23ns` | 15-minute budget; two native exits 0; no provider error event; controller exit 1 after 575.04 seconds | Model supplied substantive output but omitted required JSON `summary` twice; controller rejected it and added an unnecessary repair invocation. No budget expiry or provider recovery caused this stop. |

### Latest event stream

Times are relative to the journal's `running` record (UTC 11:08:58.176).

- +0.317s: work invocation starts.
- +6.241s: session `ses_e2b675050ffeCaf4pneuFBtXDw` recorded.
- +526.712s: work invocation exits 0. Stream has 48 step starts, 47 tool
  events, 47 step finishes and one final text event. No error event.
- +526.714s: controller schedules repair for "final result missing or invalid".
- +528.770s: native recovery check passes; agent/model fields in its journal
  are null, so that record does not verify model identity.
- +528.770s: same-session handoff invocation starts.
- +574.860s: handoff exits 0; it has one step start and one final text event.
- +575.071s: controller records failed/exit 1. Stored elapsed is 575.041s
  because final journal writing occurs after elapsed is measured.

Both final texts contain `OC_RUN_RESULT` with `decision`, `complete`, `reason`,
`evidence` and `next`. Neither has `summary`; `final_report()` requires it.
The controller's `(not failed and repaired)` branch then rejects the second
answer. The `recovery exhausted or unsafe` wording conflates conditions: this
run exhausted its one format-repair opportunity, not its working budget.

The report's claim that only shell was used and no tools failed is false.
There are 47 distinct tool calls and six failures:

| Call ID | Failure | Later recovery evidence |
| --- | --- | --- |
| `call_c4e3125e3d094869a41ba641` | Shell syntax sent to JavaScript `execute` | Subsequent direct shell calls ran successfully |
| `call_9c6685cc` | Guessed reference filename absent | Later scoring used explicit variety-to-filename mapping |
| `call_8a44d080` | Non-existent `BLEUScore.format_score` | Later scoring printed `score.format()` |
| `call_8a6add4f` | Non-existent `BLEUScore.toks` | Final scores obtained without that attribute |
| `call_292d919b` | Invalid Python assignment expression | Corrected all-variety scoring executed successfully |
| `call_de826b6a` | Sorting tied tuples compared dictionaries | Later error-inspection command used a numeric sort key |

These are historical failed attempts, not six unresolved failures of the final
scoring calculation. Native execution preserves them without converting them
into a separate scientific-completion gate. The latest run also committed
research documentation as `1d1e878` on `ai/development`; this task did not alter it.

### Independent saved-output check

Used the existing research `.venv/bin/python -B` and SacreBLEU 2.6.0, with no
inference, downloads, file writes or transcript printing. For each variety,
excluded canary segment 0 and records marked `is_bad_source`; asserted 960
unique prediction and reference keys, exact key-set equality, matching German
sources and matching embedded references. No silent truncation; no empty outputs.

| Variety | Pairs | BLEU | chrF++ |
| --- | ---: | ---: | ---: |
| Grischun | 960 | 47.58 | 69.40 |
| Puter | 960 | 45.34 | 67.87 |
| Surmiran | 960 | 40.04 | 64.10 |
| Sursilvan | 960 | 43.55 | 66.55 |
| Sutsilvan | 960 | 41.30 | 64.69 |
| Vallader | 960 | 43.69 | 67.48 |

Computed `BLEU().corpus_score(hypotheses, [references])` and
`CHRF(word_order=2).corpus_score(hypotheses, [references])` against the separate
saved JSONL reference files. Signatures:

```text
nrefs:1|case:mixed|eff:no|tok:13a|smooth:exp|version:2.6.0
nrefs:1|case:mixed|eff:yes|nc:6|nw:2|space:no|version:2.6.0
```

This independently reproduces the numbers. It does not audit checkpoint
exposure, prove held-out generalisation, validate every interpretation in the
report, or establish any German-guided ASR improvement.

## Validation and preservation

Before removal, `python3 -m unittest discover -s tests -v` ran 66 old tests in
124.723s: 63 passed, three opt-in native tests skipped; exit 0. No model inference.
The new five-test suite exercises installed 2.0.28 with a loopback provider:
failed shell exit 7 followed by useful output, empty final answer, terminal
provider error, same-session resume/export, diagnostic stderr, project agent,
SIGINT and a short detached job. This is native integration with synthetic model
responses, not a scientific experiment or long-term reliability demonstration.
Final command: the README's `OC_NATIVE_BIN` / `OC_NATIVE_AGENT` unittest command;
five tests passed in 5.565s, no skips, exit 0. README shell blocks passed `zsh -n`
and `git diff --check` passed. No fixture OpenCode server or experiment remained
in the final process inventory; the pre-existing Desktop and MTPLX processes
remained running.

Initial fixture execution inherited an incorrect `PWD` despite Python's `cwd`;
agent discovery and two fixture paths failed. Correcting the fixture environment
to the selected project made all checks pass. The two misplaced fixture marker
files were moved into the external backup. No research files were involved.

One valid live Sage smoke in an isolated copy of the agent returned
`NATIVE_SMOKE_OK` in 2.34s, exit 0, no tools. Native session export confirmed
`sage-research` and the configured MTPLX Sage BF16 model. An earlier smoke used
the incorrect inherited directory and is retained as diagnostic evidence, not
used to validate project selection. No long research session was launched.

Same loopback scenario comparison: native CLI exit 0 after two provider requests
(tool plus partial answer); old controller exit 1 after three requests, including
a handoff repair. It preserved useful text in both cases. This reproduces the
unnecessary controller failure without replaying private research.

Backup: `~/.local/share/oc-run/retirement-20261113T113106Z/` holds the old installed
executable, all Git refs in `source.bundle`, original global instructions,
preservation manifest, comparison logs and live smoke logs/session export.
Source rollback is also available at `backup/pre-native-20261113` / `1c36a97`.
The global instructions' obsolete oc-run section and checkpoint-acceptance clause
were removed after backing up the original. The project agent still mentions an
external controller; it is preserved unchanged and the direct launch prompt
explicitly identifies that there is no controller or reporting contract.

No pushes or merges. This task made no changes to research branches, results,
configuration, model precision, context limit or KV cache. All 52 historical
evidence file hashes match; saved MT inputs and research configuration hashes
match; all 33,712 local file size/mtime entries are unchanged. The research HEAD
also remains unchanged. The initial preservation assertion caught concurrent
documentation edits: README changed; RESEARCH_STATUS, ROADMAP, TODO and two
research documents disappeared from their former paths, with new METHODS and
archive paths present. These changes were left alone. Therefore the whole
research worktree cannot be described as unchanged. The external
`preservation-result.json` records the exact paths and final status. Instructions
for usage and rollback are in the README.

## Limits

No ten-hour, power-loss, native compaction-under-pressure, real OOM recovery,
managed-background-job shutdown or live Sage tool-use validation. Native parent
CLI output may omit child-session activity; inspect native child transcripts
when relevant. Tool side effects can outlive a timeout or interruption. There is
no automatic retry, workspace lock or safe deadline enforcement. Handling these
with guarantees would require additional orchestration; this change deliberately
makes those limits visible and leaves resumption to an informed user.
