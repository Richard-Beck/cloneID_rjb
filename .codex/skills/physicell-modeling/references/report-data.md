# Generic report data contract

`render_report.py data.json report-folder` packages local Plotly, styles, controls and images. All input images/linked files are
relative to data.json's directory and are copied into the report folder. Source paths in provenance are plain text; no project
path or server is required to view the report. Build data with the confirmed adapter. Arbitrary group/arm labels are supported.
Use null for an unavailable optional plotted value, never NaN/Infinity. Candidate losses must be finite and scorable.

Top-level JSON fields:

- `title`: report title; `groups`: objects `{id,label}`; `models`: ordered stage IDs (lowercase alphanumeric, underscore/hyphen).
- `model_definitions`: stage ID to actual plain-language definition; optional `colors`: stage ID to plot color.
- `candidates`: exact-vector-deduplicated records per group/stage with `id`, `group`, `stage`, `loss`, `predicted` (data loss,
  excluding assumption penalty), `inherited` boolean, `source_stage`, `components` (weighted named contributions), `params`.
  Each named parameter contains `value` (raw), `log` (plotted transformed value), `unit`, `section` (`shared` or `kinetics`).
  `shared` is a legacy display-section key, not a sharing assumption: include branch-qualified biological, initialization and
  condition coefficient names there. `kinetics` contains G1 endpoints/timing. Expand stationary coefficients for branch comparison
  in display data only; retain the actual fitted vector and declared sharing in the audit.
  Exclude inactive sigmoid timing; document nonstandard log transformations. Candidate IDs break equal-loss ties.
- `best`: keys `groupID_stageID` to winning candidate ID; null for a stage/group without a scorable result.
- `component_names`: ordered weighted loss component names. `component_groups`: display label to list of component names,
  for example an area group combining coverage and relative area. Components must sum to recorded total loss.
- `outcomes` (optional): stage ID to group ID to `{starts,scored}`. Explain failures in protocol and link a full outcome manifest.
- `growth`: one record per included episode, with `group`, `arm` (display label), `episode`, `passage` (display identifier),
  `condition_label`, `times` (days since seeding), `observed`, `passage_ids` (observation IDs), and `simulations` (stage ID to
  counts at those times from its winner, or null entries for unavailable results). Arrays have equal lengths. Values are
  already converted to the reporting count scale; `count_axis_label` names that scale. Retain every episode, not just imaged ones.
- Optional `growth[].plot_label` supplies a short facet title; otherwise the template uses arm and passage without parsing dataset IDs.
- Optional `growth[].metrics` contains `observed` and `simulations` (stage ID to metric object). Each metric object may contain
  `coverage`, `gap`, `clark_evans`, and `area_quantiles`. Every array aligns with that episode's `times`.
  Scalar metrics use finite numbers or null. Each `area_quantiles` entry is `[q10,q25,q50,q75,q90]` in display units,
  ordered and finite, or null / five nulls for missing support. Supply transformed display values, not log-space fitting values.
  Provide these metrics when saved data support them; older counts-only payloads still render, with unavailable choices disabled.
- Optional `metric_axis_labels` overrides the metric-key labels (`count`, `area_quantiles`, `coverage`, `gap`, `clark_evans`).
  Defaults assume relative cell area, coverage fraction, gap in pixels and dimensionless Clark–Evans. Override for other units.
  `passage_metric_note` describes actual area normalization, tile pooling, quantile interpolation, spatial transformations and
  sampling cadence. The shaded bands represent cell distributions, not uncertainty in the fit. Do not invent unsaved samples.
- `fields`: selected records with `id`, `group`, `arm`, `passage`, `episode`, `passage_id`, `time` (days since seeding), `tile`,
  `raw_image`, `mask_image` (relative rendered image paths), `raw_path`, `mask_path`, `raw_sha256`, `mask_sha256` (provenance),
  `observed: {visible_cells}`, `simulations` (objects with `stage`, `rank` 1/2/3, `candidate`, `loss`, `time`, `image` relative path,
  `visible_cells`, `snapshot`, `cells_sha256`). Match time within the declared simulator step and preserve scale/crop. Missing
  optional representatives are omitted explicitly; list inaccessible requested fields in a linked manifest. Include every available
  imaged acquisition within each selected episode. The template groups by group/episode and stacks records in time order,
  showing raw/mask/all model stages together. Representative rank applies to all rows.
- `default_cutoff_percent`: 5 unless user changes it; controls remain independent per stage.
- `descriptions`: plain text `imageGeometry` (units, dimensions, scale bars), `imageSelection` (selection rule), `lossDefinition`
  (weights and support), `parameterTransforms` (log units/shifts). These are actual dataset conventions, not boilerplate promises.
- `protocol`: array of plain-text paragraphs describing confirmed grouping/conditions, model and fitting choices, sample
  support, rates/initialization, scoring, timesteps/domain, seeds and failures. Include actual bounds and parameter semantics in
  linked tables where needed. The template deliberately supplies no fitted protocol claims.
- `compute_usage`: display-label to value map, with elapsed time, CPU-hours, peak CPUs and stage breakdown or explicit unavailable
  entries; distinguish usage from allocation. `links`: `{label,href}` for relative provenance/configuration/outcome files copied
  with the report.

Stage IDs and group IDs together must form unambiguous best-map keys. The renderer validates score sums, winners and image
existence. The adapter validates scientific support, source hashes, time/scale agreement, inherited score identity and count
conversions. Browser checks should use at least one nonstandard group name and varying branch count to catch leaked assumptions.
