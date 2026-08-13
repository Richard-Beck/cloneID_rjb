# Analyze Coherent Spans

Use this workflow for connected runs of culture episodes sharing one media ID. Read [the cleaned metadata reference](../references/cleaned-metadata-reference.md) for graph and measurement semantics.

## 1. Summarize spans

From the repository root, run:

```bash
.codex/skills/cloneid-database-data/scripts/summarize_coherent_spans.py
```

A coherent span is a maximal weakly connected component after retaining episodes with a known `seeding_media_id`, retaining edges whose
endpoints share that ID, and removing edges where the child seed occurs more than 7 days after its immediate parent harvest. The threshold is
configurable with `--max-parent-gap-days N`; an edge at exactly the threshold is retained. Edges with negative or missing/unparseable gaps are
also retained because they are not known to exceed the threshold. Missing-media episodes are excluded by default; use
`--missing-media-mode singleton` to emit them separately.

Outputs under `data/coherent_spans/`:

- `coherent_spans.csv`: one row per span.
- `coherent_span_membership.csv`: episode-to-span assignments.
- `coherent_span_edges.csv`: internal edges and signed timestamp gaps.
- `coherent_span_run_metadata.json`: definitions and validation counts.

Preferred counts use nonnegative `correctedCount`, then nonnegative `cellCount`. These may be different image-processing outputs from the same
source image; the latter is a fallback value, not an independent biological measurement. The export does not identify segmentation-algorithm
versions. Literal seeding density is unavailable without vessel area or volume. Signed inter-episode gaps are retained because timestamps may
not be tightly anchored to measurement events; use the recorded day unless records clearly conflict, but do not assume precise same-day
ordering.

## 2. Compute span distances (optional)

This stage requires `coherent_span_membership.csv` from stage 1.

```bash
.codex/skills/cloneid-database-data/scripts/compute_coherent_span_distances.py
```

For two spans, distance is the minimum episode-edge count between any source-span episode and any target-span episode. Directed mode follows parent-to-child edges; undirected mode permits traversal either way. Unclassified episodes remain available as intermediate nodes.

Outputs under `data/coherent_span_distances/`:

- Directed and undirected dense distance matrices.
- Directed and undirected sparse reachable-pair tables with deterministic witness paths.
- `span_distance_run_metadata.json` with definitions and validation counts.

Use directed distances for descendant reachability. Use undirected distances only for shared graph connectivity. Prefer the sparse tables when most span pairs are unreachable.
