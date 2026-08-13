# Core Input Fields

Best-effort interpretation of the three source exports. Field names and units are preserved literally; review uncertain meanings before biological analysis.

## `core_data/passaging.csv`

One row per recorded culture event or related database record.

| Field | Interpretation |
|---|---|
| `id` | Unique passaging-record identifier and graph node key. |
| `cellLine` | Cell-line or culture label. |
| `event` | Usually `seeding` or `harvest`; blank values occur. |
| `passaged_from_id1`, `passaged_from_id2` | First and optional second parent/source identifiers. Some roots use labels rather than valid record IDs. |
| `growthType` | Sparse free-text growth morphology, such as adherent or suspension. |
| `passage` | Recorded passage number or label. |
| `cellCount` | Original or uncorrected recorded count. This may be an earlier quantification of the same source image used to generate `correctedCount`; it should not be assumed to be an independent wet-lab measurement. |
| `date` | Event timestamp as stored. Treat the recorded day as reliable unless other records clearly conflict, but do not assume hour-level precision or exact same-day ordering. |
| `address` | Site or laboratory associated with the record. |
| `comment` | Free-text notes. |
| `media` | Media identifier referring to `media.csv:id`; may be blank. |
| `feeding1`–`feeding9`, `feeding17` | Successive recorded feeding timestamps. The irregular numbering reflects the export schema. |
| `Countess` | Count recorded from a Countess instrument or workflow; exact use should be confirmed. |
| `flask` | Flask or vessel code as stored. |
| `correctedCount` | Updated count, understood to commonly reflect re-segmentation or re-counting of the same source image using an updated image-analysis procedure. Prefer it over `cellCount` when valid. The export does not report the segmentation algorithm, version, run identifier, or complete correction provenance, so `correctedCount` should be treated as the preferred available quantification, not as independently verified ground truth. |
| `areaOccupied_um2` | Recorded occupied area in square micrometres, generally image-derived. |
| `cellSize_um2` | Recorded cell-size estimate in square micrometres, generally image-derived. |
| `owner` | Record owner or creator identity. |
| `lastModified` | Identity associated with the latest modification, despite the timestamp-like field name. |
| `transactionId` | Sparse source-system transaction identifier. |
| `BeforeCorrection_From_Passage_Media` | Audit text describing values before correction of provenance, passage, or media fields. |
| `lastModifiedDate` | Latest-modification timestamp when recorded. |

## `core_data/media.csv`

One row per media definition. Blank and zero values are not always used consistently.

| Field | Interpretation |
|---|---|
| `id` | Unique media identifier referenced by passaging records. |
| `base1`, `base1_pct` | Primary base-medium identity and recorded percentage. |
| `base2`, `base2_pct` | Optional second base-medium identity and percentage. |
| `FBS`, `FBS_pct` | Serum identity and percentage. Values include FBS variants and horse serum. |
| `EnergySource`, `EnergySource_nM` | Primary metabolic or hormonal additive and recorded nominal concentration. The `_nM` unit label may not be reliable for every ingredient. |
| `EnergySource2`, `EnergySource2_pct` | Secondary additive and recorded percentage or amount-like value; interpretation varies by ingredient. |
| `HEPES`, `HEPES_mM` | HEPES identity and nominal millimolar concentration. |
| `Salt`, `Salt_nM` | Salt identity and recorded nominal concentration. The `_nM` unit label should not be assumed correct without review. |
| `antibiotic`, `antibiotic_pct` | First antibiotic identity and percentage. |
| `antibiotic2`, `antibiotic2_pct` | Second antibiotic identity and percentage. |
| `antibiotic3`, `antibiotic3_pct` | Third antibiotic identity and percentage; some rows contain an amount without an identity. |
| `antibiotic4`, `antibiotic4_pct` | Fourth antibiotic identity and percentage. |
| `antimycotic`, `antimycotic_pct` | Antimycotic identity and percentage. |
| `growthFactors` | Free-text growth-factor identities; no dedicated dose field. |
| `Stressor` | Stressor or other special additive identity. This field is semantically broad. |
| `Stressor_concentration`, `Stressor_unit` | Recorded stressor dose and unit; either may be missing. |
| `comment` | Free-text media notes; currently blank in the export. |
| `oxygen_pct` | Recorded oxygen percentage. |
| `export4pub` | Source-system publication/export flag. |

Do not derive a scalar media distance directly from these fields without defining ingredient normalization, unit conversion, missingness, and domain weights.

## `core_data/perspective.csv`

Sparse assay anchors associated with passaging records.

| Field | Interpretation |
|---|---|
| `whichPerspective` | Perspective family, currently transcriptome, genome, or morphology. |
| `origin` | Source identifier intended to match `passaging.csv:id`; unmatched origins occur. |
| `n` | Number of raw Perspective records sharing this `whichPerspective` and `origin`. |

Heuristic labels currently use `n == 1` as bulk-like, `15–35` as karyotype-like, and `n > 50` as single-cell/high-throughput-like. These labels are orientation aids, not assay provenance.
