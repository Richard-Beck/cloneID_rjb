# Execution and compute protocol

## Dependencies and engine

Development engine: **PhysiCell 1.14.2**. Resolve an executable/source checkout supplied or located for this execution, record
its version/hash and verify compatibility. Do not assume a local engine path. The engine is an external software dependency;
all model-specific files are bundled in this skill. Python core uses numpy, scipy, numba, pandas, scikit-image and matplotlib;
report packaging also uses plotly. Inspect existing environments first. No environment or software is installed automatically.

For a fresh engine checkout, copy `assets/physicell/baseline_runtime.cpp` from this package into its `main.cpp`, preserve the
engine core/modules/BioFVM/Makefile/license, and build with `make -j4 PhysiCell_custom_module_OBJECTS=`. The empty override
avoids duplicate custom-module symbols. Build in an isolated checkout. Generate each case's XML, rule CSV, initial cell CSV and
sample-time file, create `output/`, and run the executable with `PhysiCell_settings.xml` from that case's working directory.
The stock XML contains illustrative numbers; `core/transfer.py` replaces fitted parameters, domain, times, cycle/death and seed.
The bundled runtime handles custom initial phase/volume state, sampling and virtual walls; stock PhysiCell alone is not this model.

## Budget and starts

Before proposing budgets, run light timing smoke tests using baseline/default parameters at operating points drawn from observed
field densities: include typical seeding, terminal harvest and the densest observed fields. Briefly initialize, burn in/relax,
then measure throughput. Record initialization, relaxation, subsequent simulation and output-measurement costs separately,
with simulated duration, cell counts, hardware and CPU allocation. These tests estimate runtime; they are not fitting, biological
validation or an approximation-agreement gate. Reuse applicable measured timings or honor an explicit request to skip them.

Present implementation effort, data preparation/correctness checks, optimizer starts and limits, distinct trajectories,
concurrency, reporting allowance, per-stage elapsed time/CPU-hours and total budget. Ask about faster first-pass versus broader
search preferences when not already settled. Distinguish measured extrapolations, hypothetical scenarios and timeout ceilings;
dense/slow fitted cases may cost more than default parameters. Include queue time separately. Agree available CPUs and the
resource envelope; no unspecified overall CPU-hour cap is implied. Development used 100 starts/group/stage, five-minute limits,
600 integration steps and up to 200 CPUs; these are configurable proposals, not authorization or universal defaults.
A per-engine timeout differs from a task limit; include checkpoint/export and reporting allowance. Budget the complete baseline
as one campaign, not separately approved stage rollouts.

Default optimizer: bounded Powell in normalized coordinates, ftol=1e-5, xtol=1e-4. Save the best vector and its count conversion
atomically during search, including an initial finite checkpoint. Final selection uses that best saved vector without another
refinement stage. Initialize stationary from reproducible stratified draws inside reviewed bounds. Screening can seek finite,
low-violation initial guesses with a bounded attempt/time allowance; record rejections and never silently remove a whole group.

Use 600 duration-scaled steps for each distinct trajectory's maximum duration. Reuse trajectories only if all effective rates,
initialization, mechanics, temporal schedule and stochastic settings match; map every observation to the correct output time.
Condition, branch or episode names alone neither establish nor preclude equivalence. Do not simulate identical stationary or
constant settings once per passage. Use explicit per-episode trajectories where adaptation changes effective parameters.

For the baseline spacing diagnostic define:

```text
q(t) = neighbor_spacing(t) / (2 * mean_radius(t))
v(t) = max(0, 1.25/sqrt(3) - q(t))
penalty = mean_over_episodes( integral((v(t)/0.05)^2, t=0..duration) / duration )
search_objective = observed_data_loss + penalty_weight * penalty
```

Default penalty_weight is 1; thresholds derive from the baseline adhesion geometry. It discourages a particular closure violation;
it does not predict every transfer error. Report it separately, including violation duration and extrema. Agreement is descriptive,
not a hard gate, and cannot discard an otherwise scorable simulator result.

## Nested stages

Half of child starts come from the lowest PhysiCell-loss parent and half from other competitive, diverse parents. Default
competitiveness window is 20% of best parent loss, with diversity measured in normalized parameter coordinates. Seed and ID
ordering resolve ties. Parent selection uses completed simulator ranking, never partial completion order or approximation loss.

For N new child optimizations, allocate floor(N/2) to the best parent and the remainder to the diverse parent pool (N >= 2).
Select up to that many other parents and distribute starts round-robin; this is a total stage budget, not N starts per parent.
If no other parent is within the 20% window, fall back to other scored parents, or the best when it is the only parent; report
this fallback. Preserve one unperturbed best-parent start. A default perturbation is Gaussian noise with standard deviation
2.5% of each search-coordinate range, clipped to bounds; reject numerically invalid proposals and fall back to the exact parent.
Vary adaptation timing within reviewed bounds. Save each start's parent ID, perturbation and fallback decisions.

Keep every exact embedded parent as an eligible candidate with its unchanged simulator output, observation support and count
conversion, separately from the N new optimizations. Stationary embeds into branch-constant by repeating all fitted biological
coefficients across branches; constant embeds into adaptation by equal G1 endpoints with other branch coefficients unchanged.
Do not resimulate identical anchors just to manufacture a new score. Assert equality of all effective biological/initialization parameters, schedules and reused scores and
that child best loss does not exceed parent best loss. Changed biology, support or scoring requires a new comparison, not an
assertion that different models remain nested.

## Simulator and scheduler

Finer fixed-time defaults: 0.5-minute mechanics/diffusion clock, 3-minute phenotype updates, one CPU per trajectory. Starting domain
area is 1.5 field areas at matching aspect ratio with a central crop and virtual walls. These are recorded configuration choices;
initial-position wrapping is not periodic boundary dynamics. Choose a seed and state whether rankings use one or multiple replicates.
Hold the approximation-derived count conversion fixed during simulator scoring.

Use `submit_campaign.py` with the adapter's frozen task counts and commands. Submit the complete stationary -> constant ->
adaptation -> report campaign together. Each stage uses a `kind: stream` array containing candidate fit tasks, one finalization
task per candidate, and that candidate's trajectory tasks. Finalization depends on its own fit with `afterany`; simulation depends
on its own finalization with `afterany`. Thus a completed or timed-out fit releases its evaluations without waiting for unrelated
fits. Finalization freezes the best saved vector/count conversion and exports its manifest, including explicit missing-checkpoint
outcomes. Concurrent tasks never mutate a shared candidate manifest. Every simulator task records missing/failed inputs.

One array-wide concurrency cap covers all fit, finalization and simulation tasks, each using one CPU. Idle capacity can be used
by either phase without fixed CPU partitions. Stage scoring waits for that entire array with `afterany`; child preparation waits
for successful scoring with `afterok`, preserving completed PhysiCell-based parent ranking and the existing start-selection rules.
The outer stage nodes remain sequential to enforce the campaign-wide cap. All jobs are submitted held, candidate dependencies
and phase time limits are configured with `scontrol`, then the campaign is released. Inspect the dry plan and command manifest.
Do not run a separate stage-wide freeze job that would reintroduce the all-fit barrier. No polling orchestrates progress.

Select partition/QOS from the actual cluster and check array-size/job-count limits for the expanded stage arrays. The `%` throttle
exists specifically to enforce the agreed CPU cap; omit it when the array is already smaller. Multi-core tasks require a revised
allocation scheme. If submission/configuration fails, recorded jobs remain held until deliberate recovery; after partial release,
inspect the recorded released set before taking action. Invalid success dependencies are cancelled so downstream failure reporting
can still run via `afterany`. Final reporting must tolerate blocked or partially completed stages. External overall deadlines
need a scheduled finalizer that harvests and cancels outstanding work, then reports incomplete candidates.

Checkpoint inputs, code, bounds, proposals, seeds, iteration/time, effective rates, exported files, observed support and losses.
Record job IDs, candidate outcomes and errors. Freeze score/ID ranking. Resume only missing/failed tasks within the remaining budget;
never overwrite completed evidence or silently relaunch a whole campaign. A group with no scorable parent blocks its child fitting
and must appear in the report.

## Checks and accounting

Verify initialized phases, component volumes, units, effective rates, sample-time rounding and measured snapshot dimensions before
full launch. Short transfer checks assess correctness; do not silently turn them into agreement eligibility gates. Check full-coverage
gap zero, sparse-background fallback and finite required residuals. Numerical errors are candidate failures, not observed-data exclusions.

Report serial elapsed time from campaign start to completion, summed actual CPU-hours and peak simultaneous allocated/used CPUs
as distinct quantities. SLURM ElapsedRaw * AllocCPUS estimates allocated core-hours; TotalCPU measures CPU usage. Derive peak
allocation from overlapping job intervals. Include fitting, simulation and reporting separately and identify queue time.

## Package checks

Run `python scripts/test_package.py` from a copy of the skill using the chosen Python environment. It uses synthetic inputs to
check nesting with arbitrary branch counts, scoring boundaries, image coloring, parameter export, checkpoints, the CPU cap and
report packaging. `python scripts/check_browser.py --chrome /resolved/browser/executable` additionally exercises report controls
and an empty-result group (requires websocket-client). Neither check submits jobs, requires project data or invokes PhysiCell.
These checks cover the packaged primitives; the confirmed dataset adapter and engine build still need their own transfer checks.
