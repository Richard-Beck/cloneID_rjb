---
name: cloneid-database-data
description: >-
  Query, validate, rebuild and interpret cloneID passaging metadata, lineage graphs, culture episodes, coherent same-media spans,
  graph distances, media conditions and LiquidNitrogen records; refresh raw database snapshots when requested.
---

# cloneID Database Data

Work from the repository root. Raw snapshots under `core_data/` and regenerated outputs under `data/` are local state, excluded from Git.
Use bundled scripts for deterministic graph and span operations and read the shared reference before interpreting fields or QC flags.
Database refresh is opt-in; never run it merely because inputs may be stale.

## Current research direction

Follow `AGENTS.md`. New user-specified hypotheses start from `dev/physicell_baseline/workflow.md` and explicitly extend its concrete model
and counterfactual. Prior hypothesis workflows, automatic model-selection requirements and planning deliverables are deprecated, including
those retained in this skill's historical references. Database preparation supports the chosen model; it does not prescribe a hypothesis
workflow. Use the repo-local `physicell-modeling` skill for requested simulator calibration and reporting.

Imaging and segmentation evidence comes only from **CellSegmentations**, including all subdirectories and per-cell feature outputs.
Resolve the root from `CELLSEGMENTATIONS_ROOT` or an explicitly supplied path. On RED it is `/share/lab_crd/CellSegmentations`; on the
workstation use its local mount. Preserve relative paths and do not silently fall back to other image collections.

## Workflows

Read only resources relevant to the current task:

- [Rebuild cleaned metadata](workflows/rebuild-cleaned-metadata.md): regenerate row-level and episode-level graph outputs.
- [Analyze coherent spans](workflows/analyze-coherent-spans.md): summarize connected same-media spans and optional distances.
- [Refresh core database snapshot](workflows/refresh-core-data.md): after a specific request, stage Passaging, Media, Perspective and
  LiquidNitrogen exports with archived baselines and diffs. Promotion is a separate requested action.

## References

- [Cleaned metadata reference](references/cleaned-metadata-reference.md): canonical files, graph semantics, fields, QC and query routing.
- [Core input fields](references/core-data-fields.md): raw table schemas and meanings.

Existing canonical evidence may be reused through `data/` when suitable for the user's question. Keep hypothesis-specific audits, reports,
figures and interpretation in the current hypothesis-test folder. Never recover inputs from an old hypothesis-test run.
