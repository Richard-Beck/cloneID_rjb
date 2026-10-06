# cloneID agentic research workflows

> **Research direction reset — 2026-09-21:** All prior hypothesis-testing workflows and plans are deprecated. The current starting
> point is the concrete [PhysiCell baseline](dev/physicell_baseline/workflow.md): a reusable modelling example and counterfactual for
> user-specified hypotheses. Develop explicit extensions from that baseline; do not resume legacy hypothesis runners or treat their
> requirements as the current workflow. Data preparation and laboratory-record maintenance remain supporting infrastructure.

This repository supports reproducible, agent-assisted research with cloneID data. It brings together the reusable workflows needed to
reconstruct cell-culture lineages from the cloneID database, connect those lineages to laboratory-notebook evidence, organize experimental
instances and protocols, and execute reviewed scientific hypothesis tests.

The repository tracks workflow code, Codex skills, prompts, schemas, and hypothesis plans. Raw database snapshots, derived metadata, the live
laboratory-record knowledge base, and analysis runs are local state and are intentionally excluded from Git.

## High-level replication sequence

1. Populate `core_data/` with a local snapshot of the cloneID database.
2. Validate the snapshot and generate the cleaned metadata graph, coherent lineage spans, and availability manifests under `data/`.
3. Extract and compress the relevant laboratory notebooks.
4. Ingest the notebook and lineage evidence into the live instance/protocol database under `lab_records/instance_protocol_db/`.
5. Use the PhysiCell baseline to formulate a user-specified hypothesis, its counterfactual, and the required model extension from the
   prepared metadata and laboratory-record evidence.

Start with the [user guide](docs/skills.md) for encrypted snapshot setup, machine-local imaging paths, example requests and output locations.
See [snapshot publishing](docs/publishing.md) and [imaging data guidance](docs/imaging-data.md).

Detailed guidance, commands, validation rules, and interpretation notes are provided by the skills under `.codex/skills/`:

- `cloneid-database-data` covers core-data refresh, cleaned metadata, coherent spans and lineage interpretation.
- `ingest-lab-records` covers notebook compression, experimental evidence retrieval and construction of the instance/protocol database.
- `physicell-modeling` covers agreed mechanistic model calibration, simulator scoring and interactive reporting.

Imaging and segmentation inputs come only from **CellSegmentations**, including its subdirectories and per-cell feature products. On RED,
set `CELLSEGMENTATIONS_ROOT=/share/lab_crd/CellSegmentations`; on the workstation, set it to the local mount. The detailed recursive
manifest is distributed as an encrypted download, and its paths are relative to that root.

Encrypted snapshots are stored as GitHub Release attachments and served through the static download page. Snapshot files, encryption
passwords and plaintext data stay outside Git history; the repository tracks the packaging and publishing code.

## Instance/protocol database operating loop

The intended workflow for the live laboratory-record database is an iterative, human-reviewed loop. Run the bounded update runner against
`lab_records/instance_protocol_db/`; by default it performs ten serial ingestion turns using Terra with medium reasoning, then asks a
Sol/xhigh reviewer to save prioritized database-compliance recommendations under `lab_records/instance_protocol_db/compliance/`.

```bash
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
python3 .codex/skills/ingest-lab-records/scripts/run-instance-update-test.py \
  --database lab_records/instance_protocol_db \
  --test-root "tmp/instance_protocol_update_${RUN_ID}"
```

Review both the resulting `compliance/*.md` recommendations and the current live database. A human should decide which recommendations are
sound, recording each decision in a disposition Markdown file (start with
`.codex/skills/ingest-lab-records/assets/compliance-disposition.template.md`). Do not treat the compliance review as an automatic change
request: it can make questionable recommendations, so human-in-the-loop judgment remains required.

To apply explicit human-approved recommendations before the next ten-turn ingestion run, supply both files. This adds one preliminary
Sol/xhigh disposition turn; it reads the two files, changes only recommendations explicitly approved in the disposition, validates the
database, and then starts the ordinary ingestion loop.

```bash
python3 .codex/skills/ingest-lab-records/scripts/run-instance-update-test.py \
  --database lab_records/instance_protocol_db \
  --test-root "tmp/instance_protocol_update_${RUN_ID}" \
  --previous-compliance-review lab_records/instance_protocol_db/compliance/<review>.md \
  --user-disposition lab_records/instance_protocol_db/compliance/<disposition>.md
```

Each run retains frozen before/after database copies, event logs, and validation output below its `--test-root`. The runner processes only
one queue item per turn; when the queue is empty, it seeds the longest never-resolved coherent span with at least four passaging-table
entries. Use `--minimum-passaging-entries` to adjust that threshold, and avoid concurrent runs against the live database.

### Current workflow gaps

- There is not yet a defined refresh-and-reingestion procedure for updated laboratory notebooks or newly arrived notebooks.
- There is not yet a defined refresh-and-reconciliation procedure for an updated cloneID snapshot and its regenerated lineage data.
- Compliance-review guidance may need refinement, either through clearer database guidelines or a more detailed reviewer prompt, before its
  recommendations can be relied on more broadly.

The former plan `plans/seed1_hypothesis_test_v3/plan.json` and associated hypothesis worker/reviewer workflows under `scripts/` are legacy
material, not current instructions.

## Local and generated state

- `core_data/`: local raw cloneID snapshot.
- `data/`: regenerated metadata, availability manifests, and analysis-ready lineage products. Reusable growth and spatial evidence is organized
  by biologically meaningful analysis group under `data/longitudinal_analysis/`; it is derived from the cleaned lineage layer and interpreted
  alongside the live laboratory-record database. Each hypothesis still selects its target set scientifically and keeps its audit, synthesis,
  figures, and downstream work in one run-local `hypothesis_tests/` folder.
- `lab_records/instance_protocol_db/`: live local experimental-instance and protocol knowledge base.
- `tmp/`, `dev/`, and `hypothesis_tests/`: temporary development work and run-specific outputs.

These paths are excluded from version control except for small README files that document their intended use.
