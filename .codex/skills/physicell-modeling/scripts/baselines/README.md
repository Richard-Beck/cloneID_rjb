# Prepared-data baseline runner

This package fits the lineage-determined and perspective-guided SUM-159 pilot baselines from prepared measurements. It retains the
30-column total/dead observer, six loss components, shared-to-state parameter mapping and zero state transitions from the accepted
180145/concluded 190611 development pilots. Those pilots supply source, never fitted vectors or runtime dependencies.

Use the repository entry point `scripts/run_baselines.py`. Paths in JSON configuration resolve relative to that JSON file; explicit
`BASELINES_PREPARED_DATA`, `BASELINES_OUTPUT_ROOT`, `BASELINES_SCRATCH_ROOT`, `BASELINES_LINEAGE_ENGINE`, and
`BASELINES_PERSPECTIVE_ENGINE` environment variables override their corresponding paths. Python defaults to the current interpreter.
The public `examples/sum159/baseline.json` keeps execution disabled. Bare help and synthetic checks need no private data or engines.

```bash
python scripts/run_baselines.py --help
python scripts/run_baselines.py mock --config examples/sum159/baseline.json --output tmp/baselines/mock
python scripts/run_baselines.py preflight --config LOCAL_CONFIG.json --output tmp/baselines/preflight
python scripts/run_baselines.py dry-run --config LOCAL_CONFIG.json --output tmp/baselines/planning
```

Preparation, dry runs and mocks do not fit, simulate or contact SLURM. Scientific workers require explicit execution authorization,
matching frozen source/config/input identities and a SLURM allocation. `prepare`, `scheduler-plan`, then `submit` freeze inputs and
materialize the held dependency campaign; existing runs and attempts cannot be overwritten or automatically resubmitted.

## Restart breadth and scheduling

The revised pilot configuration requests 512 fresh shared starts and 500 founder-ridge starts (100 at each configured alpha), 240 seconds
per optimizer; 1,000 perspective starts retain 300 seconds each. Fit/finalization/native/candidate-score tasks stream through one
1,000-CPU envelope. Scoring and parent embedding run independently per candidate. Native slots at 0% oxygen are scheduled first across
ready candidates because measured aggregate runtimes were substantially longer there; seeds, physical slots and dependencies are
unchanged. Small preparation/reduction/report tasks retain one CPU.

Up to 40 candidates receive 24-passage/two-seed native screening plus minority probes. Each eligible non-anchor source has eight
independent 100-second local refinements inside the same source-anchored bounds and frozen native correction. Replica 0 retains the
original search path; other replicas use deterministic bounded starts. Finalists remain distinct by original source. Up to three
vectors receive independent 118-passage/four-seed native validation plus probes. This fixed procedure ends with a saved-evidence report
and accept-for-now when a valid terminal vector exists; it triggers no extra correction, refit or validation batch.

Measured-duration replay estimates roughly 378 lineage CPU-hours and approximately 510–515 CPU-hours including perspective/refinement.
Estimated queue-free elapsed is roughly 68–85 minutes, with native I/O sensitivity and unsuccessful attempts included as uncertainty.
These are planning estimates, not hard CPU-hour/elapsed caps. Native output is expected to require about 300 GB for lineage plus
perspective outputs. Check actual filesystem space, quota/inodes, scheduler limits and environments before execution. Preserve native
XML/MAT snapshots for matched field reporting. Every task retains wall/CPU/outcome accounting; measured and allocated time differ.

## Scarcity and incomplete evidence

Competition/diversity rules guide selection; they do not require two parents, 40 screen candidates or three finalists. Full native
support is preferred. Partial native objectives retain actual finite measurements and report support masks, normalized retained
weights and missing components separately from the full objective. Different partial masks are not ranked as directly comparable
full losses: evidence mass/coverage and deterministic support groups precede within-group cost. Valid same-run approximation results
can initialize/rank when native evidence is unavailable, explicitly labeled. A fresh current-run design point is the final initialization
fallback and must pass an actual model evaluation. No historical fitted parameters are used.

One valid parent can seed all starts; valid outside-window parents can supply diversity. Scarce/empty stages freeze honest manifests
and continue to useful later work. Unused reserved slots are canceled before running and recorded as unused quota, not successful
simulations. Failed engines/timeouts retain exact available snapshots; unobserved requested times stay missing. Valid interrupted
checkpoints can be finalized without reevaluation. Refinement skips unavailable corrections and preserves source vectors when local
search fails. Integrity, bounds, foreign-source hashes and genuinely invalid/nonfinite models remain errors or unavailable evidence.

No aggregate native-stage clock runs while tasks wait in the queue. Individual native timeouts remain 900 seconds for lineage and
480 seconds for perspective; outer native jobs allow 45 minutes for observation processing. Reports distinguish accepted available fits,
search-quota shortfalls, partial/unavailable validation, scientific validity and worker completion. They never infer full scientific
completion from score-file existence or scheduler success.

## External engines

Use separate external **PhysiCell 1.14.2** checkouts/builds. Preserve each checkout's `core/`, `modules/`, `BioFVM/`, Makefile and license.
For lineage install `vendor/assets/physicell/baseline_runtime.cpp` as `main.cpp`. For perspective install
`assets/perspective/physicell/main.cpp` and adjacent `wgd_runtime.h` at the checkout root. Build each with:

```bash
make -j 4 PhysiCell_custom_module_OBJECTS=
```

The empty override avoids duplicate custom-module symbols. Supply the two resulting executable paths explicitly. Canonical XML
sources are `vendor/assets/physicell/PhysiCell_settings.xml` and `assets/perspective/physicell/PhysiCell_settings.xml`. Runtime exporters
write fitted XML, cell rules, initial cells, sampling times and output locally. Stock PhysiCell and the older generic 29-column observer
are different models. Exact source/assets and external binary identities are frozen separately.

`source_origins.json` maps development sources without experimental paths. `source_manifest.json` contains public source hashes only.
No prepared data, binaries, detailed private provenance or old run snapshots belong in this package. Synthetic fixtures are generated
under temporary scratch directories. Native support/timeout/refinement tests are in `vendor/native_support_mock.py`; they use fakes,
never the scientific models or external engines. The complete mock suite checks scheduler and terminal failure paths without processes.
