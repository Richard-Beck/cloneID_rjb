# Baseline workflow

The baseline is a fitted mechanistic account against which a biological hypothesis can be expressed as a model change, refitted and
compared. Two definitions are supported: lineage-determined identity follows recorded lineage relationships; perspective-guided
identity follows states defined by investigator-chosen accompanying measurements. SUM-159 progressive hypoxia is the pilot example.

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
The perspective search starts from competitive shared lineage fits produced by that same new run. Historical fitted vectors,
optimizer checkpoints and rankings are excluded from this fresh fitting boundary.

The perspective procedure uses a fixed quality/diversity/anchor screen, native screening with minority probes, bounded local
refinement, then independent validation of three finalists. The selection rules are documented in the modelling reference and encoded
in the runner. After validation, report the diagnostics and accept the fit for now; the procedure does not automatically add another
correction/refit/validation cycle.

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

The reusable fresh-fit runner is implemented and checked with synthetic inputs. The complete fresh scientific rerun has not started;
its fit quality and end-to-end resource use remain to be demonstrated. That rerun can follow this checkpoint under an agreed resource
envelope. Testing the workflow on an alternative lineage is subsequent work.
