---
name: ingest-lab-records
description: >-
  Compress laboratory notebooks without losing source accountability, and build or update lightweight Markdown knowledge bases linking
  reusable protocols, experimental instances, and cloneID coherent spans. Use for notebook-compression runs, span-to-instance adjudication,
  protocol/instance synthesis, candidate-span queues, and validation of these records.
---

# Ingest Lab Records

Treat this file as a workflow directory. Select the smallest applicable workflow and read only its listed resources. Do not preload every
reference or script.

## Workflows

### Notebook compression

- Purpose: Compress one laboratory-notebook text while preserving chronology, identifiers, quantities, state transitions, deviations,
  interpretations, and source accountability.
- Read: [references/notebook-compression.md](references/notebook-compression.md).
- Prepare parallel inputs with: [scripts/prepare-notebook-compression.py](scripts/prepare-notebook-compression.py).
- Evaluate completed outputs with: [scripts/evaluate-notebook-compression.py](scripts/evaluate-notebook-compression.py).
- Launch prepared tasks with: [scripts/deploy-template.sh](scripts/deploy-template.sh).
- Request template: [assets/notebook-compression-request.json](assets/notebook-compression-request.json).
- Output contract: [assets/notebook-compression-output.schema.json](assets/notebook-compression-output.schema.json).

Read this workflow when compressing notebooks or preparing compression tasks. A compression worker receives only its snapshotted workflow
reference and one packet containing the extracted text spans for one notebook. It must not open the source HTML, other notebooks, the
top-level skill, previous compression outputs, or unrelated project artifacts.

### Instance/protocol database update

- Purpose: update a lightweight Markdown knowledge base of protocols, experimental instances, and coherent-span links.
- Default live database: `lab_records/instance_protocol_db/`. It is durable local state but intentionally excluded from Git.
- Read: [references/instance-protocol-database-update.md](references/instance-protocol-database-update.md).
- Start from the [sources](assets/sources.template.md), [queue](assets/queue.template.md), [instance](assets/instance.template.md),
  [protocol](assets/protocol.template.md), and [turn note](assets/turn-note.template.md) examples.
- Prepare a compact retrieval bootstrap for the next bounded turn with:
  [scripts/prepare-instance-update-turn.py](scripts/prepare-instance-update-turn.py).
- Inspect an existing database progressively with
  [scripts/catalog-instance-protocol-db.py](scripts/catalog-instance-protocol-db.py).
- Discover evidence with: [scripts/search-coherent-spans.py](scripts/search-coherent-spans.py),
  [scripts/surface-notebook-summaries.py](scripts/surface-notebook-summaries.py), and
  [scripts/search-lab-records.py](scripts/search-lab-records.py); extract selected notebook paragraphs with
  [scripts/extract-notebook-evidence.py](scripts/extract-notebook-evidence.py).
- Validate with: [scripts/validate-instance-protocol-db.py](scripts/validate-instance-protocol-db.py).
- Run bounded serial tests with: [scripts/run-instance-update-test.py](scripts/run-instance-update-test.py). It freezes before/after database
  states for every turn and renders each event trace with [scripts/render-events-text.py](scripts/render-events-text.py).

Update serially when records share spans or instances. `sources.md` fixes the evidence snapshot, `queue.md` identifies the next work item, and
preparation surfaces a small starting context; retrieve detailed span, notebook, and database evidence progressively. Keep spans canonical
and external; do not author span records. Review experiments that generate or maintain cells separately from later experiments that sample
or assay them. Keep protocols general and place execution-specific parameters and deviations in instances. Treat resolved queue history as
authoritative and never requeue a resolved span. Do not consult legacy catalogs unless explicitly requested.
