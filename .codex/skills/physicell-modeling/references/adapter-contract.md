# Dataset adapter and campaign contract

Write the adapter inside the active analysis folder after confirming the scientific choices. The bundled primitives are reusable;
the adapter resolves observation schemas, groups, conditions, branches, bounds and engine paths. Do not import another study's
loader or parse scientific group membership from filenames. The package does not ship a universal end-to-end data loader.

## Core interfaces

Add the copied skill's `scripts/` to Python's import path. Import `core.colony`, `core.fitting`, `core.assumptions`,
`core.spatial`, `core.transfer` and `core.fields` as needed.

- `colony.simulate_with_geometry(p, rate, times_days, dt, T, mu)` takes natural-unit
  `[xeq,speed,K,radius,density,cluster_size,initial_volume,G1_fraction]`, a constant uncrowded rate/day and sorted nonnegative times.
  Returns n x 29 predictions (log density, coverage, log gap, CE, 25 relative log-area quantiles) and a geometry trace.
  Its fixed step must satisfy numerical stability; use 600 duration-scaled steps by default. This primitive does not implement
  condition changes within one episode; extend both engines if the confirmed model requires them.
- `fitting.hill`, `medium_multiplier`, `sigmoid_rate` and `embed_rates` support the agreed rate model. Width means the 10%-90%
  transition span, not inverse steepness. `embed_branch_parameters` repeats stationary scalar biological coefficients across
  branches and carries constant branch arrays unchanged into adaptation. Route the complete branch vector to both engines;
  a rate-only mapping would silently leave mechanics/response shared. Keep initialization and observation sharing separate.
- `fitting.stratified_starts` operates in explicitly transformed coordinates; `diverse_parents` returns competitive other parents.
  The adapter applies the half-best/half-other allocation, bounded perturbations and documented fallback if few parents qualify.
- `fitting.bounded_search` saves the best record atomically and produces termination status. Return objective `loss` plus separate
  `data_loss`, `assumption_penalty`, `count_offset` and other metadata from the evaluation callback. Use a hard outer job limit.
- `fitting.composite_score(predicted,observed,scales,weights,coefficients,offset)` accepts n x 29 matrices and n x 5 episode-balanced
  weights ordered count/coverage/relative-area/gap/CE. Observed first column is log count. `offset=None` profiles count conversion;
  pass the frozen offset for simulator scoring. Gap columns are logged and floored at zero before comparison. Unsupported terms
  have zero weights, while missing required predictions are errors. Confirm weights/scales; do not fit them opportunistically.
- `assumptions.summarize_trace` reports a duration-normalized spacing penalty and violation summaries.
- `spatial.measure`, `mask_measure`, `aggregate` implement the baseline field operators. Their default scale is a 10-pixel closing,
  30-pixel border and stride 4; adapt the matched observed/simulator operator together when resolution changes. Bootstrap fields.
- `transfer.export_case(directory,p,rate,seed,times_minutes,domain_size,...)` creates an independent case using bundled assets.
  `initial` implements clustered initialization; `snapshot(path,domain_size,field_shape,crop_origin)` reads simulator observables.
  Dimensions/crop are explicit; the fixed-delay and death parameters must match the approximation. The adapter runs the engine.
- `fields.colour_labels` and `simulated_labels(snapshot,shape,crop_origin)` render deterministic adjacency-colored labels. Record
  crop, spatial/time conversion and source hashes separately; rendered labels are for display, not a replacement for full-disk area.

## Required adapter operations

1. Freeze cleaned observations, episode membership, condition schedules, units and measurement uncertainties. Declare parameter
   names, transforms, bounds and sharing. Deduplicate common ancestry observations. Persist the scientific agreement.
2. Prepare deterministic starts and exact anchors. Freeze candidate and trajectory-slot manifests with arbitrary group/branch
   counts before submission. Slot counts must not depend on optimization outcomes: reserve distinct episode/settings slots where
   needed and record reuse/no-op outcomes for verified equivalents. No stage assumes a particular ancestry or branch count.
3. Optimize with per-start atomic checkpoints. Finalize each candidate independently after its fit terminates, including on
   timeout: freeze the best saved vector and count conversion, and write only its own immutable trajectory/export manifest.
   Record a missing checkpoint as an explicit outcome; do not wait on other fits or resubmit a failed optimization.
4. Run the candidate's trajectory tasks after its finalization terminates. Export each final vector, invoke the supplied engine
   with timeout, collect snapshots/metrics, and write a success/error outcome. A failed finalization must not expose an older
   manifest as if it belonged to this attempt; require the matching frozen candidate ID and attempt provenance.
   Reuse exact parent sources. Record candidate ID, group/stage, parameter vector, count offset and frozen support/scoring IDs.
5. Score all completed new candidates and anchors on the same support, check inherited equality and monotonic best loss, select
   stage winners and create the child-stage seed pool. No scorable parent is a blocking stage outcome with a failure report.
6. Render fields and construct the generic report data, score CSV and source manifests. Record actual compute accounting.

## Scheduler input

`submit_campaign.py SPEC.json` writes a dry plan; add `--submit` to launch a reviewed plan. The JSON has:

- `submission_root`: a new path inside this run; `max_cpus`: positive integer.
- Optional `partition`, `qos`, `account`, resolved from the actual scheduler; `python` is the resolved compute-node Python
  executable (defaults to the launcher's interpreter).
- `scientific_contract_confirmed`: true only when the user has actually agreed to the scientific structure. Separately record
  the agreed resource envelope before submission; this flag does not grant permission for arbitrary compute budgets.
- `nodes`: ordered stage-level objects with `name`, `cwd`, optional `memory` (default `6G` per task), `depends_on` (previous
  node name, omitted for the first), and `condition` (`afterok` or `afterany`). These outer nodes form a serial chain.
- Ordinary nodes (`kind: command`, the default) also supply `command` (argv list, never shell text), `minutes`, and `tasks`
  (default 1). Use these for preparation, scoring, report-data, field rendering and final packaging.
- Streaming stage nodes (`kind: stream`) supply `trajectories_per_candidate` (positive counts in frozen candidate order),
  plus `fit`, `finalize`, and `simulate` objects, each with `command` (argv list) and `minutes`. There is no whole-stage fit barrier.

A streaming node, with illustrative counts/limits to replace using the adapter and measured budget:

```json
{
  "name": "stationary_candidates", "kind": "stream", "cwd": "/current/run",
  "depends_on": "stationary_prepare", "condition": "afterok", "memory": "6G",
  "trajectories_per_candidate": [2, 3],
  "fit": {"command": ["/resolved/python", "adapter.py", "fit", "stationary"], "minutes": 5},
  "finalize": {"command": ["/resolved/python", "adapter.py", "finalize", "stationary"], "minutes": 2},
  "simulate": {"command": ["/resolved/python", "adapter.py", "simulate", "stationary"], "minutes": 20}
}
```

For C candidates, the stage array contains C fit tasks, C finalization tasks, then sum(trajectories_per_candidate) simulation
slots. The dispatcher sets `SLURM_ARRAY_TASK_ID` to the adapter-local fit/finalize candidate index or flattened simulation index.
It also sets `PHYSICELL_CANDIDATE_INDEX`, `PHYSICELL_PHASE`, and (simulation only) `PHYSICELL_TRAJECTORY_INDEX` within that
candidate. `PHYSICELL_ARRAY_TASK_ID` retains the actual scheduler index for accounting. Commands read environment variables
rather than expecting shell substitution in argv. The dispatcher's path and Python must be accessible on compute nodes.

Each candidate follows fit -> finalize -> its simulations, with `afterany` dependencies to salvage timed-out checkpoints and
record failures. Fit tasks are materialized before finalization dependencies, then finalization before simulation dependencies.
The launcher sets phase-specific time limits while the stage array is held. All tasks use one CPU and the node's shared memory
request. A single array throttle enforces the CPU budget across phases; the scheduler can use freed capacity for any ready task.
Check Slurm `MaxArraySize` and pending-job limits for these expanded arrays before launch; do not silently chunk arrays into
independently capped jobs that could collectively exceed the budget.

Typical outer nodes: prepare -> stream -> score -> next prepare ... -> report-data -> field-render -> report-package.
Scoring uses `afterany` on the streaming array; next preparation uses `afterok` on scoring so it sees the completed PhysiCell
parent ranking. Reporting must tolerate incomplete/blocked stages and run through appropriate `afterany` dependencies.
All nodes are submitted held and released only after configuration succeeds. `scheduler_commands.json`, `jobs.json` and
`submission_status.json` record submissions/configuration/releases, including partial failure. Dry runs do not create jobs.json.
Inspect recorded jobs before recovering; the launcher neither automatically retries nor imposes an overall deadline.

Do not mark a plan runnable merely because the dry-run passed: test adapter initialization, full biological-parameter embedding,
scoring, per-candidate finalization and a small transfer before campaign launch. A narrow scheduler probe should verify array-task
dependencies on the target cluster when this launcher is first deployed there. Such a probe is separate from runtime benchmarks
and must not launch fitting or a full simulation campaign.
