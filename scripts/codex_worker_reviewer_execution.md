# Worker-reviewer runner

`codex_worker_reviewer_execution.sh` runs each selected plan phase through one persistent Codex worker session and separate ephemeral
reviewers. The initial runner and every full continuation use the resources configured by `TIME`, `MEM`, `CPUS`, and `QOS`.

The canonical repository plan is `plans/seed1_hypothesis_test_v3/plan.json`, which is also the launcher's default. Set `PLAN_DIR` or
`PLAN_JSON` explicitly to run another compatible plan without changing the canonical plan.

## Long SLURM work

The worker's final response follows `prompt_templates/codex_worker_turn.schema.json`:

- `COMPLETE` sends the phase to the reviewer.
- `WAIT_FOR_SLURM` supplies controlling job IDs, purposes, logs, and expected outputs.

The schema itself uses the JSON Schema subset accepted by Codex structured output. Cross-field invariants—`COMPLETE` having no jobs and
`WAIT_FOR_SLURM` having one or more unique controlling job IDs—are checked by the runtime after the Codex call.

After `WAIT_FOR_SLURM`, the runner:

1. Saves the worker session ID and an atomic checkpoint.
2. Submits a full-sized `afterany` continuation with `--kill-on-invalid-dep=yes`.
3. Submits a small independent watchdog.
4. Exits the current allocation.

The continuation calls `codex exec resume <SESSION_ID>` and sends only the new scheduler reconciliation. The same worker session is also
resumed for reviewer-requested revisions. Reviewers remain independent and ephemeral.

The watchdog periodically reconciles scheduler state. It submits a dependency-free, full-sized recovery continuation when the ordinary
continuation is cancelled or otherwise terminal without advancing the checkpoint, when all target jobs are terminal, when a previous
resumption was interrupted, or when `MAX_SLURM_WAIT_HOURS` is reached. It never cancels the worker's compute jobs.

An advisory lock plus monotonically increasing resume generation prevents a normal continuation, watchdog recovery, or stale watchdog from
resuming the same session concurrently.

## Principal settings

- `WATCHDOG_INTERVAL_MINUTES` defaults to `30`.
- `MAX_SLURM_WAIT_HOURS` defaults to `168`.
- `WATCHDOG_TIME`, `WATCHDOG_MEM`, and `WATCHDOG_QOS` default to `00:10:00`, `1G`, and `small`.
- Relative worker-supplied log and output paths are resolved against the phase work directory.

The run records its active state in `run_status.json` and its worker state in `orchestration/worker_checkpoint.json`. Each phase records its
session ID in `worker_session.json`. Initial worker turns, resumed turns, and scheduler reports are retained under the corresponding iteration
directory.

The launcher, runtime module, plan, prompt templates, and schemas are copied into `orchestration/` and hashed before the first worker turn.
Continuation jobs run those frozen launcher/runtime snapshots.

## Smoke test

```bash
scripts/tests/test_codex_worker_reviewer_resumption.sh
```

The test uses fake Codex and SLURM commands to exercise yield, dependency failure, watchdog recovery, same-session resume, reviewer failure,
same-session revision, and final pass without submitting real jobs.
