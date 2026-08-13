# Rebuild Cleaned Metadata

Use this workflow when cleaned graph outputs are missing or stale. Read [the core input field reference](../references/core-data-fields.md) before reviewing source fields and [the cleaned metadata reference](../references/cleaned-metadata-reference.md) before interpreting outputs.

## 1. Validate inputs

From the repository root, run:

```bash
.codex/skills/cloneid-database-data/scripts/validate_core_inputs.py
```

Stop on validation errors. Review warnings, which may describe known source-data limitations rather than rebuild blockers.

## 2. Rebuild

Run:

```bash
scripts/agentRrunner.sh .codex/skills/cloneid-database-data/scripts/annotate_metadata_graph.R
```

This is a protocol-agnostic rebuild: `protocol_id` and `seeding_protocol_id` are left blank because no reviewed protocol mapping is bundled.
The script reads the local, untracked `core_data/passaging.csv`, `core_data/media.csv`, and `core_data/perspective.csv`.

The script replaces only these owned outputs:

- `data/annotated_passaging_nodes.csv`
- `data/passaging_edges.csv`
- `data/culture_episodes.csv`
- `data/culture_episode_edges.csv`
- `data/metadata_graph_qc_summary.csv`

After rebuilding, inspect `data/metadata_graph_qc_summary.csv` and confirm that all five outputs exist and contain rows. Report cycles, invalid parents, malformed dates, nonstandard edges, mixing, and negative durations when relevant.
