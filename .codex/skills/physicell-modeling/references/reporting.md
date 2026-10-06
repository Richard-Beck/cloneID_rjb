# PhysiCell report standard

HTML is the primary report. It must work offline from its own folder, without a server, CDN, account or external service.
Use plain-language model definitions and state the actual fitting protocol. Link frozen vectors, scores and source manifests.

## Required contents

1. **Stage comparison.** Show best PhysiCell loss, improvement over stationary, candidate identity/origin, and counts of
   new scorable fits versus starts, separately by confirmed parameter-sharing group. Define stationary, constant and adaptation beside this table.
2. **Matched fields.** Display raw observed image, neighbor-colored observed mask and neighbor-colored simulated fields
   side by side. Select representative observations across each arm's early/middle/late passages without consulting residuals. Include all available imaged timepoints within each selected passage, stacked vertically. Use a median-cell-count accessible tile. Default to the best candidate from each
   stage; dropdowns select the passage and representative rank (first/second/third). Always show all stages side by side; omit the Display dropdown.
   Show passage, time, tile, candidate, loss and visible-cell counts. Include enlargement and raw/mask/snapshot paths and hashes.
   Verify cropping and dimensions from segmentation metadata and simulation times to within one mechanics step.
3. **Passage plots.** Observed counts are points; stage-best PhysiCell predictions are colored lines. Include every eligible
   passage, one facet per passage in a five-column, four-row grid (20 per page), navigable by group, arm and page.
   Use a plot-class dropdown for counts, cell-area distributions and available spatial measures (coverage, gap, Clark–Evans).
   Show simulated area medians with 25–75% and 10–90% shaded bands, and observed quantile boxes at acquisition times
   (25/50/75% boxes with 10/90% whiskers). Distinguish distribution spread from fit uncertainty. State area normalization,
   units, quantile interpolation and spatial-summary transformations. Connect saved simulation samples, retaining missing values.
   Keep narrow screens horizontally scrollable so all five columns remain legible. Make linear/log scale selectable. Preserve the
   frozen count conversion for each candidate and label counts versus time explicitly.
4. **Loss components.** Show the selected candidates' weighted count, coverage, relative-area, gap and Clark–Evans
   contributions as a stacked chart whose parts sum to total loss. Show total loss versus selectable components (including
   agreed component groupings such as area and organization) across candidates, with stage-best diamonds. Include matched-support predicted-versus-
   PhysiCell data loss. Label inherited candidates and allow new-only filtering.
5. **Parameter diversity.** Independently select each stage's cutoff above its best PhysiCell loss, defaulting to 5%.
   Plot parameter names on x, log10 values on y, stage colors and offsets, reproducible jitter, and stage-best diamonds.
   Include raw values, units, candidate ID/loss and inheritance on hover, with a selected-parameter table. Separate
   biological/initialization/condition coefficients from kinetic endpoints/timing for readability, labeling each coefficient's
   actual branch or shared scope. Expand stationary coefficients to equivalent branch values for display, and stationary/constant
   reference rates into equivalent early/late endpoints per branch. Hide sigmoid timing for flat curves; plot midpoint as
   an explicitly documented shift if needed for zero values; choose the shift in the confirmed coordinate units. Exact duplicate parameter vectors count once within each stage.
6. **Audit.** Provide machine-readable report data, weighted losses, image-selection and field-provenance manifests, and
   links to the stage outputs. Keep original observations and fitted outputs intact. List inaccessible requested images
   explicitly rather than silently substituting an unrelated field.

## Visual and scientific checks

Use consistent blue/orange/green stage colors across panels. Image colors indicate adjacency, not identity or phenotype.
Observed and simulated fields are independent realizations; their passage/medium/time and field dimensions match.
Simulation display masks partition overlapping disks for legibility; area scoring continues to use full disk areas.
Include a pixel scale bar unless a calibrated physical pixel size is available. Do not invent image registration.

The representative subset is for images only. Growth and objective comparisons retain the full frozen observation support.
Near-best plots describe retained search solutions, with explicit stage-specific loss thresholds. Counts in the interface
must update when cutoffs or new/inherited filtering change. Stage-best markers remain visible for reference.

Check numerical loss sums and inherited-score equality. Verify finite values for full-coverage gap measurements. Browser
checks must verify all controls, that the candidate/image changes, that all images load, and that no JavaScript errors occur.
Provide static CSV/JSON exports alongside interactive plots. Scientific image panels must be rendered from the recorded
microscopy files and simulator output, never synthesized or aesthetically modified.

Use the packaged template and renderer described in [report-data.md](report-data.md). Supply actual definitions, weights, image geometry and protocol; no dataset-specific values are embedded in the template. Add serial wall time, CPU-hours and peak CPU allocation/use, including the source of the accounting.

Use Plotly title objects (`title: {text: ...}`) for axes and chart titles, with readable colors and adequate margins.
Browser checks must inspect rendered scatter-axis title text, not just layout metadata, and exercise passage pagination,
metric selection, all timepoint rows and candidate ranks. Counts-only payloads remain supported; disable unavailable metric choices.
