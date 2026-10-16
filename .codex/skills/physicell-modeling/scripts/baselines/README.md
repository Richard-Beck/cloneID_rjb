# Prepared-data SUM-159 baseline pilot

This source package promotes the scripted setup derived from the accepted `20261016_180145` lineage pilot and concluded
`20261016_190611` perspective pilot. It preserves their model-specific numerical, scoring and selection implementation. It has
not been scientifically rerun after promotion and is not a universal adapter for other cell lines or prepared-data schemas.

The repository entry point is `python scripts/run_baselines.py`; its default is a dry run. The example is
`examples/sum159/baseline.json`. `--help` uses only the standard library. The current Python runs the CLI; `paths.python: null`
means that interpreter, while an explicit value selects the executable written into future scheduler commands. No installation
or environment is selected silently. Synthetic checks require the existing numpy/scipy/pandas/numba/scikit-image/matplotlib
dependencies but require no private data, compiled engine or PhysiCell checkout.

```bash
python scripts/run_baselines.py --help
python scripts/run_baselines.py dry-run --config examples/sum159/baseline.json
python scripts/run_baselines.py mock --config examples/sum159/baseline.json
```

Missing local prerequisites are reported explicitly. In the public example, scientific execution is disabled. `dry-run`,
`preflight`, `prepare`, `scheduler-plan`, `report`, `accounting` and `mock` never submit jobs. The explicit future `submit`
command requires `execution.authorized: true`, usable local prerequisites and verified scheduler limits. Scientific workers
require SLURM. There is no separate environment-token or repeated scientific approval flow. No launch is authorized now.

All relative `paths` values, including environment overrides, resolve from the selected configuration file's directory.
`~` is expanded; other variables embedded in path strings are not expanded. Environment overrides are
`BASELINES_PREPARED_DATA`, `BASELINES_OUTPUT_ROOT`, `BASELINES_SCRATCH_ROOT`, `BASELINES_LINEAGE_ENGINE` and
`BASELINES_PERSPECTIVE_ENGINE`. `CELLSEGMENTATIONS_ROOT` applies only to an explicitly supplied optional imaging manifest.
The example's scratch root is repository-local `tmp/baselines/`, with runs below it. Runtime output must remain under that
configured scratch root and outside this source package. `--output` is an explicit CLI output path relative to the current
directory, and must also be under the configured scratch root. Per-run configuration, inputs and external dependency hashes
are frozen locally; later workers use that frozen configuration. Private inputs and binaries are never stored in this package.

The prepared-data interface requires `observations.csv`, `observations.npz`, `field_measurements.csv`, `metadata.json`,
`episodes.json`, `assays.json`, `lineage_edges.csv`, `schedule_all.csv` and `excluded_schedule.csv`. Example fingerprints identify
the vetted pilot prerequisites; supply those locally or deliberately update a local configuration for a validated replacement.
The NPZ arrays are `observed` and `scales` of shape n x30 and `weights` of shape n x6. Columns 0/1 are log1p(total retained/dead)
counts; remaining columns are coverage, logged gap, Clark-Evans and25 pooled log relative-area quantiles. Component weights are
0.5 total plus0.1 each for dead, coverage, relative area, gap and Clark-Evans. Episode/founder weighting and exact row/time/ancestry
joins are checked. Frozen classified measurements are data reuse, not parameter reuse. Raw reconstruction is outside this boundary;
any future image/mask/features work must use CellSegmentations and verified joins, without historical-root fallbacks.

Fresh deterministic lineage fits precede simulator ranking and ridge initialization. Perspective starts use only that new run's
competitive, numerically valid shared parents; two state13 blocks share one density/cluster initialization. The confirmed terminal
procedure is top5 objective +5 diverse per alpha with two permanent shared anchors, a24-passage/two-seed native screen plus minority
probes, eligible bounded refinement, two best supported distinct sources plus a competitive diverse third, then independent all118
passages/four-seed validation plus probes. These counts are visible configuration. Reporting accepts the fit for now after the planned
validation, retaining missing/failed evidence. Diagnostics do not trigger another correction, refit or native batch; no quality
acceptance threshold is added. The co-located serial/alternating diagnostics from other work are not this campaign's procedure.

The complete18-node held-job scheduler plan keeps each candidate's fit -> finalization -> native dependencies, failure salvage,
stage ranking, global CPU cap and final reporting. Default pilot settings reserve9,701 task slots, including2,176 lineage and6,280
perspective native trajectories; these are plans, not runs or newly approved resource budgets. Relative native-stage deadlines start
when each stage manifest is prepared, including subsequent queue waiting. Official future accounting maps jobs through frozen task
tables and separates measured CPU, allocated CPU, elapsed, queue and dependency time. Current-report snapshots are labeled partial.

## External engine prerequisites

The model-specific source assets target **PhysiCell 1.14.2**. Maintain separate isolated external checkouts/builds for the two engines.
Preserve each checkout's `core/`, `modules/`, `BioFVM/`, Makefile and license. For lineage, install
`vendor/assets/physicell/baseline_runtime.cpp` as that checkout's `main.cpp`. For perspective, install
`assets/perspective/physicell/main.cpp` and its adjacent `wgd_runtime.h` at the checkout root. In each checkout, the documented build
command is `make -j4 PhysiCell_custom_module_OBJECTS=`; the empty override avoids duplicate custom-module symbols. Keep the resulting
executables outside this package, and supply their distinct paths through config/environment. No engine is built or executed by setup.

The canonical XML templates are `vendor/assets/physicell/PhysiCell_settings.xml` for lineage and
`assets/perspective/physicell/PhysiCell_settings.xml` for perspective. Runtime exporters use these templates and generate each case's fitted XML, `cell_rules.csv`, initial-cell CSV, sample-time file and `output/` locally.
Run-time commands invoke the configured engine with `PhysiCell_settings.xml` in that case directory. Stock PhysiCell, or the maintained
skill's older generic29-column observer/engine, is not a replacement for these retained-total/dead model sources. Exact source bytes
and fingerprints are recorded in `source_manifest.json`; external compiled binary identities are frozen per run.

Compute-node Python/library compatibility, actual scheduler array/job limits, native transfer and the numerical shared microscopy
embedding remain execution-time checks. No scientific model, engine, scheduler probe or real job was invoked to validate this promotion.
Known assay timing proxies and the restricted shared-parent embedding remain scientific limitations from the pilots.

The test suite generates invented fixtures at runtime under the configured scratch directory, including an intentionally synthetic
118-episode/343-row support shape. It does not read laboratory measurements. `source_manifest.json` contains source hashes only;
`source_origins.json` gives a concise development mapping without historical runtime paths or experimental manifests.
