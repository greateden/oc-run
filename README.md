# OC Run: working-budget GPU handoff

This branch is an isolated replacement for the old remote `main` controller. It is **not** the user's newer, unpushed local 168-line build. Do not merge or install it without comparing that local build first.

`oc-run 10h "Research ..."` uses one native OpenCode session until the working budget ends. It never stops a healthy active turn at the deadline.

## Optional GPU handoff

[MTPLX](https://mtplx.ai/docs/quickstart/) supports `mtplx stop` and `mtplx serve`, but has **no model unload/reload HTTP endpoint**. GPU handoff is therefore opt-in, for a model server used exclusively by this research job. It does not modify any installed MTPLX settings or infer the restart command.

Write a private lifecycle file outside Git, with your **actual known-good startup command** including every important model and precision setting:

```json
{
  "exclusive": true,
  "model_id": "your-current-served-model-id",
  "health": "http://127.0.0.1:8000/health",
  "stop": ["mtplx", "stop"],
  "start": ["mtplx", "serve", "--host", "127.0.0.1", "--port", "8000", "--model", "/absolute/path/to/existing/model"]
}
```

**Do not use this illustrative start command verbatim**: preserve BF16, unquantised KV and any other options from your verified existing invocation. Check `mtplx serve --help` on your installed version first. Avoid storing access tokens in the lifecycle file. Keep the file private (`chmod 600`). The setting `exclusive: true` confirms that stopping MTPLX will not disrupt other users or clients.

Run:

```sh
oc-run --gpu-lifecycle /private/path/mtplx-lifecycle.json 15m "Research ..."
```

The initial prompt explains the handoff to Sage. When Sage decides to train, it must finish preparation, then call this from an OpenCode shell tool **without launching any process in the background**:

```sh
oc-run train -- .venv/bin/python scripts/finetune_asr.py --device mps ...
```

The `train` command registers a request and exits immediately; it does **not** start training. Sage must then end its OpenCode turn. OC Run stops MTPLX, confirms its server is down, runs the training command as a tracked subprocess and waits for completion. It restores the model service and checks `/health` and `/v1/models` before resuming the **same OpenCode session**, provided working time remains. Training time counts towards the budget.

State and logs remain under `~/.local/state/oc-run`. Training logs, the request and the exit code are retained. If training is interrupted and remains alive, restoration is deliberately withheld to avoid competing for unified memory. A failed or unverified model unload prevents training from launching.

Caveats: this does not block an agent from running unregistered shell commands, inspect every training command before trusting it. It does not control unrelated GPU processes. Stopping the MTPLX server confirms the service is down, not a precise per-process Metal memory measurement. The newer local controller and actual app-managed MTPLX lifecycle have **not** been tested by this GitHub-only implementation.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_gpu.py' -v
```

The tests use a fake OpenCode CLI, an HTTP server and a synthetic training job. No real GPU work is performed.
