# Reliability investigation — 13 November 2026

The starting checkout was `c088e75`. The shell executable was a byte-identical
copy at `~/.local/bin/oc-run` (SHA-256
`aa905a58993c5bc2ffcfa6e68b203d5a61783f02127e1190c2c1b0a708aeb4b5`).
OpenCode was `~/.opencode/bin/opencode`, reporting `v2.0.28`.
Installation copies the single Python file; there is no separate package version.

## Confirmed historical findings

- **11 November, 23:28:** the older controller killed three work invocations at
  approximately 1,500 seconds each. Its logs show fixed safety limits, not evidence
  establishing a stall. Its final invocation exited 0, but the old checkpoint
  contract rejected missing disclosures for two failed tool calls. Useful work
  remained unverified. The starting checkout had already removed those fixed
  invocation limits; this patch does not reintroduce them.
- **12 November, 23:33:** the provider reported insufficient memory during prefill
  after about 5,281 seconds. It said its engine had cleared caches and remained up.
  The last tool was followed by eleven step starts over roughly 281 seconds,
  consistent with OpenCode's own ten-retry policy. The controller then stopped on
  exit 1 without recovery. Native persisted messages identify the agent as `build`.
  The competing memory consumers and whether another request would fit were not
  established; engine availability is not sufficient memory headroom.
- **13 November, 11:17:** OpenCode exited 0 after about 471 seconds, with a shell
  command in assistant text rather than an executed call or final report. Its
  native outcome was `succeeded`, which describes execution, not task acceptance.
  The controller correctly refused success but only attempted report repair after
  a stop, so this early exit got no repair. Native messages identify `sage-research`.
  The logs establish the malformed output, not why Sage produced it.

Ordinary tool failures were already recorded without failing the invocation.
One additional correctness defect was reproduced: nested native shell timeout
metadata without an exit code was counted as a successful tool. It now remains
uncertain and prevents automatic continuation.

## Small correction

The existing session, journal, locks, guardian and completion contract remain.
One bounded loop permits at most two extra invocations, with 2s/4s backoff.
Known transport/timeout failures and the specifically recognised cache-clearing
prefill OOM can qualify. Arbitrary OOMs, authentication errors, unknown errors and
unexpected process exits cannot.

Before another invocation, native reads must confirm the original session and
location, with no active execution, child session, queued input or managed shell.
Incomplete, malformed or timed-out tool observations also prevent recovery.
Any child session requires manual inspection because its events are absent from
the parent CLI stream. No new session is silently created.

A missing or invalid result receives one handoff-only repair opportunity, using
that same allowance. Each handoff invocation has a 120-second limit. Repeated
malformed reports stop with a controller diagnostic. Provider recovery starts no
new work after the cooperative deadline or a stop request. Signals retain the
existing interruption behaviour and preserve durable evidence.

No dependencies, public flags, provider settings or research files were changed.
OpenCode still resolves the project agent/model itself. Recovery prompts require
inspection of saved outputs and running jobs before further experiments.

## Validation and limits

The original suite passed 51 tests with two native tests skipped. Three new
regression tests run against the original controller reproduced four assertions:
missing report repair, OOM continuation, transport continuation, and false shell
timeout success. Deterministic fixtures exercise the actual nested event format.

The native integration uses the installed CLI/server, a real lightweight shell
tool, project agent configuration and a loopback fixture provider. It checks
same-session report repair and incomplete status, without Sage inference. Existing
native tests cover durable steering across server restarts and hidden child events.
The focused tests also cover retry exhaustion, refusal around uncertain work,
deadline handling, interruption during backoff, bounded handoff, unchanged outputs
and an unrelated process remaining alive. Full results are recorded locally.

Final validation: Python 3.12 at
`/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`, running
`OC_RUN_NATIVE_BIN=~/.opencode/bin/opencode python3 -m unittest discover -s tests -v`:
**66 tests passed, no skips, 129.673 seconds, exit 0**. The public `--help`
interface is unchanged. `git diff --check` also passed. Baseline regression and
final suite logs are under
`~/.local/share/oc-run/bounded-recovery-20261113T114402/`.

This is lifecycle validation, not a scientific acceptance test or proof of
ten-hour stability. No historical experiment, model download, training or real
Sage request was run. No resource scheduler was added. Deadlines and handoff-only
instructions are cooperative; arbitrary detached jobs and model behaviour cannot
be guaranteed. Native checks are point-in-time observations. Private-server
teardown can terminate its managed jobs; detached processes can survive tool
timeouts. Inspect jobs before a manual resume. BF16, context capacity and KV cache
settings remain under the owner's control.

## Versioned upstream evidence

The official documentation links to the Anomaly repository. The following
`v2.0.28` source files were retrieved and read; no downloaded code was executed:

- [CLI event/completion handling](https://github.com/anomalyco/opencode/blob/v2.0.28/packages/cli/src/run/noninteractive.ts)
- [Session selection](https://github.com/anomalyco/opencode/blob/v2.0.28/packages/cli/src/session-target.ts)
- [Native session API](https://github.com/anomalyco/opencode/blob/v2.0.28/packages/protocol/src/groups/session.ts)
- [Provider retry policy](https://github.com/anomalyco/opencode/blob/v2.0.28/packages/core/src/session/runner/retry.ts)
- [Shell tool](https://github.com/anomalyco/opencode/blob/v2.0.28/packages/core/src/tool/plugin/shell.ts)
  defaults to a 120-second foreground timeout; background commands default to no
  timeout and notify the session on completion.
- [Shell process handling](https://github.com/anomalyco/opencode/blob/v2.0.28/packages/core/src/shell.ts)
  attempts termination on timeout, with a three-second forced-kill allowance.
  That is not proof that every detached descendant has stopped.
