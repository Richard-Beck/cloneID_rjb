# Prepared-data baseline runner

This source implements fresh lineage-determined and perspective-guided SUM-159 pilot fits from prepared data. It preserves the
30-column total/dead observer, six weighted objective components, shared-to-state mapping and zero state transitions from the accepted
180145/concluded190611 pilots. Those pilots supply development source, never runtime parameters or fitted vectors. This is a prepared-data
pilot adapter; database reconstruction and segmentation are prerequisites.

Use `scripts/run_baselines.py`. JSON paths resolve relative to their JSON file. `BASELINES_PREPARED_DATA`, `BASELINES_OUTPUT_ROOT`,
`BASELINES_SCRATCH_ROOT`, `BASELINES_LINEAGE_ENGINE` and `BASELINES_PERSPECTIVE_ENGINE` override configured paths. Python uses the current
interpreter unless explicitly configured. `examples/sum159/baseline.json` disables execution. Help and synthetic validation need no private
inputs or engines.

```bash
python scripts/run_baselines.py --help
python scripts/run_baselines.py mock --config examples/sum159/baseline.json --output tmp/baselines/mock
python scripts/run_baselines.py dry-run --config LOCAL_CONFIG.json --output tmp/baselines/planning
python scripts/run_baselines.py prepare --config LOCAL_CONFIG.json --run-name NEW_RUN
python scripts/run_baselines.py scheduler-plan --config LOCAL_CONFIG.json --run NEW_RUN_PATH --output PLANNING_PATH
```

Preparation/dry runs never fit, simulate or contact SLURM. Future `submit` creates all jobs held, configures dependencies, then releases
them. Existing runs/attempts cannot be overwritten or automatically resubmitted. Local execution requires a complete project-owned
storage inventory, the bounded-protocol engine pair, matching frozen hashes and the authorized cleanup/review handoff.

## Resource and storage contract

Project limits are decimal 50e9 durable bytes and 100e9 total peak bytes across all project-created home, shared and node-local artifacts,
including copies and caches. Moving data behind a symlink does not exclude it. Declare every ownership root in
`storage.project_scope_roots`; only explicitly declared pre-existing read-only input/environment roots may be excluded. Preflight walks
resolved targets, deduplicates hard links, counts independent copies separately and refuses undeclared external targets. Filesystem-wide
free space does not establish a user quota. A new run requires actual inventory plus its full durable reservation below 50e9. An explicit `storage.inventory_file` can reuse a
post-cleanup snapshot for at most 600 seconds during prepare/submit; `inventory_sha256` binds its exact bytes and ownership roots.
Without that local option preflight inventories directly. The launch handoff must exclude unrelated new storage-producing work.

The example reserves 36e9 durable growth: 22e9 compact native records, 1e9 selected field frames, 5e9 bounded fit records/traces,
2e9 report, 50e6 cache/overhead and 5.9e9 metadata and physical allocation overhead. The closed native case count is 14,984; the five capped compact files plus one
65,536-byte log total at most 1,376,256 bytes/case, or 20,621,819,904 bytes. All 2,104 fit/refinement attempts have a 2e6-byte
envelope. An additional 623,120,256-byte allowance covers up to 999 interrupted compact atomic overlaps within the same 22e9 reservation.
Configuration validation recomputes these bounds when counts change. The actual measured project footprint must leave
36e9 bytes of durable headroom before launch, so existing project allocation must be at most 14e9 bytes. The planning estimate is
12e9 existing bytes; the actual post-cleanup inventory controls admission.

The filesystem charges approximately 24–32 KiB per file beyond logical payload and 32 KiB per directory. The extra 4e9-byte allowance
covers those physical charges for compact cases, fitted records, dispatch/worker accounting and combined scheduler logs. For scale,
89,904 compact files can add 2.946e9 bytes at 32 KiB/file, 14,984 case directories add 0.491e9, and 56,565 dispatch/accounting/log files add
1.390–1.854e9 before their small contents. Existing category buffers cover part of this overhead; the metadata/allocation allowance
covers the remainder. Inventory counts allocated blocks for files, directories and symlinks, including targets on other owned volumes.

Candidate fields awaiting ranking are temporary, with a separate 16e9-byte staging reservation. At most 1,932 recognized fields of
8,000,064 bytes total 15,456,123,648 bytes; selected winners remain within the 1e9 durable field allowance and losing fields are deleted.
Moving a frame into this pool does not create a second payload copy. The final retention manifest and janitor close this lifecycle on
success, timeout or cancellation. No temporary candidate field is silently classified as durable output or excluded from peak use.

At most 999 native cases reserve 32e6 transient bytes each. Even at the full 50e9 durable ceiling, the aggregate bound is
50e9 + 999*32e6 + 16e9 = 97.968e9 bytes, below 100e9. Each case reserves two 8,000,064-byte frames for atomic overlap, 8e6 initial
inputs, 1e6 logs, 1e6 numeric state trajectory and 2e6 other overhead, including the active compact-file atomic overlap. Initial CSV bytes
are checked before writing. Case inodes are bounded at 32; durable artifacts reserve 400,000 inodes. Workers create cases only under
the current run's `transient/`, acquire a reservation before export and release it after cleanup and verified wrapper completion. A wrapper exception keeps its reservation until the janitor,
so unfinished compact overlaps cannot accumulate outside the reserved count. These are finite ceilings rather than
preallocated files; all project-created copies and cached bytes remain counted.

Native slot reservations use a small `storage/state.json`; full inventory and field provenance live in `storage/inventory.json` and
`storage/assets.json`. All readers and writers use the same reservation lock, including startup reads on shared filesystems. Detailed
audits should use `storage_budget.ledger_snapshot(run)` to read the full, hash-checked view. This layout preserves the storage limits and
failed-case reservations while avoiding full provenance rewrites for every native case. Initialize a fresh run; active ledgers cannot be
converted in place.

Both engines implement an output-only frame/acknowledgement protocol. A frame contains the actual sample time and full precision x,y,
total_volume,dead,cell_type columns for at most the existing 200,000-cell guard:64+200000×5×8=8,000,064 bytes. The engine cannot advance to
another snapshot until the current frame is measured, removed or moved into its reserved durable field asset, then acknowledged. The
same observer array helper serves legacy XML/MAT and compact frames. No XML/MAT fallback is allowed in this profile. Numerical update
loops, RNG calls, mechanics, cell-cycle/death rules and objective calculations remain unchanged.

Exploratory cases keep compact observations, support, numeric state trajectory, exact source/seed/time hashes and bounded logs. They
delete bulky output immediately after measurement, including failure and SIGTERM paths. Immutable compact progress supports recovery
without another model call after hard interruption. A dependent janitor runs after all campaign allocations terminate, removes stale
cases/caches, harvests saved evidence if the controller/report failed, and prunes losing field assets. It never deletes output while a
worker can still own it. Persistent Numba disk caching is disabled; compilation stays in process memory. Python/native core dumps are
disabled. Diagnostic trial traces are bounded, with total/retained/omitted counts and a hash of every attempted record; fit decisions and
best checkpoints are unaffected.

Full precision compact fields for recognized rows 175, 57, 342, 234, replicate 0, are retained within the field budget until ranking. The final
retention manifest preserves selected fits, regularization-path winners and required fields; losers are pruned after hash checks. Geometry,
seed, source, observation row and coordinate metadata support full-field statistics and 25% crops. Retaining a partial field is never
represented as a complete native trajectory.

## Campaign and time window

The example fits 512 shared starts and 500 ridge starts (100/alpha), 240 seconds each, with deterministic fresh seeds. It freezes native pools
from those new saved fits:256 shared sources and 40 ridge sources per alpha (200 total), half best objective and half maximin parameter
diversity. This is an explicit finite native allocation. Unselected fits retain their approximation results and unvalidated status.
Selected native trajectories are4,096 shared and 6,400 ridge. Fresh shared native ranking supplies both ridge parents and perspective
initialization from this same run. No previous run's fitted vectors/rankings/checkpoints are read.

The perspective phase has 996 starts (249/alpha), 300 seconds each, fitting one 999-worker wave while one CPU runs the budget controller.
Up to 24 sources receive 24-passage/two-seed native screening plus minority probes; configurable best/diverse selection retains permanent
anchors. Eligible non-anchor sources have four independent 100-second refinements within the same source-anchored bounds and frozen
native correction. Up to three distinct-source finalists receive all 118 passages/four seeds plus probes. No adaptive correction/refit or
additional native batch follows validation.

The execution window is 3,600 seconds, with scientific admission ending at 3,300 seconds and 300 seconds reserved for saved-evidence reporting.
The clock starts on the allocated budget-start worker; later dependency/queue delays remain visible. Per-case native caps are 420 seconds
lineage and 360 seconds perspective. Remaining global time clips every new fitting/native allowance. At expiry, the controller stops only
this campaign's jobs, preserves actual partial outcomes, harvests valid current-run checkpoints and reports. If scheduler teardown lags,
reservations remain active and the dependent janitor reports after stable termination. External queue availability can delay report
arrival; it never authorizes another scientific allowance. Cleanup-only work and all failures remain in accounting.

Optimizer allowance alone is 150.47 CPU-hours, plus 2.67 CPU-hours refinement. Total planning estimate is310–370 CPU-hours and approximately 50–55 minutes
without queue delays, based on measured tails with bounded streaming/cleanup. The zero-oxygen cohorts contain 512 shared and 800 ridge
trajectories, each within one 999-worker wave; shorter oxygen cases can fill the remaining capacity. These forecasts do not guarantee
completion: queue delay, heavy tails or cleanup overhead may produce a partial saved-evidence report at the same fixed deadline. These are estimates; the 1,000 CPU-hour ceiling and one-hour
window are limits. Native/fit/finalization/candidate-score tasks retain individual CPU/wall/outcome sidecars. Official SLURM Submit,
Eligible,Start,End,AllocCPUS,ElapsedRaw,TotalCPU and exit state distinguish allocation, actual CPU, queue/dependency delay and failures.
The controller uses one CPU and workers at most 999; the afterany janitor starts only after all other allocations end.

## Evidence and manifest interfaces

`lineage_<stage>_fit` manifests map full fresh candidate indices: fit i, finalizer N+i, dependent on its own fit.
`lineage/<stage>_native_candidates.json` freezes pool_index,candidate_index,candidate_id,alpha,final_sha256 and selection basis.
`lineage_<stage>_native` manifests use the pool index and explicit global `indices`/local `trajectory_indices`; score groups wait for all
own native indices. Dispatcher records additionally retain original fit index/id, parent finalizer job/index, pool hash and final hash.
The selected pool, original candidate manifest and final vectors are checked again before execution.

`budget/clock.json` stores the window; `budget/actions.json` records administrative commands, UTC and return status;
`budget/controller_outcome.json` distinguishes normal completion, harvest and cleanup pending. `budget_terminal.json` freezes best
available saved fits/support if validation is incomplete. Normal finalists remain unchanged. `budget_terminal/retention_manifest.json`
and pruning outcome identify exact kept/deleted compact field assets. `budget/janitor_outcome.json` marks final cleanup. Collect final
accounting after the janitor exits, including its cost and controller cost; worker completion is separate from scientific support.

Scarce/invalid pools, one parent, unavailable corrections, partial native cases and checkpoint recovery remain explicit evidence tiers.
Full native scores precede partial scores; different missing-support patterns are not directly compared as full objectives. Missing
observations are unavailable, never zero loss. Genuine input/source/bounds integrity failures remain errors. The terminal report accepts
an available fit for now while describing incomplete validation; it does not claim a complete baseline from file existence.

## Rebuilding external engines

Use separate external **PhysiCell 1.14.2** checkouts, preserving core/modules/BioFVM, Makefile and license. For lineage install
`vendor/assets/physicell/baseline_runtime.cpp` as main.cpp. For perspective install `assets/perspective/physicell/main.cpp` and
`wgd_runtime.h`, and apply `assets/perspective/physicell/PhysiCell_phenotype.cpp.patch` to the stock core. The exact retained M-exit
interception hook is required; `core_patch_origin.json` records stock/patched/patch source hashes. BOTH builds require
`assets/native_frame_protocol.h` beside main.cpp. Build each with:

```bash
make -j4 PhysiCell_custom_module_OBJECTS=
```

The empty override avoids duplicate custom-module symbols. Supply the resulting separate binaries explicitly. Canonical XML assets are
`vendor/assets/physicell/PhysiCell_settings.xml` and `assets/perspective/physicell/PhysiCell_settings.xml`. Engine
`--cloneid-frame-protocol` must declare the exact protocol/version/field count/bounds; unsupported old binaries fail before a simulation.
Before launch, bounded matched-initial-input/seed original-vs-new checks must verify full cell columns, 30 observables and state CSV,
including division/death events and timeout/cancel cleanup. This is a required transfer check, not a refit or quality threshold.

`source_origins.json` and `source_manifest.json` contain public source identities only. Prepared data, binaries, detailed experimental
provenance, run manifests and validation artifacts stay local. Synthetic fixtures use temporary directories and are removed after checks.
