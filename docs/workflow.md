# Baseline workflow

The baseline is a fitted mechanistic account against which a biological hypothesis can be expressed as a model change, refitted and
compared. Two definitions are supported: lineage-determined identity follows recorded lineage relationships; perspective-guided
identity follows states defined by investigator-chosen accompanying measurements. SUM-159 progressive hypoxia is the pilot example.

## Resource envelope

Read `AGENTS.md` and the current user constraints first. This project allows 50 GB durable storage, a transient peak of 100 GB with
cleanup afterwards, and defaults to up to 1,000 cores for one hour. Count project-created data on home, shared and node-local storage,
including duplicate copies. For a project without explicit rules, state assumptions of a 20 GB total disk cap and 32 cores for two
hours. Plan output retention and cleanup with the compute work; keep compact metrics and selected report fields instead of every raw
simulation. Limits must leave enough capacity to report partial results and clean up.

## Prepare the evidence

1. Use [cloneid-database-data](../.codex/skills/cloneid-database-data/SKILL.md) to validate a local cloneID snapshot and reconstruct the
   relevant ancestry, culture episodes, media and sampling histories. Keep database inputs under `core_data/` and derived products under
   `data/`.
2. Use [ingest-lab-records](../.codex/skills/ingest-lab-records/SKILL.md) to connect those histories to notebook evidence and reconstruct
   experimental instances, protocols and exceptions. The live database is `lab_records/instance_protocol_db/`; update it serially and
   validate each bounded update.
3. Prepare the observation table, episode/lineage specification and accompanying assays with explicit units, time matching and source
   provenance. For imaging, use only CellSegmentations and verify image/mask/feature joins. See [setup](skills.md) and
   [imaging guidance](imaging-data.md).

These are prerequisites to fitting. Once their prepared products are accepted, a fresh fit can start from them; it need not repeat raw
database, notebook or microscopy reconstruction.

## Fit from prepared data

Use [physicell-modeling](../.codex/skills/physicell-modeling/SKILL.md) and its
[prepared-baseline procedure](../.codex/skills/physicell-modeling/references/prepared-baselines.md). Freeze the prepared data, model,
observation mapping, candidate-selection rules and resource envelope for the run. The approximation proposes parameters; PhysiCell
evaluates the resulting fields and supplies native diagnostics.

The [SUM-159 configuration](../examples/sum159/baseline.json) scripts fresh shared lineage fits followed by founder-specific ridge fits.
The perspective search prefers competitive shared lineage fits produced by that same new run. Parent scarcity falls back to other
valid current-run fits, with the evidence basis recorded; it does not terminate the campaign. Historical fitted vectors,
optimizer checkpoints and rankings are excluded from this fresh fitting boundary.

The perspective procedure uses a fixed quality/diversity/anchor screen, native screening with minority probes, bounded local
refinement, then independent validation of three finalists. The selection rules are documented in the modelling reference and encoded
in the runner. After validation, report the diagnostics and accept the fit for now; the procedure does not automatically add another
correction/refit/validation cycle. A poor fit or scarce candidate pool is a reportable outcome. Continue with fewer valid candidates or
explicitly labelled partial evidence when necessary; keep identity, input-integrity and physical-mapping checks strict. Missing cost
components never count as zero loss, and partial scores do not compete directly with fully supported scores.

## Report and retain

Report the fitted behavior, count/spatial cost components, accompanying-data fit, missing simulations and compute use. Distinguish
measured CPU use, allocated CPU-hours and elapsed time, and state the campaign scope included in each total. Match displayed microscopy
and model fields to the correct acquisition; presentation crops do not replace full-field fitted statistics.

Track reusable code, configuration and selected public figures/text in Git. Keep raw snapshots, detailed measurements and manifests,
the live lab-record database, full run outputs and private provenance outside Git. Encrypted snapshots can distribute local prerequisites;
see [publishing](publishing.md). A figure builder requiring local data is reproducible when those prerequisites are restored, rather than
from a source checkout alone.

## This checkpoint

Both named [SUM-159 pilots](../examples/sum159/README.md) are complete. Their selected results appear in the
[current figure](u01_calibration_draft/latest/baseline_multipanel.png) and
[calibration text](u01_calibration_draft/latest/calibration.md).

The reusable fresh-fit runner has synthetic checks and a recorded scientific attempt from prepared data. That attempt completed
lineage fitting and stopped because an initialization rule required two competitive shared parents. The selected lineage fit was
weaker than the accepted pilot. The revised runner removes that quality gate and widens the search to 512 shared starts, 500
founder-specific starts, 1,000 perspective starts and eight bounded refinement starts per eligible source, under one 1,000-CPU cap.
Replacement run `20261017_152845_sum159_baseline_scratch` passed preflight and completed all 1,012 lineage fits, then was canceled
after storage exhaustion during ridge simulation evaluation. It used 203.0114 CPU-hours including storage recovery and preflight.
Compact records and selected figure evidence remain; bulk outputs and the shared-storage copy are being reclaimed. A fresh bounded
storage workflow is being prepared within the 50 GB durable / 100 GB transient limit and one-hour compute window. The first attempt's full
outputs were erased at the user's request; its published summary remains historical evidence. Complete fresh-workflow fit quality remains to be demonstrated; the [example](../examples/sum159/README.md) records the stopped attempt and its resource use.
Testing on an alternative lineage remains subsequent work.
