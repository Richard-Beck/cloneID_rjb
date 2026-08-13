# Growth-fitting code reference

## Overview

Useful when the task is to estimate growth within individual culture episodes, compare local intervals along a coherent lineage span, or
describe passage-to-passage parameter change without assuming that growth parameters remain constant or follow a predetermined adaptation
curve.

These functions operate on prepared observation tables. Episode assignment, lineage and coherent-span construction, count selection, and
metadata QC remain upstream cloneID database tasks. Follow the count semantics and selection guidance in the
[cleaned metadata reference](cleaned-metadata-reference.md).

Depending on the question, the outputs may be useful for:

- comparing supported exponential and logistic models under Normal and Lognormal observation errors;
- plotting local or smoothed growth-rate and carrying-capacity estimates along a lineage;
- examining whether parameter changes coincide with media changes or other recorded events;
- identifying weakly supported fits, unusual residuals, or episodes that merit closer review; or
- supplying fitted values and parameter estimates to downstream visualizations or comparative analyses.

These are possible downstream uses rather than prescribed interpretations. Overlapping windows are correlated, latent-state estimates are
partially informed by neighboring episodes, and finite carrying-capacity estimates need not imply that saturation was well observed.

## Contents

- [Supplied files](#supplied-files)
- [Shared model conventions](#shared-model-conventions)
- [`fit_episode_growth_models()`](#fit_episode_growth_models)
- [`fit_finite_growth_window()`](#fit_finite_growth_window)
- [`fit_rolling_finite_windows()`](#fit_rolling_finite_windows)
- [`fit_joint_state_lineage()`](#fit_joint_state_lineage)

## Supplied files

- [`growth_likelihood_models.R`](../scripts/growthfit/growth_likelihood_models.R): independent-episode, finite-window, and rolling-window
  likelihood fits.
- [`joint_state_growth_models.R`](../scripts/growthfit/joint_state_growth_models.R): joint latent-state lineage interface and TMB result
  extraction.
- [`joint_state_model.cpp`](../scripts/growthfit/joint_state_model.cpp): TMB likelihood template used by the joint model.

Source the R files in this order:

```r
source(".codex/skills/cloneid-database-data/scripts/growthfit/growth_likelihood_models.R")
source(".codex/skills/cloneid-database-data/scripts/growthfit/joint_state_growth_models.R")
```

The second file checks that likelihood API version 1.0.0 is loaded. Its joint fitter requires the `TMB` R package and compiles the sibling C++
template in the user's R cache; it does not write compiled artifacts into the supplied folder.

## Shared model conventions

All four public fitters expect finite positive abundances and nonnegative integer calendar days from each episode's seeding calendar date. Count
selection is performed before fitting according to the [cleaned metadata reference](cleaned-metadata-reference.md).

The four candidate combinations are exponential or logistic mean growth crossed with Normal or mean-preserving Lognormal observation error:

```text
exponential: mu_e(d) = N0_e exp(r_e d)
logistic:    mu_e(d) = K_e / (1 + A_e exp(-r_e d))
```

The Lognormal model uses `meanlog = log(mu) - sigma_log^2 / 2`, so `mu = E[Y]`. Its original-count likelihood includes the Jacobian and is
comparable with the Normal likelihood when both candidates use the same observations.

## `fit_episode_growth_models()`

```r
fit_episode_growth_models(
  episode_data,
  day_col = "calendar_day",
  count_col = "selected_count",
  episode_id_col = NULL
)
```

Fits all four candidates to exactly one episode.

Input contract:

- `episode_data` is a nonempty data frame; rows are not silently removed.
- `day_col` is numeric, finite, whole, and nonnegative.
- `count_col` is numeric, finite, and strictly positive.
- If supplied, `episode_id_col` is complete and contains exactly one unique nonempty value. When omitted, the result's `episode_id` is `NA`.

The return value is a four-row data frame, one row per candidate. It contains model identity and eligibility; `N0`, `K`, `A`, `r_per_day`,
doubling time, and predicted day-zero mean; observation dispersion and original-count RMSE; log likelihood, AIC, BIC, ranks, deltas, and
selection flags; and optimizer, residual-degree, variance-collapse, and boundary diagnostics.

Exponential candidates require more than two observations on at least two distinct days. Logistic candidates require more than three
observations on at least three distinct days. Counts of fitted parameters include dispersion (`k = 3` and `k = 4`, respectively).
Unsupported, saturated, nonconverged, variance-collapsed, boundary, or nonfinite candidates remain in the table but are excluded from ranking.
Numerically tied eligible candidates may both be selected.

## `fit_finite_growth_window()`

```r
fit_finite_growth_window(
  data,
  episode_col = "episode_id",
  day_col = "calendar_day",
  count_col = "selected_count",
  observation_id_col = NULL
)
```

Fits all four candidates to one supplied group of episodes. Exponential candidates give each episode its own `N0` and share `r`; logistic
candidates give each episode its own `A` and share `r` and `K`. Dispersion is shared within the window.

Input contract:

- `data` is nonempty and has complete, nonempty episode IDs, valid calendar days, and finite positive counts.
- `observation_id_col` is optional. If supplied, it must be complete, nonempty, and unique; otherwise row-based IDs are generated.

Returns a list of three data frames:

- `candidate_fits`: four candidate rows with support/status, parameter counts, shared parameters, likelihood criteria, selections, RMSE, and
  optimizer diagnostics;
- `episode_coefficients`: one row per candidate and episode with `N0` or `A`, predicted initial mean, and shared `r`/`K`;
- `fitted_observations`: one row per candidate and observation with observed count, fitted mean, and residual.

For `E` episodes, the parameter count including dispersion is `E + 2` for exponential and `E + 3` for logistic candidates. Implemented support
checks require observations to outnumber mean parameters and at least one episode to contain two distinct days. Nonconvergence, nonpositive or
collapsed dispersion, boundary mean parameters, and nonfinite criteria also make a candidate ineligible; ineligible rows remain in the outputs.

## `fit_rolling_finite_windows()`

```r
fit_rolling_finite_windows(
  observations,
  episode_order,
  group_sizes = c(2L, 3L, 5L),
  episode_col = "episode_id",
  day_col = "calendar_day",
  count_col = "selected_count",
  observation_id_col = NULL,
  span_col = "coherent_span_id",
  position_col = "span_position",
  progress = interactive()
)
```

Constructs every stride-one window of each requested size separately within each supplied span, then calls
`fit_finite_growth_window()` for every window. `observations` follows the finite-window input contract and must include every episode used by a
generated window. `episode_order` must contain complete episode and span IDs, unique episode IDs, and finite within-span positions in the named
columns. Group sizes are positive integers; sizes longer than a span are skipped. `progress = TRUE` emits periodic messages.

Returns four data frames:

- `windows`: exact window membership, span, group size, order, and start/end positions;
- `candidate_fits`, `episode_coefficients`, and `fitted_observations`: the corresponding finite-window tables prefixed with window metadata.

AIC/BIC ranks are meaningful only among candidates fitted to the same window. Overlapping windows reuse observations and are correlated local
summaries, not independent replicates. Because windows are constructed within `span_col`, the caller controls where parameter sharing stops.

## `fit_joint_state_lineage()`

```r
fit_joint_state_lineage(
  lineage_data,
  span_col = "span_id",
  dll_info = compile_joint_state_model()
)
```

Fits all four joint candidates separately to every supplied span and combines the results. The default `dll_info` lazily compiles or loads the
supplied TMB template; an already prepared DLL-info list may be passed to reuse a compilation.

Required columns are:

- `episode_id`: complete, nonempty episode identifier;
- `path_position`: finite serial position, unique across episodes within a span, with one position per episode;
- `calendar_day`: finite, nonnegative whole day;
- `selected_count`: finite positive abundance;
- `span_col`: span identifier used to split the lineage.

Each span must contain at least two episodes, and every episode at least two observations. An episode observed on only one distinct day is
allowed; its growth-rate state is then informed by neighboring states rather than direct within-episode change. Spans are ordered by minimum
`path_position` and receive independent latent processes.

The joint exponential model has a fixed episode-specific `log(N0)` and a latent episode-specific `r`. The logistic model has fixed `log(A)`
and latent `r` and `log(K)`. Latent states follow proper Gaussian random walks by episode step. The first state is Normal around an estimated
initial mean with the innovation SD; subsequent states are Normal around the preceding state. The implementation does not scale innovations by
elapsed calendar time. TMB integrates the latent states with a Laplace approximation.

Returns six data frames, row-bound across candidates and spans:

- `summary`: marginal log likelihood, parameter count, AIC/BIC ranks and deltas, observation and innovation scales, and fit diagnostics;
- `states`: episode-level `r` and, for logistic candidates, `logK`/`K`, with local Hessian-based intervals;
- `intercepts`: fixed episode intercepts and implied day-zero means;
- `fitted`: conditional fitted means, residuals, standardized residuals, and conditional observation log likelihoods;
- `hyperparameters`: initial-state means, innovation SDs, and observation dispersion;
- `diagnostics`: optimizer-start counts, gradient, Hessian, and boundary information.

The marginal parameter count excludes integrated state realizations: it is `E + 3` for exponential and `E + 5` for logistic candidates. BIC
uses the number of observation rows. A joint candidate is labeled `converged` only when the outer optimizer converges, the reported Hessian is
positive definite, the maximum absolute gradient is below `1e-2`, and no fixed parameter is near a bound. Other finite fits are labeled
`diagnostic_warning`; construction or optimization failures return a failed summary row and empty detail tables.

The current span comparison ranks every candidate with finite AIC and BIC, including `diagnostic_warning` candidates. Always interpret ranks
with the gradient, Hessian, and boundary fields. When observed trajectories do not approach a plateau, logistic `K` can be weakly identified
and the logistic curve can approximate an exponential; inspect `K` intervals and diagnostics rather than treating a finite estimate as evidence
of saturation.
