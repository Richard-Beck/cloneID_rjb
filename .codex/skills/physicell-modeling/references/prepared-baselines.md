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

Read [the example](../../../../examples/sum159/README.md) for completed pilot results, the first fresh attempt and local-path configuration.
That attempt completed lineage fitting and stopped before perspective fitting because its competitive-parent prerequisite was unmet.
Synthetic/static coverage and partial scientific execution do not establish successful end-to-end calibration.

## SUM-159 model and observations

The lineage model first fits a shared biological vector, then founder-specific vectors coupled by ridge. Biology is constant across
arms/passages within a founder in this pilot; the recorded oxygen history drives the specified oxygen response. The perspective model
shares biology by current 2N/4N genomic state across founders and treatments. Its pre-existing mixtures change through differential
division and survival, with zero state transitions. Density and cluster initialization are shared.

Initialize perspective candidates from competitive simulator-ranked shared lineage parents produced by the **same new run**. The
founder-ridge vector is not the parent: founder-specific density/cluster parameters do not embed in the perspective parameterization.
Check the shared physical embedding explicitly; stochastic native realizations need not have identical scores.

This pilot adapter requires at least two valid shared parents within 20% of the best native microscopy loss. It stops the perspective
branch when that prerequisite is unmet. Preserve the failed attempt and its costs; changing the cutoff, adding fits or reusing historical
vectors changes the planned campaign and needs the user's direction.

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

1. Fit 16 fresh shared lineage starts. Evaluate their final vectors with two native seeds and rank the supported results. Fit 12
   founder-ridge starts at each alpha in 0, 1, 10, 100 and 1000 from those new parents; evaluate final vectors and retain shared anchors.
2. Generate 1,000 perspective exploratory starts from this run's competitive shared parents, across four configured regularization
   strengths. Check the shared embedding and retain the permanent shared anchors.
3. Screen 40 candidates: five best objective values plus five maximin parameter-diverse choices per alpha. Diversity choices come from
   the best 60% of valid candidates, with a pool floor of 30 and cap of 100, using normalized/transformed parameter distances. The two
   shared anchors replace the final diversity slots in the first two alpha buckets.
4. Evaluate 24 selected passages with two native seeds plus same-oxygen minority probes at 1%, 5%, 95% and 99%. Record failures and
   calculate native diagnostics. Apply at most 100 seconds of local refinement to non-anchor candidates with complete native support,
   matching source/correction vectors and finite native microscopy bias. Anchors and incomplete/invalid sources receive explicit outcomes.
5. Rank supported original/refined options by corrected approximation microscopy + native-screen bias + corrected assay deviance +
   ridge penalty, retaining the best option per source. Take the best two distinct sources. Choose the third by maximin parameter
   diversity among the remaining top 12 sources within `best + max(1, 0.2 * abs(best))`; fall back to the next supported source if that
   pool is empty. Freeze the three vectors and independently evaluate all 118 passages with four seeds plus minority probes.
6. Report the saved validation evidence and **accept the fit for now**. Validation does not trigger another correction, refit or native
   batch. Missing tasks remain visible rather than being treated as zero loss.

The executed procedure ends here. Co-located exploratory serial/alternating scripts from the pilot directory were not executed phases
of this protocol; do not infer additional required phases from their presence.

[terminal.py](../scripts/baselines/terminal.py) implements screen eligibility, transformed distances, deterministic ties, refinement
eligibility and finalist selection; the configuration supplies their numerical settings. These rules determine the followup batches
without another discretionary selection step.

## Execution and reporting

Inspect the concrete dry-run dependency plan and agree a resource envelope before scientific submission. Synthetic checks and a saved
plan are useful preparation, not authorization to launch. Use SLURM for substantial work, honor the agreed campaign CPU cap and retain
completed results on failure. Resume only the requested missing work rather than silently expanding the campaign.

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
