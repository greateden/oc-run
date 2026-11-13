# Existing solutions: 13 November 2026

Assessment completed before implementation. Installed CLI: **2.0.28**. GitHub's
live releases API identifies **2.3.0** (published today) as the newest stable v2;
the search index still showed 2.2.7. Neither CLI nor plugins were upgraded.

## Native OpenCode

Inspected official source tags `v2.0.28` (`026b106b`) and `v2.3.0`
(`a6b15d33`), release notes and [CLI documentation](https://opencode.ai/docs/cli/commands/).
The [official website](https://opencode.ai/) links the
[official repository](https://github.com/anomalyco/opencode).
The [2.3.0 release](https://github.com/anomalyco/opencode/releases/tag/v2.3.0)
was checked directly; no download or installer was executed.

- **Session continuation:** installed `run --session ID --format json` resumes
  a persisted conversation. `--standalone` uses this CLI's private server rather
  than the independently installed Desktop service. Native `session export`
  preserves the full conversation. No fork or implicit latest-session lookup.
- **Completion:** installed `packages/cli/src/run/noninteractive.ts` waits for
  native execution, reconciles persisted messages and reports terminal errors
  through JSON `error` events and a non-zero exit. A step finishing is not the
  whole turn finishing. The wrapper can wait for process exit instead of
  implementing a server, event subscription and execution-state tracker.
  Testing also found that an empty answer can produce no JSON records. The
  documented `--session` flag creates a missing caller-supplied ID;
  `packages/cli/src/session-target.ts` and `packages/schema/src/session-id.ts`
  confirm this. A random `ses_` ID is chosen before the initial turn, so empty
  successful turns need no session discovery. Prompts use stdin because this
  version's positional-message formatter quotes text containing spaces.
- **API/hooks:** session create/prompt/wait/interrupt and message APIs exist.
  Plugins have session hooks and event subscriptions. Latest native goals use
  `experimental.idle`; older third-party plugins use `session.idle`. These are
  building blocks, not a duration-budget command.
- **Native `/goal`:** absent from the installed source; present in 2.3.0's
  [goal implementation](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/plugin/goal.ts). It calls `ctx.session.generate` to obtain
  a structured reviewer verdict, stops on `done`, pauses on blocked/invalid
  verdicts, and has 50-round and three-stall backstops. The goal schema has no
  elapsed-time budget. This both adds prohibited research judgement and can
  stop permanently before the allocated time.
- **Native `/schedule`:** absent from installed 2.0.28. Latest
  [schedule implementation](https://github.com/anomalyco/opencode/blob/v2.3.0/packages/core/src/schedule.ts) and the schedule command/tool implement
  due-time/interval/cron scheduling and conditional checks, behind an
  experimental flag. Ordinary repeat intervals have a one-minute minimum;
  conditional checks have a 15-second minimum. These are scheduled wake-ups,
  not immediate continuation after each completed turn. Expiry and queued
  admissions do not establish the requested after-turn monotonic budget.
- **Built-in iteration:** a native turn runs its own tools/model steps;
  compaction and cache warming do not cause general-purpose idle continuation.
  No exact native working-budget workflow was found in either inspected tag.

## Third-party source review

These are author-owned third-party repositories, not official OpenCode plugins.
Read-only shallow clones were inspected outside both project repositories;
none was loaded, built or installed. Plugins execute with the host's filesystem
and network access, so a small dependency count alone is not a sandbox.

| Candidate and inspected revision | Actual stopping semantics | Assessment |
| --- | --- | --- |
| [charfeng1/opencode-ralph-loop](https://github.com/charfeng1/opencode-ralph-loop), 1.0.10, `2ef2386c` (commit 25 May; repository pushed 8 September) | `src/index.ts` resumes the same session on idle, stops on a DONE promise or iteration cap (default 100); catches continuation errors silently | No duration budget. Auto-copies commands/skills into global configuration. Old `@opencode-ai/plugin` peer; no runtime dependency listed. Not an exact match. |
| [william-ricchiuti/OpenCode-goal-plugin](https://github.com/william-ricchiuti/OpenCode-goal-plugin), 0.11.4, `1ae8144a` (30 October; pushed 2 November) | Duration, turn, token and cost caps, but accepts completion/blocked markers and evidence-gated completion; optional independent verifier; wall-clock `Date.now()` duration | Maintenance mode following native goals. 7,193-line main module plus durable state and Zod dependency. Enforces a completion policy the user explicitly excludes. |
| [ByBrawe/opencode-loop](https://github.com/ByBrawe/opencode-loop), 0.6.10, `3cb059da` (1 November) | Idle loop with `--max-runtime`; native runtime serialises same-session admission and explicitly never aborts it on expiry | Closest functional option: `/loop idle --max-runtime 10h <prompt>`. Runtime policy uses `Date.now()` and persisted creation timestamps, not a monotonic clock. Includes job persistence, scheduling, recovery, verification, branch/checkpoint operations and a daemon. Runtime dependency `@opencode/plugin` 2.0.22; optional UI peers. Over 3,900 lines in the inspected native/runtime modules alone. Considerably more machinery and install surface than this timer needs; not installed or runtime-validated. |
| [hjzccc/opencode-auto-continue](https://github.com/hjzccc/opencode-auto-continue), 0.1.1 | `src/idle-handler.ts` resumes on idle with cooldown and consecutive-count cap | No duration option. Depends on the v1 plugin package; five-commit repository. Not an exact match. |

## Decision

Implement a small Python standard-library wrapper using the installed CLI.
It owns monotonic budgeting, explicit same-session continuation, raw logging,
interruption forwarding and a narrowly bounded rapid-turn safeguard. OpenCode
owns permissions, tools, sessions, model selection and compaction. Sage owns
research decisions. No completion markers, reviewer inference, repair turns,
provider recovery, per-turn deadline or dependency installation.

Source snapshots and repository metadata are retained locally under
`~/.local/share/oc-run/timer-assessment-20261113/` for this assessment. Historical
retirement evidence remains in `RELIABILITY.md` and Git; this decision supersedes
its advisory-deadline recommendation.
