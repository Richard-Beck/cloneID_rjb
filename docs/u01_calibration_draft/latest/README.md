# Baseline figure: concluded SUM-159 pilots

Current preview: [baseline_multipanel.png](baseline_multipanel.png), with a [PDF](baseline_multipanel.pdf).
[preview.html](preview.html) provides the figure, text and source notes; [caption.md](caption.md) supplies the updated caption.

This folder contains the verified figure prepared from the two concluded named pilots. The figure builder performs no fitting,
simulation, or new raw microscopy access. It uses saved report display assets and native XML/MAT snapshots.

## Layout revision

The initial panel mapping is retained below. The current revision labels panels A--F only, removes descriptive panel/facet titles,
and arranges F1--F4 as a compact 2x2 grid of comparison groups.

| Previous panel | Content | Revised panel |
| --- | --- | --- |
| A | Lineage | A |
| B | Chromosome histogram | B |
| E | Compute | C |
| F | Hypoxia trajectories | D |
| C | Cost components | E |
| G | Matched fields | F |
| D | Duplicate snapshot/segmentation strip | Removed |

In the revised labels, the layout is:

```text
AAAE
BCDE
FFFF
FFFF
```

A's lineage axis is 7.25 inches wide. E's cost facets remain stacked in a narrow right-hand column, each 1.18 inches wide, with a common
legend and short axis labels. Every F group retains brightfield, segmentation, lineage simulation and perspective simulation across
four small images. Within-group gutters are 0.015 inches. Modality and F1--F4/acquisition labels are overlaid with translucent backing;
no outside image headings consume row space. All four cases remain present.

The figure is 11.5 x 7.25 inches, compared with the original 18 x 24 inches: 80.7% less figure area. The complete-field alternative remains in the isolated development folder; it is not duplicated here.

## Panel choices

- A highlights 2N hypoxia 1 A18 in gold and links it to E and F2. F1--F4 and molecular sampling proxies remain visible.
- B pools all 220 chromosome counts into a histogram with bins two chromosomes wide. The existing nonWGD/WGD clusters retain blue/pink
  colors; measurement-source labels are removed.
- C shows actual used/allocated CPU-hours separately for the concluded lineage campaign (34.0/70.1) and perspective campaign
  (128.4/197.4), with approximately 40 and 31 minutes elapsed, respectively. These are full recorded scheduler scopes; local work is
  outside those totals. No hypothetical PhysiCell-only projection is shown.
- D removes normoxia trajectories and normoxia-specific observations. Hypoxia 1/hypoxia 2 use the same dark ink with solid/dashed lines, and the lineage
  reference is dotted. Molecular observations and frozen fitted proxies have distinct marker shapes. The perspective trajectory uses
  the final frozen physical vector and correction, matching the frozen mixtures used to initialize native fields.
- E illustrates the six cost components using one accepted lineage-defined example: total/dead count, coverage, relative area, gap and
  organization. Coefficients are 0.5 for total count and 0.1 for each other term. The gold acquisition-time marker links directly to F2.
- F2 brightfield, segmentation and lineage simulation have separate inset gold frames linking them to E. The perspective simulation is unframed. Every F image uses a 700 x 550-pixel window from a 1400 x 1100-pixel field:
  exactly 25% of its area. Brightfield and segmentation share one registered window. Independent native realizations may use separate
  windows representative of their own full fields. Cropped panels retain identical scale with 100-pixel bars; the full-field alternative
  has 200-pixel bars.

## Representative display windows

`crop_selection.py` selects each observed/native window against its own full field. It never compares an observed crop with a simulation
and does not optimize their visual agreement. The frozen source of truth for fit/validation remains the complete field.

Candidate origins form an 11x11 deterministic grid: x = 0,70,...,700; y = 0,55,...,550. An observed window is rejected if it intersects the
pre-existing saved scale-bar/label overlay. The registered brightfield uses the selected segmentation window. Each independent native
field has its own selection. The criterion equally weights available groups: count density, dead fraction, coverage, censored gap median,
boundary-screened density-scaled nearest-neighbor distance, 10/50/90% log-area quantiles, and living high-state fraction. The genomic
fraction group is omitted for observations because the mask has no genomic labels. Native fractions use actual living cells in that
full-field realization, not the fitted culture-wide latent fraction.

Discrepancies are scaled by log(1.25) for density/gap, 0.05 for dead/coverage/genomic fractions, 0.10 for organization, and 0.20 for log-area
quantiles. Lowest unrounded mean squared discrepancy wins; ties use distance to the centered origin, then y, then x. Density explicitly
accounts for the quarter-field area. Area quantiles use the full field's mean normalization. The NN summary excludes focal centers whose
nearest-neighbor distance exceeds their distance to the window edge. These are presentation criteria, not additions to the fitted cost.

Observed cell counts/centroids come from saved prepared classification TSVs inside the pilot outputs. Full counts and class counts match
the saved report; converted centroids reproduce exact-mask full-field Clark--Evans within 0.000011. Centroids were rounded to 0.01 px,
and contour-derived areas are morphology proxies, not exact fitted pixel areas. Full observed coverage/gap targets are the saved frozen
field measurements; candidate envelopes use the saved segmentation display after rejecting annotation-overlapping windows. No legacy
raw image, mask or feature collection is reopened. Exact TSV identities, hashes, unit conversion and limitations are recorded locally.

`.local/crop_selection.json` records the grid/rule/scales, every eligible/rejected candidate, selected rectangles, crop-versus-full counts,
spatial summaries and native living-state abundances. Model/observation agreement and the complete-field fitted scores are unchanged.

## Data and interpretation

The lineage source is the accepted scratch campaign `20261016_180145_sum159_total_count_shared_ridge`, using `ridge_0100_10`, selected on
the pooled alpha-100 path. Its full-support simulator loss is 9.2971, independently reconstructed with the current six coefficients. Aggregate
weighted contributions remain in `.local/accepted_lineage_loss_components.csv`; they are full-support values, not scores for a displayed crop.

The perspective source is `20261016_190611_sum159_total_count_latent_state`, using `refined_no_wgd_0p0_072` from its final-validation
report. It is the displayed example with the lowest reported conditional rechecked diagnostic and smallest composition drift among
the three finalists. It is not described as a self-consistent native winner. The figure uses its frozen physical vector and frozen
selection correction, the exact saved frozen-cohort log-odds arrays, and fresh main-field snapshots initialized at those same mixtures.

The perspective microscopy loss is 10.7331 with complete 343-acquisition, four-seed support and all 472 ordinary fields. Its fresh
composition recheck shifts fractions by up to 8.27 percentage points; 127/128 minority probes completed. The shifted mixtures did not
receive another microscopy evaluation. Therefore image loss plus the rechecked assay loss remains a conditional diagnostic, not a
self-consistent validated total. The unavailable probe is retained as missing in the source report. The GREEN recheck is a validation
measurement; D plots the matching frozen fitted trajectory, corresponding to BLUE in the source report.

Culture-wide log odds transfer at the recorded parent harvest time. Independent finite native fields draw local mixtures and do not
propagate their integer counts or local extinctions into descendants. Frozen parent/child inheritance and every displayed report
fraction are independently checked against the saved latent arrays. On D's passage axis, an A(p) episode occupies p-1 through p;
seed-proxy observations mark the preceding parent harvest. Common-root harvest is passage zero.

E counts show observations and the arithmetic mean of the accepted lineage candidate's two saved simulator seeds. The spatial illustration
uses one saved simulator seed at the highlighted final acquisition. Observed spatial evidence is the acquisition's four saved full fields:
areas are pooled across fields, while gap and nearest-neighbor CDFs are averaged across fields. F2 displays the representative tile `tl`,
not every field contributing to the observed acquisition summary. Its images are illustrative, not independent per-crop cost estimates.
Relative area uses full disk areas for simulated cells; display masks partition overlapping disks. All fitted statistics and loss checks use
the original full-field geometry. None are recomputed on the 25% display crops.

Observed panels reuse saved report display assets. Simulator panels are rendered from saved XML/MAT snapshots. This draft does not re-open
historical raw imaging paths. Detailed source paths, hashes, field selections and checks are in Git-ignored `.local/`.

Simulation blue/pink colors describe founding identity in the lineage model and current genomic state in the perspective model. The mask
does not have a genomic assignment: green is alive, orange is dead, and multinucleated labels are included as alive.

## Rebuild and replace final sources

From the project root:

```sh
conda run -n cpose python docs/u01_calibration_draft/latest/build_figure.py
```

`config.json` records both campaign/candidate pairs, selection strengths, count schemas, display crop and figure dimensions. Its two source
loaders follow the different saved-output schemas explicitly. Local frozen reference evidence supplies the unchanged chromosome records,
field selection and observed spatial distributions; rebuilding does not depend on mutable `latest/` contents. No source model is imported
or executed. Rebuilding requires the named local pilot outputs and the accompanying `.local/reference_inputs/` folder.

`.local/verification.json` records reconstruction of the accepted candidate's weighted full-support score, observed/native spatial vectors,
matching simulator times and observed field selections, narrow stacked cost facets, the 2x2 F case grid, removal of the separate snapshot
strip, and labels contained inside image panels. `.local/dependencies.json` records hashes of the required source files. Historical revisions are not normal rebuild dependencies;
archive preservation is checked separately at promotion. It also verifies the perspective four-seed score, input/scales/weight agreement, frozen log-odds semantics, actual native
sample times, checkpoint hashes and full-field total/dead counts in all displayed snapshots. Rendered previews were inspected visually.
This figure revision does not edit the grant source; shared workflow guidance is maintained separately.

## Spacing revisions

The approved text, caption, crop selections, model choices and plotted data are unchanged. A's axis starts at 0.42 inches from the top
(previously 0.75); B--D axes start at 2.64 inches (previously 3.85), with 0.21 inches between their panel letters and axes. C and D are
packed more closely across the row. E's facets are packed to match the shorter upper block; F's approved image dimensions and 2x2
arrangement are unchanged and move upward together. Overall height falls from 9.05 to 7.65 inches, a 15.5% reduction.

`.local/spacing_verification.json` compares every plotted line/scatter array, rectangle bounds, image pixels and axis label against the
previous approved builder. Crop evidence is exactly equal. Normal rebuilding requires only the named pilot artifacts and local frozen
reference inputs; no historical revision archive is opened solely for a preservation check. Separate promotion manifests retain the
local archive-integrity audit.

The follow-up reduces E's axis-to-axis horizontal gap from the rightmost D facet from 1.42 to 0.72 inches (E shifts left 0.70 inches).
F moves upward 0.40 inches without changing image dimensions: its first row begins at 4.84 rather than 5.24 inches. The vertical gap
from the B--D axis bottoms to F image tops falls from 1.15 to 0.75 inches, with C's elapsed annotation brought closer to its axis.
E's five facets are packed to keep their labels readable above F. Height is now 7.25 inches, another 5.2% reduction from 7.65.

Internal branch IDs remain O1/O2; only displayed names change to hypoxia 1/hypoxia 2. Chemical oxygen notation (% O2) is unchanged.
Gold frames identify the observed field, its segmentation and the lineage snapshot associated with the single-model illustration in E;
the perspective snapshot is not highlighted. `.local/gap_label_verification.json` verifies the plotted numerical arrays and image pixels
against the incumbent, excluding only the requested decorative-frame changes. Crop selection is exactly unchanged.

The preceding latest is preserved locally in `docs/u01_calibration_draft/revisions/revision_09/`; earlier local archives remain intact. Revision archives and private `.local/` evidence/reference inputs are excluded from the Git checkpoint. Normal rebuilding requires the named local pilot artifacts and `.local/reference_inputs/`, but no historical archive.
