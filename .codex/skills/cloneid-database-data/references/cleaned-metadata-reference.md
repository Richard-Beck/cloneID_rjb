# Cleaned Metadata Reference

## Graph model

cloneID has two linked graph views:

- **Row-level provenance graph:** one node per passaging record. Parent fields are `passaged_from_id1/2`.
- **Culture-episode graph:** one node per seeding event. Assigned harvest rows are observations within that episode; propagation links episodes.

Use the episode graph for lineages, branches, media transitions, and biological units. Use the row graph for individual harvests, images, measurements, and exact provenance.

## Event and episode semantics

Under the intended experimental workflow, each passaging row represents an imaging event. A row may exist even when its corresponding image files are unavailable.

- **Seeding event:** imaging performed immediately after cells are transferred into a new flask or culture environment. A seeding row starts a culture episode, and its passaging ID is the `episode_id`.
- **Harvest event:** any other imaging event. Harvest rows assigned to a seeding event are observations within that culture episode.
- **Culture episode:** one seeding event plus its assigned harvest events.
- **Harvest observation count:** the number of harvest rows unambiguously assigned to the episode. It excludes the seeding row and ambiguous or nonstandard harvest assignments.
- **Terminal harvest candidate:** the latest recorded assigned harvest. By convention, when cells are transferred into a new flask, the latest harvest entry from the preceding culture episode is used as the parent of the new seeding event. This is a provenance convention, not a biologically privileged endpoint or an episode summary. Use `via_harvest_id` for the parent harvest recorded on an actual episode-propagation edge.

## Local canonical inputs

Raw database snapshots are local state and are intentionally excluded from Git. Use the refresh workflow to create and review a staged
snapshot before promoting it into `core_data/`.

- `core_data/passaging.csv`: raw passaging and event records.
- `core_data/media.csv`: media definitions and components.
- `core_data/perspective.csv`: sparse Perspective assay anchors.
- Protocol mappings are optional extensions rather than graph inputs. In a protocol-agnostic rebuild, `protocol_id` fields remain blank.
- No reviewed protocol mapping is currently bundled with the skill.

## Cleaned outputs

### `data/culture_episodes.csv`

One row per seeding episode.

- Identity: `episode_id`, `cellLine`, `seeding_date`, `seeding_protocol_id`, `passage_num`.
- Media: `seeding_media_id`, `seeding_media_label`, `media_broad_category`.
- Seeding quantity: `seeding_cellCount`, `seeding_correctedCount`.
- Harvests: `harvest_observation_count`, `first_harvest_date`, `last_harvest_date`, `terminal_harvest_candidate`, `episode_duration_days`.
- Graph: parent/child counts, depth, component, roots, leaves, branches, and multiparent flags.
- Assays and QC: Perspective summaries, inferred assay labels, `qc_flags`.

### `data/culture_episode_edges.csv`

Episode propagation edges.

- Endpoints: `parent_episode_id`, `child_episode_id`, endpoint existence, cell line, and media.
- Provenance: `via_harvest_id`, `row_edge_id`, `edge_kind`.
- Timing: `via_harvest_date`, `child_seeding_date`, `days_harvest_to_child_seeding`.
- Transitions and QC: media/cell-line changes, mixing, temporal-order flags, `edge_qc_flags`.

### `data/annotated_passaging_nodes.csv`

One row per raw passaging record.

- Record fields: `passage_id`, `protocol_id`, event, cell line, passage, parsed date, parents, and media.
- Measurements: numeric cell count, corrected count, occupied area, and cell size.
- Episode assignment: `culture_episode_id`, observation number, days since seeding, terminal-harvest flag.
- Graph fields: component, lineage depth, ancestors, descendants, degrees, branches, and multiparent flags.
- Assays and QC: Perspective fields, invalid parents, malformed dates, cycles, `qc_flags`.

### `data/passaging_edges.csv`

Row-level parent-child edges with endpoint context, event types, dates, media transitions, mixing, and QC.

### `data/metadata_graph_qc_summary.csv`

Compact graph and metadata validation counts.

## Edge semantics

- `observation_edge`: seeding to harvest within an episode.
- `propagation_edge`: harvest to downstream seeding.
- `nonstandard_harvest_to_harvest`: preserved nonstandard provenance.
- `nonstandard_seeding_to_seeding`: direct seeding-to-seeding provenance.
- `multiparent_edge`: possible mixing or multiple sources.

In the episode-edge table, direct seeding propagation is `nonstandard_direct_seeding_to_seeding`.

## Count semantics and selection

- Operationally, treat `cellCount` and `correctedCount` as alternative quantifications that may have been derived from the same underlying
  image. `correctedCount` commonly reflects subsequent re-segmentation or re-counting, rather than a second biological observation.
- The database export does not identify the segmentation algorithm or version used for either value. Modification fields do not by themselves
  establish image-analysis provenance.
- For primary quantitative analysis, prefer a valid `correctedCount`; otherwise use a valid `cellCount`. Retain both original fields and record
  which one supplied each selected value.
- Do not treat agreement between `cellCount` and `correctedCount` as agreement between independent measurements. Likewise, a
  raw-versus-corrected refit is not a default biological robustness analysis: it primarily measures sensitivity to an incompletely documented
  measurement pipeline.
- Longitudinal changes in corrected-count availability or in the relationship between the two fields should be recorded as measurement-process
  context. Without algorithm-version provenance, they cannot identify the date of a particular segmentation change or establish that either
  value is unbiased.

## Interpretation and QC

- When a reviewed protocol mapping is available, resolve a row's `protocol_id` against that mapping's protocol definition. Episode-level
  `seeding_protocol_id` is inherited from the episode's seeding row. These fields are intentionally blank in a protocol-agnostic rebuild.
- A seeding record defines an episode even when no harvest is recorded.
- `terminal_harvest_candidate` is a harvest record ID, not a boolean.
- Apply the count-selection and provenance guidance above. Treat negative image-like measurements as possible sentinels.
- Database timestamps may not be tightly anchored to the measurement event. Treat the recorded calendar day as reliable unless other records clearly contradict it, but do not rely on hour-level precision or exact same-day ordering.
- Harvest abundance or confluence—and harvest density when a valid denominator is available—is largely conditioned by culture protocol because cells are commonly reseeded near a target confluence. Seed-to-harvest fold change therefore depends strongly on seeding quantity, vessel format, the passage threshold, and time to harvest; do not treat it by itself as an intrinsic growth phenotype.
- `growthType` is usually sparse; check coverage before using it.
- Use exact media IDs and components for comparisons; broad media categories are orientation labels.
- Preserve nonstandard edges and mixing records, but report them explicitly.
- Do not interpret a leaf as biological failure without supporting context.

Perspective anchors are sparse. Inferred labels based on `whichPerspective + n` are heuristic: `n == 1` is bulk-like, `15–35` is karyotype-like, and `n > 50` is single-cell/high-throughput-like.

## Query routing

- Lineages, branches, replicates, media transitions: start with episodes and episode edges.
- Exact harvests, images, measurements, or provenance: join to annotated passaging nodes.
- Longest lineages: use episode depth and verify branches, mixing, and QC.
- Assay-bearing samples: use Perspective counts/types and describe inferred labels as heuristic.
