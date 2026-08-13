---
name: cloneid-database-data
description: >-
  Use when rebuilding, querying, or interpreting cloneID passaging metadata, lineage graphs, culture episodes, coherent same-media spans,
  graph distances, media and protocol conditions, Perspective assay anchors, refreshing raw database snapshots, cleaned cloneID CSV outputs,
  or episode and lineage growth models.
---

# cloneID Database Data

Work from the repository root. Use the bundled scripts for deterministic graph and span operations. Read the shared reference before
interpreting fields or QC flags.

Raw snapshots under `core_data/` and regenerated outputs under `data/` are local state and are intentionally excluded from Git.

Do not read or execute all workflows by default. Use the descriptions below to determine which files are relevant to your assigned task.
Database refresh is opt-in: never run it merely because canonical inputs may be stale.

## Workflows

- name: Rebuild cleaned metadata
  description: Regenerate the canonical row-level and episode-level metadata graph outputs.
  path: [workflows/rebuild-cleaned-metadata.md](workflows/rebuild-cleaned-metadata.md)

- name: Analyze coherent spans
  description: Summarize connected same-media episode spans and optionally compute distances between them.
  path: [workflows/analyze-coherent-spans.md](workflows/analyze-coherent-spans.md)

- name: Refresh core database snapshot
  description: After a specific user request, download a staged Passaging, Media, Perspective, and LiquidNitrogen bundle with archived baselines and diffs.
  path: [workflows/refresh-core-data.md](workflows/refresh-core-data.md)

## References

- name: Cleaned metadata reference
  description: Canonical files, graph semantics, field meanings, QC guidance, and common query routing.
  path: [references/cleaned-metadata-reference.md](references/cleaned-metadata-reference.md)

- name: Growth-fitting function reference
  description: Reusable R functions and input/output contracts for fitting and comparing growth models within culture episodes, rolling
    coherent-span windows, and serial-passage lineages.
  path: [references/lineage-growth-estimation.md](references/lineage-growth-estimation.md)

- name: Detailed lineage-growth analysis example
  description: A self-contained worked example with bundled R and data views; use it to reason from a prepared span through metadata review,
    model support, fair comparison, parameter interpretation, culture-practice alternatives, and follow-up analysis.
  path: [references/detailed-growth-analysis-example.md](references/detailed-growth-analysis-example.md)
