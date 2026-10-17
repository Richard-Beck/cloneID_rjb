# Figure data bundle

The bundle contains only the saved reporting evidence needed to regenerate this approved figure and its numerical checks. It
contains no optimizer checkpoints, executable model, complete campaign tree, raw-image collection, private path manifest or
scheduler connection. Observed images are the approved saved display pixels, encoded as lossless PNGs; their pre-existing
annotations are excluded by the unchanged representative-window rule. They are not new raw-image reads.

| File | Contents |
| --- | --- |
| `figure_data/F1_*` through `F4_*` | Four exact approved 700 x 550 brightfield crops and four complete 1400 x 1100 registered segmentation displays, preserving decoded RGB pixels exactly |
| `figure_data/cells.npz` | Complete saved native x/y/volume columns, exact dead/state codes for eight displayed fields, plus prepared observed centroids, contour-area proxies and dead flags |
| `figure_data/numerics.npz` | Frozen observed/scales/weights arrays, two-seed Lineage-guided and four-seed Perspective guided predictions, four observed full-field spatial distributions, and frozen composition time/log-odds series |
| `figure_data/plot_data.json` | Measured count/design rows, lineage edges, karyotype locations, 220 chromosome counts, episode links, assays, field geometry/provenance and expected full-support losses |
| `figure_data/compute_inputs.json` | Recorded objective-call totals, measured campaign/search CPU and matched complete-native-objective benchmark CPU sums |
| `figure_data/expected.json` | Approved crop rectangles, count/component values and pixel hashes used by rebuild checks |
| `figure_data/manifest.json` | Bundle sizes/hashes, source identities/hashes, geometry/units and exact plotting-library versions |

NPZ arrays contain only numeric/boolean data and are loaded without pickle. Full-precision float64 coordinates/volumes are retained;
no cell subsampling or geometry rounding is added. The full field's simulation-coordinate origin is (-700, -550). The
renderer converts sphere volume to projected disk radius and partitions overlaps exactly as before. Lineage colors describe
founding 2N/4N identity; perspective colors describe current genomic state. The observed masks have no genomic assignment.

The unplotted 75% of brightfield pixels is omitted. Each retained crop's full-field origin is recorded in `plot_data.json` and
checked against the window recomputed from the full segmentation/geometry. This bundle supports the approved cropped figure;
it does not supply the optional full-brightfield alternative. No omitted brightfield pixel enters a fitted statistic or crop criterion.

Observed centroids were rounded in the prepared pilot products to 0.01 pixels. Contour-derived areas are morphology proxies,
not exact fitted pixel areas. Their count/class totals and nearest-neighbor summaries were checked against the frozen field
measurements; exact observed coverage/gap targets remain bundled separately. Geometry conversions and prepared-source hashes
are retained without private filesystem paths.

`crop_selection.py` uses the unchanged 11x11 origin grid, metric scales and deterministic tie-break. Each candidate window is
compared with its own full field using density, dead fraction, coverage, gap, organization, relative area and, for native fields,
living state abundance. It never selects windows by observed-versus-model agreement. Observed image/mask windows are registered;
independent native realizations have independently representative windows. Every displayed crop is 700 x 550 pixels, 25% of the
1400 x 1100 field, with a 100-pixel scale bar. Rebuild logs contain every candidate's crop/full metrics.

The Lineage-guided source is campaign `20261016_180145_sum159_total_count_shared_ridge`, pooled alpha-100 selection `ridge_0100_10`.
The Perspective guided source is campaign `20261016_190611_sum159_total_count_latent_state`, its selected refined alpha-0 example
with the frozen physical vector/correction. D uses that frozen fitted composition, matching the native initialization mixtures.
The separate recheck changed fractions by up to 8.27 percentage points, with 127/128 minority probes completed. The shifted
mixtures did not receive another microscopy evaluation; image loss plus rechecked composition loss is not a validated joint score.
Native fields are independent realizations; frozen culture-wide composition transfers at the recorded parent harvest time.

The six complete-field cost coefficients are 0.5 for total retained live+dead count and 0.1 each for dead count, coverage, relative
area, gap and organization. Seeds are scored separately and averaged. E counts are the arithmetic mean on the linear count scale;
its spatial example uses seed 0. Observed spatial CDFs summarize four fields, while F2 displays one representative field.

Hypoxia 1 and hypoxia 2 denote separately propagated branches with matching recorded oxygen series. The source records do not
establish an additional treatment difference or stronger experimental-replication claim. Normoxia is excluded from D.

## CPU estimate

The compact inputs are sufficient statistics for the approved projection: original objective counters and measured `TotalCPU`
aggregates for scientifically complete native objectives. Individual scheduler rows and campaign files are not rebuild inputs.
The helper recomputes the means, benchmark spreads and replacement-call arithmetic; expected totals are checked rather than used
as substitutes for that arithmetic.

```text
projected_CPUh = measured_CPUh - approximation_search_CPUh
                 + sum(recorded_calls(stage) * mean_complete_native_CPUh(stage))
```

| Search | Calls | Benchmark support | Complete benchmark objectives |
| --- | ---: | --- | ---: |
| Lineage shared | 11,789 | 343 acquisitions, two seeds, 16 native tasks | 11 |
| Lineage founder-specific | 22,878 | 343 acquisitions, two seeds, 32 native tasks | 45 |
| Perspective exploration | 53,016 | 118 passages, four seeds; 472 main fields + 128 probes | 2 |
| Perspective bounded refinement | 556 | Same complete support for this hypothetical replacement | Same 2 |

Used CPU includes the measured campaigns' failed work. Complete benchmark selection excludes failed/nonfinite scientific support,
not unavailable accounting. The displayed perspective example's incomplete probe objective is excluded from the successful-call
benchmark without imputation. Its earlier screen used 24 passages/two seeds and is recorded as context, not scaled into a full call.
No allocated CPU-hours or elapsed-time-times-capacity estimate enters the calculation.

Holding the objective-call budget fixed does not promise the same convergence, parameters or optimization path. Benchmarks are
optimized checkpoints and do not sample every cost region. Lineage 10th/90th-percentile and perspective min/max benchmark spreads
are descriptive sensitivities, not confidence intervals. Additional pure-native composition-history closure iterations, native
correction fitting and analytical closure guidance without a measured counterpart are unpriced. The estimate is a conditional
scenario, not a measured or fully specified native-only optimization.
