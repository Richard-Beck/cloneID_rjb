# Fresh baseline fitting from prepared data

Use this procedure for the lineage-determined and perspective-guided baselines. They define identity and parameter sharing in different
ways; neither definition requires SUM-159, hypoxia, two founders or two genomic states. The SUM-159 adapter records one successful pilot
workflow. A different lineage needs its own evidence, observation mapping and agreed model choices.

## Boundary and entrypoint

Database preparation and laboratory-record reconstruction precede fitting. Fresh fitting starts from accepted prepared measurements,
curated episodes/lineage edges and accompanying assays. Reuse those data with their provenance; exclude old fitted vectors, optimizer
checkpoints, rankings and predictions as initialization inputs. Raw reconstruction is a separate task when requested.

The maintained source is `scripts/baselines/` within this skill; the repository entrypoint is `scripts/run_baselines.py`, with example
configuration at `examples/sum159/baseline.json`. Configuration paths are relative to the configuration file. Use an environment with
the required scientific Python dependencies; the runner uses the current interpreter unless explicitly configured otherwise.

From the repository root:

```bash
python scripts/run_baselines.py mock --config examples/sum159/baseline.json --output tmp/baseline_mock
python scripts/run_baselines.py dry-run --config examples/sum159/baseline.json --output tmp/baselines/planning
```

The mock command uses synthetic fixtures. A real dry run requires the configured local prepared data and engine prerequisites and
writes a plan without fitting, simulating or contacting SLURM. The example keeps execution disabled. `preflight` distinguishes setup
validation from permission/resource readiness; a strict readiness failure is not evidence that a scientific run occurred.

Read [the example](../../../../examples/sum159/README.md) for completed pilot results, fresh-attempt outcomes and local-path configuration.
The first fresh attempt stopped at an overly strict competitive-parent prerequisite; that quality cutoff is now a preference with
explicit fallbacks. A later attempt completed all approximation fits but exhausted storage during native evaluation and was canceled.
Synthetic/static coverage and partial scientific execution do not establish successful end-to-end calibration.

## SUM-159 model and observations

The lineage model first fits a shared biological vector, then founder-specific vectors coupled by ridge. Biology is constant across
arms/passages within a founder in this pilot; the recorded oxygen history drives the specified oxygen response. The perspective model
shares biology by current 2N/4N genomic state across founders and treatments. Its pre-existing mixtures change through differential
division and survival, with zero state transitions. Density and cluster initialization are shared.

Initialize perspective candidates preferentially from competitive simulator-ranked shared lineage parents produced by the **same new run**. The
founder-ridge vector is not the parent: founder-specific density/cluster parameters do not embed in the perspective parameterization.
Check the shared physical embedding explicitly; stochastic native realizations need not have identical scores.

The 20% competitive window is an initialization preference. Fill a scarce pool with other valid current-run shared parents; one valid
parent is sufficient. If complete native evidence is unavailable, use explicitly labelled partial-native, approximation or fresh-design
fallbacks from this run. Check numerical embedding before use. Full native support takes precedence; compare partial losses only within
the same support pattern, with component and requested-weight coverage recorded. Never substitute an approximation loss for a native loss.
Poor fit quality, missing simulations and fewer-than-requested candidates remain visible through the final report. Identity, input
integrity and physical-mapping failures remain errors.

The accepted observer has 30 columns: log1p(total retained live + dead count), log1p(dead count), coverage, logged gap, Clark-Evans
organization and 25 relative log-area quantiles. The composite cost weights total count at 0.5 and each of dead count, coverage,
relative area, gap and organization at 0.1. Score each simulator seed separately, then average replicate losses. Preserve the configured
units, normalizations and balancing; this is a composite residual, not a likelihood of independent observations. The generic older
29-column/five-component core is not this observer.

Keep microscopy loss, assay deviance, ridge penalties and approximation/closure guidance distinct. Native ranking uses the specified
native score, never the optimizer score as a substitute.

## Fixed pilot procedure

The public configuration and numerical source encode the following procedure, with deterministic seeds and tie-breaking. Freeze their
identities with prepared inputs before a new run. These counts describe the pilot adapter, not mandatory defaults for every study.

1. Fit 512 fresh shared lineage starts. Select a bounded pool of 256 final vectors for evaluation with two native seeds and rank the
   supported results. Fit 100 founder-ridge starts at each alpha in 0, 1, 10, 100 and 1000 from those new parents; evaluate 40 per alpha
   (200 total) with two native seeds and retain shared anchors. Preserve the pool-to-original-candidate mapping and final-vector hashes.
2. Generate 996 perspective exploratory starts (249 per alpha) from this run's competitive shared parents, across four configured regularization
   strengths. Check the shared embedding and retain the permanent shared anchors.
3. Screen 24 candidates: five best objective values plus one maximin parameter-diverse choice per alpha. Diversity choices come from
   the best 60% of valid candidates, with a pool floor of 30 and cap of 100, using normalized/transformed parameter distances. The two
   shared anchors replace the final diversity slots in the first two alpha buckets.
4. Evaluate 24 selected passages with two native seeds plus same-oxygen minority probes at 1%, 5%, 95% and 99%. Record failures and
   calculate native diagnostics. Run four independent local refinements, each bounded at 100 seconds, for eligible non-anchor sources
   with an available correction, matching source/correction vectors and finite native microscopy bias. Partial support remains labelled;
   anchors and unavailable/invalid corrections receive explicit outcomes.
5. Rank supported original/refined options by corrected approximation microscopy + native-screen bias + corrected assay deviance +
   ridge penalty, retaining the best option per source. Take the best two distinct sources. Choose the third by maximin parameter
   diversity among the remaining top 12 sources within `best + max(1, 0.2 * abs(best))`; fall back to the next supported source if that
   pool is empty. If fewer distinct sources are valid, retain those available and record the shortfall. Freeze the selected vectors and independently evaluate all 118 passages with four seeds plus minority probes.
6. Report the saved validation evidence and **accept the fit for now**. Validation does not trigger another correction, refit or native
   batch. Missing tasks remain visible rather than being treated as zero loss.

The executed procedure ends here. Co-located exploratory serial/alternating scripts from the pilot directory were not executed phases
of this protocol; do not infer additional required phases from their presence.

[terminal.py](../scripts/baselines/terminal.py) implements screen eligibility, transformed distances, deterministic ties, refinement
eligibility and finalist selection; the configuration supplies their numerical settings. These rules determine the followup batches
without another discretionary selection step. Additional refinement starts retain the same source correction and physical model;
finalist selection deduplicates sources rather than treating refinement replicas as independent finalists.

## Execution and reporting

Inspect the concrete dry-run dependency plan against the authorized resource envelope before scientific submission. Synthetic checks
and a saved plan are useful preparation; existing user authorization governs whether to launch. Use SLURM for substantial work, honor the agreed campaign CPU cap and retain
completed results on failure. Resume only the requested missing work rather than silently expanding the campaign. Queue delay must not
consume a scientific stage allowance. Per-case engine timeouts bound failed simulations; saved snapshots at the exact requested times
can still contribute explicit partial evidence. After individual worker failures, dependent reducers and reporting still run.

The project default is at most 1,000 concurrent CPU cores for one hour, with a 1,000 CPU-hour ceiling. The controller reserves one
core, leaving at most 999 worker cores. Scientific work is harvested 55 minutes after the allocated budget-start job begins, leaving five minutes for saved-evidence
reporting and cleanup. Subsequent queue waits are visible in this execution clock; the utilization replay removes scheduler waiting
separately. A budget limit produces a clearly labelled partial result rather than
discarding completed work. Actual completion time and CPU use remain measured outcomes.

Count all project-created copies toward the 50 GB durable / 100 GB transient storage limits, including shared and node-local copies.
Validate the retained project footprint before submission. Native workers stream bounded cell frames to the existing observer, save
compact metrics and selected figure fields, and discard raw fields after measurement. Worker reservations, retained metrics, field
staging and cleanup overlap must all fit the declared envelope. Reporting and cleanup run after failure or cancellation too.

The runner records source/input identities, task outcomes and selections. Report measured CPU use separately from allocation and
elapsed time, include failed/cancelled work in campaign accounting, and state whether any live report-job snapshot is partial.
Allocation does not establish actual peak CPU utilization.

The [CPU plotting example](../../../../examples/sum159/plot_cpu_utilization.py) reads saved task accounting. Its scheduler-adjusted replay
preserves dependencies, task durations and long tails under the original CPU cap while removing scheduler waiting. Busy CPU is estimated
from task CPU time divided by elapsed time, not instantaneous sampling. Complete accounting can describe a scientifically stopped run;
never represent cancelled, unrun stages as completed work.

Show full-field count and spatial diagnostics, accompanying-data behavior, matched saved observations/native fields and important
limitations. Display crops are presentation choices; all fitted statistics retain their full-field geometry. Keep combined scores
traceable to the actual parameters and mixtures evaluated. For this pilot's retained composition-recheck limitation and displayed
candidates, use the example's account rather than silently adding a new validation/refitting cycle.
