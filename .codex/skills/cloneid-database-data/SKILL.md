---
name: cloneid-database-data
description: Use when querying, summarizing, or retrieving cloneID database metadata, especially passaging lineage DAGs, culture episodes, media conditions, Perspective assay anchors, biological replicates, longest lineages, or cleaned cloneID CSV outputs.
---

# cloneID Database Data

Use this skill for cloneID metadata questions such as "find the longest lineage", "find apparent biological replicates more than 10 passages long", "summarize media transitions", "find assay-bearing samples", or "retrieve passaging/episode records".

## Data Location

Use the repository root containing this skill. In the current checkout, that is:

```text
/home/4473331/projects/cloneID_rjb
```

Cleaned outputs live in `data/`. If they are missing or stale, regenerate them from the repo root:

```bash
conda run -n R-4.2.3 Rscript scripts/annotate_metadata_graph.R
```

## Core Interpretation

cloneID has two linked graph views:

- **Row-level provenance DAG**: each `passage_id` is one database record from `passaging.csv`. Parents are `passaged_from_id1/2`.
- **Culture-episode graph**: each `seeding` row is one culture episode/flask/passaging unit. Its child `harvest` rows are observation/image/segmentation timepoints. A `harvest -> seeding` edge usually means propagation into the next episode.

Use the episode graph for biological lineage questions. Use the row-level DAG when individual images, harvest observations, raw provenance, or nonstandard records matter.

## Files

- `data/culture_episodes.csv`: one row per seeding/culture episode. Best starting point for lineage depth, passage chains, biological replicate candidates, media context, episode-level assay coverage, and summarized harvest observations.
- `data/culture_episode_edges.csv`: episode-level propagation graph. Use for longest lineages, branches, parents/children, media transitions, mixing, and passage-depth traversal.
- `data/annotated_passaging_nodes.csv`: one row per raw passaging record. Use for individual `harvest` observations, image/readout records, Perspective anchors, media joins, and row-level QC.
- `data/passaging_edges.csv`: original row-level parent-child edges with `edge_kind`.
- `data/metadata_graph_qc_summary.csv`: QC counts and sanity checks.
- `core_data/media.csv`, `core_data/passaging.csv`, `core_data/perspective.csv`: raw source tables.

## Edge Kinds

In `passaging_edges.csv`:

- `observation_edge`: `seeding -> harvest`; within-episode observation/readout.
- `propagation_edge`: `harvest -> seeding`; normal passage to a downstream episode.
- `nonstandard_harvest_to_harvest`: suspicious or imported/collapsed provenance.
- `nonstandard_seeding_to_seeding`: direct episode-to-episode edge; preserve but flag.
- `multiparent_edge`: child has two parents, often possible mixing.

In `culture_episode_edges.csv`, normal biological propagation is `propagation_edge`. Direct `seeding -> seeding` cases are preserved as `nonstandard_direct_seeding_to_seeding`.

## Recommended Workflow

1. Start with `culture_episodes.csv` and `culture_episode_edges.csv` for lineage questions.
2. Filter out or separately report rows with serious `qc_flags`, depending on the user question.
3. Use `episode_depth`, `episode_parent_count`, `episode_child_count`, `episode_is_branch_point`, and `episode_is_multiparent` for graph structure.
4. Use `seeding_media_id`, `media_broad_category`, and `culture_episode_edges.media_changed` for media-transition questions.
5. Use `perspective_record_count_in_episode`, `perspective_types_in_episode`, and `inferred_assay_labels_in_episode` for sparse omics/karyotyping anchors.
6. Join back to `annotated_passaging_nodes.csv` on `culture_episode_id` when individual harvest observations or exact `passage_id`s are needed.

## Assay Labels

Perspective records are sparse assay anchors, not a complete assay schema. Inferred labels use `whichPerspective + n` heuristics:

- `n == 1`: bulk-like.
- `15 <= n <= 35`: karyotype-like.
- `n > 50`: single-cell/high-throughput-like.
- otherwise: ambiguous/unknown.

Always describe these as heuristic labels unless the raw assay provenance is available.

## Query Patterns

For graph queries, Python with `csv` and adjacency maps is usually enough. Prefer deterministic scripts over manual inspection for anything involving paths or graph traversal.

Longest episode lineage:

```python
import csv
episodes = list(csv.DictReader(open("data/culture_episodes.csv", newline="")))
deepest = max(episodes, key=lambda r: int(r["episode_depth"] or -1))
print(deepest["episode_id"], deepest["episode_depth"])
```

Candidate biological replicates:

```text
Group episodes by shared parent/root/cellLine/media context, require long descendant chains or repeated sibling branches, then inspect QC flags and harvest counts before reporting.
```

Media transition questions:

```text
Use culture_episode_edges where media_changed == TRUE, then summarize parent/child media, cellLine, edge depth, and downstream descendants.
```

## Reporting Rules

- State whether the answer used the episode graph or row-level DAG.
- Report QC caveats explicitly when nonstandard edges, missing parent episodes, timestamp inversions, or multiparent/mixing records affect the result.
- Do not treat absence of descendants as biological failure without supporting context.
- Do not make strong claims about assay technology from Perspective alone; label inferences as heuristic.
