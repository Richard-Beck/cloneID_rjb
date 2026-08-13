# cloneID agentic research workflows

This repository supports reproducible, agent-assisted research with cloneID data. It brings together the reusable workflows needed to
reconstruct cell-culture lineages from the cloneID database, connect those lineages to laboratory-notebook evidence, organize experimental
instances and protocols, and execute reviewed scientific hypothesis tests.

The repository tracks workflow code, Codex skills, prompts, schemas, and hypothesis plans. Raw database snapshots, derived metadata, the live
laboratory-record knowledge base, and analysis runs are local state and are intentionally excluded from Git.

## High-level replication sequence

1. Populate `core_data/` with a local snapshot of the cloneID database.
2. Validate the snapshot and generate the cleaned metadata graph and coherent lineage spans under `data/`.
3. Extract and compress the relevant laboratory notebooks.
4. Ingest the notebook and lineage evidence into the live instance/protocol database under `lab_records/instance_protocol_db/`.
5. Execute the canonical hypothesis-testing plan, or develop a new plan from the prepared metadata and laboratory-record evidence.

Detailed guidance, commands, validation rules, and interpretation notes are provided by the skills under `.codex/skills/`:

- `cloneid-database-data` covers core-data refresh, cleaned metadata, coherent spans, lineage interpretation, and growth models.
- `ingest-lab-records` covers notebook compression and construction of the instance/protocol database.

The canonical hypothesis plan is `plans/seed1_hypothesis_test_v3/plan.json`. The worker/reviewer runner and its concise operational notes are
under `scripts/`.

## Local and generated state

- `core_data/`: local raw cloneID snapshot.
- `data/`: regenerated metadata and analysis-ready lineage products.
- `lab_records/instance_protocol_db/`: live local experimental-instance and protocol knowledge base.
- `tmp/`, `dev/`, and `hypothesis_tests/`: temporary development work and run-specific outputs.

These paths are excluded from version control except for small README files that document their intended use.
