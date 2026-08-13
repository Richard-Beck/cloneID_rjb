---
editor_options:
  markdown:
    wrap: 72
---

# CloneID lineage growth analysis example

## Purpose

This workflow aims to demonstrate the level of analysis and critical thinking 
that is mandatory in order to achieve useful results when performing detailed
analyses of cloneID metadata, as well as providing some minimal tools/scaffolding
to reproduce similar analyses. Note in particular the careful integration 
and consideration of various forms of metadata. Note the willingness to formulate
and run with working hypotheses and reasonable assumptions based on incomplete
data! Note the lack of emphasis on mechanical scores and validations.  

## Contents

- [Purpose](#purpose)
- [Why examine metadata first?](#why-examine-metadata-before-fitted-parameters)
- [Metadata summary object](#metadata-summary-object)
- [Starting material and culture history](#starting-material-and-culture-history)
- [Sister branches](#sister-branches-reveal-the-experimental-context)
- [Recorded runs and seeding practice](#recorded-runs-and-seeding-practice)
- [Inter-episode timing](#inter-episode-timing-may-not-mean-what-its-labels-imply)
- [Observation cadence](#observation-cadence-reflects-the-working-week)
- [Expectations for growth analysis](#expectations-carried-into-the-growth-analysis)
- [Growth rate analysis](#growth-rate-analysis)
- [Model support](#what-the-model-screen-says-about-c-and-g1)
- [Long G1 passages](#why-did-g1-complete-so-few-passages)
- [Glucose-normalized interpretation](#a-glucose-normalized-interpretation)

## Why examine metadata before fitted parameters?

Growth parameters are produced by a culture and measurement process.
Reviewing that process first provides critical contextual clues that can
significantly enhance analytical depth, relevance, insight, and
meaningfulness.

## Metadata summary object

The companion bundle stored beside this reference under
`detailed-growth-analysis-example-bundle/` contains the prepared
episode, ancestry, branch, passaging, media, and fit views used below.
It also stores the assembled
[`metadata_summary.rds`](detailed-growth-analysis-example-bundle/data/metadata_summary.rds)
object:

``` r
library(dplyr)

skill <- ".codex/skills/cloneid-database-data"
bundle <- file.path(
  skill,
  "references",
  "detailed-growth-analysis-example-bundle"
)
metadata_summary <- readRDS(
  file.path(bundle, "data", "metadata_summary.rds")
)
```

The object is not a second metadata model. Its core is produced by
applying
[`summarise_growth_metadata()`](detailed-growth-analysis-example-bundle/R/growth_metadata_summary.R)
to the prepared one-row-per-episode span. Root, pre-span, and sister-arm
views are then attached as named fields by
[`analysis_operations.R`](detailed-growth-analysis-example-bundle/analysis_operations.R).
The underlying CSVs remain available when the episode-level or row-level
records need to be inspected directly. Tables in this example are
lightly formatted versions of these chained selections and summaries;
labels and units may therefore differ slightly from the stored columns.

| Object field | Question it helps answer |
|------------------------------------|------------------------------------|
| `overview`, `episode_timeline` | What is the span, and how do episode-level practices vary along it? |
| `root_context`, `pre_span_history` | What population entered the span, after how much prior culture and calendar time? |
| `media_runs`, `protocol_runs`, `owner_runs`, `count_processing_runs` | Which recorded contexts persist, and which are isolated events? |
| `inter_episode_durations`, `observation_cadence` | How does the recorded workflow relate to the laboratory calendar? |
| `graph_events`, `sister_branches` | Why did the lineage branch, and what happened to its sisters? |
| `comment_summary` | What experiment or event context was explicitly recorded? |

## Starting material and culture history

Root comments can provide provenance that is absent from the cell-line
name. Here, the row-level root is `MDA-231_2N_NLS_mCherry`, with the
comment:

> NLS-mCherry 2N cells, derived through homotypic fusion, from Andriy's
> lab

``` r
metadata_summary$root_context |>
  select(
    row_root_id,
    row_root_date,
    row_root_comment,
    episode_graph_root_id,
    analysis_span_start_date,
    analysis_span_start_episode_steps_from_episode_graph_root
  )

metadata_summary$pre_span_history |>
  select(
    relative_episode_position_to_span_start,
    episode_id,
    seeding_date,
    media_id,
    incoming_harvest_to_seed_days
  )
```

The analysis population did not enter the span immediately after that
record. Its episode graph begins on 2022-12-19 and contains five culture
episodes over 410 calendar days before the analyzed start on 2024-02-02.
All five pre-span episodes used media 53. The ancestry includes a
157-day storage-compatible hold, followed later by a 98-day
storage-compatible hold and a change from media 53 to media 19 at span
entry.

The first analyzed episode is followed by another 367.906-day
harvest-to-seeding hold and a change from media 19 to media 82:

| Culture interval | Episodes | Recorded medium | Relevant transition |
|------------------|-----------------:|------------------|------------------|
| Before the span | 5 | 53: McCoy's 5A + FBS | 157-day and 98-day storage-compatible holds |
| Position 1 | 1 | 19: RPMI-1640 + FBS + L-glutamine | entered after the 98-day hold |
| Positions 2–39 | 38 | 82: modified RPMI + dFBS + glucose/phosphates | position 2 entered after the 368-day hold |

Long harvest-to-seeding intervals are compatible with freezing and
recovery.

Every episode in the current span contains the tag `LTEE`, meaning
"long-term evolution experiment" in this context. The tag alone does not
say whether this lineage is a control or an experimental arm. The branch
context is more informative.

## Sister branches reveal the experimental context

The analyzed path branches at positions 2 and 12. A deterministic
follow-up traced every direct daughter for up to ten descendant episode
steps and recorded its media. The branch summaries are retained as a
named list in the companion object:

``` r
branch_daughters <- metadata_summary$sister_branches |>
  bind_rows(.id = "branch_key") |>
  filter(branch_parent_path_position == 2) |>
  select(
    initial_child_episode_id,
    media_ids_observed,
    maximum_episode_steps_observed
  )

branch_daughters
```

The `C_`, `G1_`, `G2_`, `O1_`, and other prefixes are discovered here,
in the direct-daughter IDs; they were not predefined analysis groups.
The companion begins with this prepared sister-arm view; the upstream
graph traversal that created it is not reproduced in the example
bundle.

At position 2, the population was split into 16 daughters:

| Daughter group | Media trajectory over available descendants |
|------------------------------------|------------------------------------|
| Selected `C` arm | media 82 for all 10 inspected steps |
| `P1`, `P2` | media 82, then media 76 through step 10 |
| `G1`, `G2` | media 83, then media 86, with one `G2` offshoot in media 82 and later media 88 |
| `O1`, `O2` | media 82, then media 101–104 as oxygen decreases |
| `PQ`, `Q`, `M`, `F` arms | short trajectories in media 24–27, with one `PQ` continuation in media 19 |
| `RPMI` arm | media 82 initially, then media 53 |

This is consistent with a designed panel of culture conditions. The `C`
name and its continued use of the parent medium suggest that it may be
the control/reference arm of the LTEE, while the other daughters enter
altered nutrient or oxygen conditions.

At position 12, the `C` population produced five daughters. The selected
`C_A11` continuation remains in media 82 for all ten inspected steps.
The other four daughters are named `PQ1redo`, `PQ2redo`, `Q1redo`, and
`Q2redo`; each has one recorded episode in media 82 and no recorded
descendant. This looks more like a failed or abandoned attempted restart
or allocation of experimental arms.

The working interpretation is that positions 3–39 follow a long-running,
same-media, control/reference-like arm. This makes gradual change under
serial propagation plausible, while deliberate media changes do not
explain variation within that interval.

## Recorded runs and seeding practice

The strict protocol mapping places the mapped episodes in the
`ltee_resource_deprivation` protocol family, supplying experimental
context beyond their individual media assignments.

The run views preserve where recorded contexts begin and end:

``` r
recorded_runs <- bind_rows(
  media = metadata_summary$media_runs,
  owner = metadata_summary$owner_runs,
  count_processing = metadata_summary$count_processing_runs,
  .id = "context"
) |>
  select(context, value, start, end, n)

recorded_runs
```

| View             | Positions | Recorded state                  |
|------------------|----------:|---------------------------------|
| Media            |         1 | 19                              |
|                  |      2–39 | 82                              |
| Recorded owner   |         1 | `cloneredesign`                 |
|                  |      2–28 | `jackson`                       |
|                  |        29 | `vural`                         |
|                  |     30–39 | `jackson`                       |
| Count processing |         1 | corrected near original         |
|                  |         2 | corrected differs from original |
|                  |      3–19 | corrected near original         |
|                  |     20–39 | corrected differs from original |

The position-1-to-2 boundary combines recovery, media, owner, and
seeding changes, so none can be isolated there. The owner change at
position 29 lasts only one episode; it is relevant to a local anomaly,
but not a sustained later trend. Recorded owner is an account and should
not be assumed to identify the person who performed every wet-lab step.

The count-processing transition at position 20 is persistent and occurs
without a recorded media or owner change. The median corrected/raw
seeding-count ratio is 1.00 at positions 3–19 and 0.65 at positions
20–39. Corrected and original counts may be alternative processing of
the same images, with no algorithm version recorded. This boundary is
measurement-process context, not an independent validation series or
evidence that either count is biologically correct.

The episode timeline also shows large changes in selected seeding
abundance:

``` r
seeding_regimes <- metadata_summary$episode_timeline |>
  mutate(
    positions = cut(
      path_position,
      breaks = c(0, 1, 2, 3, 12, 22, 25, 39),
      labels = c(
        "1", "2", "3", "4–12", "13–22", "23–25", "26–39"
      )
    )
  ) |>
  summarise(
    median_selected_seeding_count = median(seeding_selected_count),
    .by = positions
  )
```

| Positions | Median selected seeding count | Pattern |
|---:|---:|----|
| 1 | 4.42 M | post-hold media-19 episode |
| 2 | 1.34 M | post-year-hold media-82 episode |
| 3 | 1.54 M | first selected `C` daughter |
| 4–12 | 0.492 M | persistent lower-seeding interval |
| 13–22 | 0.413 M | similar lower-seeding interval |
| 23–25 | 1.01 M | temporary higher-seeding interval |
| 26–39 | 0.574 M | return toward the sub-million range |

seeding abundance changes highlight potential differences in culture
protocol, perhaps: delayed imaging of the first seeded timepoint, adding
more cells to the flask, or "better" cell handling practices leading to
more cells attaching, or more carefully optimized microscope settings.
If the passage 23–25 temporary higher-seeding interval also overlaps
with other metadata detected breakpoints/covariates, the overlap may
help to strengthen, weaken, or refine any of those ideas.

## Inter-episode timing may not mean what its labels imply

The 38 within-span terminal-observation-to-child-seeding intervals are:

``` r
duration_views <- metadata_summary$inter_episode_durations

duration_views$summary
duration_views$weekday_transitions
duration_views$seeding_counts
```

| Duration bin   | Edges | Percent |
|----------------|------:|--------:|
| `≤1 day`       |    11 |   28.9% |
| `1 day–1 week` |    26 |   68.4% |
| `>1 year`      |     1 |    2.6% |

The weekday transitions reveal two dominant routines that the bins alone
hide:

| Duration bin   | Parent terminal observation → child `seeding` record | Edges |
|------------------|-------------------------------------|-----------------:|
| `≤1 day`       | Friday → Friday                                      |    11 |
| `1 day–1 week` | Monday → Wednesday                                   |    20 |
| `1 day–1 week` | Friday/Saturday → Monday                             |     4 |
| `1 day–1 week` | Friday → Tuesday                                     |     1 |
| `1 day–1 week` | Monday → Thursday                                    |     1 |
| `>1 year`      | Monday → Friday                                      |     1 |

Since harvest-\>seeding edges reflect passaging of populations to new
flasks, it is natural to wonder what underlying protocol/reality
generates the two dominant routines, and what effect that might have on
the data. A Friday → Friday edge implies
imaging-\>passaging-\>re-imaging all on the same day, whereas e.g a
Monday → Wednesday allows for possibility of cells being seeded and
allowed to attach/grow overnight before imaging on Wednesday - likely
resulting in more cells counted and higher image quality. Accordingly,
in this example trajectory child seeding abundance *is* associated with
the duration bin:

| Incoming-duration bin | Children | Median selected seeding count | IQR |
|------------------|-----------------:|-----------------:|-----------------:|
| `≤1 day` | 11 | 403,869 | 391,950–494,029 |
| `1 day–1 week` | 26 | 528,326 | 458,805–682,587 |
| `>1 year` | 1 | 1,338,994 | — |

The common multi-day group has a 31% higher median, but all `≤1 day`
children were seeded on Friday and all `1 day–1 week` children were
seeded Monday–Thursday.

Practical follow-ups are:

1.  Ask the wet-lab team for a protocol clarification.
2.  Inspect available seeding images for attachment, focus, cell
    morphology, and segmentation differences between the calendar
    groups.
3.  Treat exclusion of Friday versus Monday–Thursday episodes as a
    sensitivity analysis, recognizing that it also removes distinct
    portions of the laboratory schedule.
4.  Where pooled models remain estimable, test whether conclusions
    persist when observations labelled `seeding` are withheld.

## Observation cadence reflects the working week

The observation schedule is strongly calendar-structured:

``` r
metadata_summary$observation_cadence |>
  arrange(seeding_weekday, cadence_signature)
```

| Seeding weekday | Observed day signatures (episodes) |
|-----------------|------------------------------------|
| Monday          | `0,2,4` (4)                        |
| Tuesday         | `0,1,3` (1)                        |
| Wednesday       | `0,2` (11), `0,2,5` (8), `0,3` (1) |
| Thursday        | `0,1,4` (1)                        |
| Friday          | `0,3` (13)                         |

The most natural explanation for the Friday day-0/day-3 pattern is that
staff do not routinely image over the weekend. More generally, cadence
looks like realized culture practice rather than an independently
assigned sampling design. Day of week, staff availability, attachment,
confluence, workload, and realized growth may all contribute.

## Expectations carried into the growth analysis

The metadata support a few provisional expectations:

-   Positions 1–2 are recovery- and media-associated and should not be
    used to identify a single causal effect.
-   Positions 3–39 appear to be a continuing, same-media,
    control/reference-like LTEE arm. Sister arms are natural candidates
    to bundle for comparative analysis.
-   Variation near position 20 has a persistent measurement-processing
    alternative; positions 23–25 and 31 have conspicuous
    seeding-practice alternatives; position 29 has a local
    recorded-owner alternative.

## Growth rate analysis

We took the `G1` sister arm forward as a comparison. A fuller analysis
would include all suitable sisters, especially the near-replicate `G2`
arm. The selected `C` and `G1` arms were seeded from the same parent on
2025-02-12, only 12 minutes apart, and both began at recorded passage
11. They then experienced different media:

``` r
media <- read.csv(
  file.path(bundle, "data", "media_view.csv")
) |>
  filter(media_id %in% c(82, 83, 86, 88))

span_episodes <- read.csv(
  file.path(bundle, "data", "analysis_span_episode_ids.csv")
)

arm_calendar <- span_episodes |>
  filter(arm == "G1" | (arm == "C" & path_position >= 3)) |>
  summarise(
    n_episodes = n(),
    first_seeding = min(substr(seeding_date, 1, 10)),
    last_observation = max(substr(last_harvest_date, 1, 10)),
    .by = arm
  )
```

| Arm  | Media trajectory      |    Glucose concentration |
|------|-----------------------|-------------------------:|
| `C`  | 82 throughout         | 11.1 mM, with phosphates |
| `G1` | 83 for one episode    |                     3 mM |
|      | 86 for eight episodes |                   1.5 mM |
|      | 88 for four episodes  |                  0.75 mM |

The `C` arm completed 37 episodes between 2025-02-12 and 2025-08-08.
`G1` completed only 13 episodes and continued until 2025-08-25. Thus `C`
experienced many more passages than `G1` over a comparable calendar
interval. Passage number and calendar date cannot be treated as
interchangeable after the split.

### What the model screen says about `C` and `G1`

We crossed exponential and logistic mean growth with Normal and
mean-preserving Lognormal errors. Each candidate was fit independently,
in rolling windows of two, three, and five episodes, and in a joint
latent-state model. The screen must be read with the metadata because
the arms expose different parts of the growth curve:

``` r
fit_records <- read.csv(
  file.path(bundle, "data", "model_fit_records.csv")
)

fit_support_status <- fit_records |>
  count(
    arm,
    strategy,
    candidate_model,
    fit_status,
    criterion_eligible,
    name = "n_fits"
  )

fit_delta_aic <- fit_records |>
  filter(
    is.finite(AIC),
    is.na(criterion_eligible) | criterion_eligible
  ) |>
  mutate(
    delta_AIC = AIC - min(AIC),
    .by = c(arm, strategy, fit_unit_id)
  )

joint_fit_diagnostics <- read.csv(
  file.path(bundle, "data", "joint_fit_summary.csv")
) |>
  select(
    arm,
    candidate_model,
    fit_status,
    sigma_r_innovation,
    sigma_logK_innovation,
    boundary_parameters
  )
```

| Feature | `C` analysis span | `G1` arm |
|------------------|-----------------------------------|-------------------|
| Episodes; observations | 39; 92 | 13; 82 |
| Within-episode follow-up | Two or three observations over 0–5 days | Two to eighteen observations over 0–40 days |
| Independent Logistic + Lognormal support | 0 of 39 episodes | 8 of 13 episodes |
| Rolling Logistic + Lognormal support | 80 of 110 windows | 31 of 32 windows |
| Joint Logistic + Lognormal improvement over exponential | 107.9 AIC units; converged | 69.7 AIC units; `r` innovation on its lower boundary |

The absence of independent logistic support in `C` is a direct
consequence of its realized culture and observation routine. Cultures
were usually passaged within five days, with too few observations for
one episode to define curvature. Logistic support appears only after
pooling information across episodes. In `G1`, the two long cultures
provide direct information about high-density behavior, but contribute
36 of 82 observations and therefore exert unusual leverage on pooled
fits.

Both screens favor density-dependent behavior once episodes are pooled,
but they do so for different reasons. The approximately 10-million `C`
carrying-capacity estimate is reconstructed from many short passages.
The early `G1` estimate is visible within long cultures, but, as
considered below, may summarize a repeatedly refed operating state
rather than one approach to equilibrium.

The model-derived arm contrast is nevertheless clear. Over the shared
passage range 11–23, rolling Lognormal logistic fits put `r` around
1.13–1.20/day in `C` and 0.96–1.11/day in `G1`. Joint median `K` is
approximately 10.3 million in `C` and 3.8 million in `G1`; rolling-five
fits give approximately 10.0 and 3.7 million. Median logistic `N_init`
is approximately 0.49 million in both arms. The primary cross-arm
contrast is therefore high-density abundance, not initial abundance, and
the modeled low-density rates differ much less than the cultures'
passage frequency.

The C change screen also showed how metadata variables can manifest in
model estimated parameters. The position-20 count-processing boundary
produces only a weak `N_init` increase in Normal-error rolling fits and
is absent from the admitted joint Lognormal trajectories. In contrast,
the temporary high-seeding regime at positions 23–25 overlaps the most
recurrent parameter region: `r` changes around position 25 and `K` rises
around 25–27. The isolated owner change at position 29 and the seeding
anomaly at position 31 do not coincide with similarly recurrent
boundaries. A later `r` signal around 35 is metadata-light but appears
in only two model/strategy series.

The C lineage therefore contains fitted changes in parameter values, but
its strongest one is entangled with seeding and episode-duration
practice and has no obvious triggering biological event. In `G1`, the
major recorded interventions are glucose changes, while culture duration
and likely feeding practice also change.

A fitted `r` is biologically interesting only when the relevant growth
process can reasonably be represented by a constant rate over the fitted
interval. Logistic growth can separate modeled low-density growth (`r`)
from a high-density scale (`K`), but rolling and joint fits borrow
information and yield correlated episode estimates. In `G1`, the
lower-bound joint `r` innovation means that its nearly flat trajectory
is regularization, not evidence that the biological rate was constant.

### Why did `G1` complete so few passages?

The calendar comparison raised the obvious question: why did `G1`
complete 13 episodes while `C` completed 37? Inspection of G1 episode
duration and observation count immediately identified two exceptional
cultures. `G1_A2` and `G1_A4`, at recorded passages 12 and 14, were each
cultured in medium 86: modified RPMI with dFBS and 1.5 mM glucose.
`G1_A2` contains 18 observations through day 38; `G1_A4` contains 18
through day 40. Together they account for 36 of the arm's 82
observations.

``` r
g1_observations <- read.csv(
  file.path(bundle, "data", "g1_growth_observations.csv")
)

g1_episode_followup <- g1_observations |>
  summarise(
    n_observations = n(),
    last_observed_day = max(calendar_day),
    .by = c(episode_id, path_position, passage_num, seeding_media_id)
  ) |>
  arrange(desc(last_observed_day))
```

Both reach several million cells within five days and then fluctuate for
another month. From day 6 onward, their mean counts are almost
identical—3.60 million in each episode—even though individual
observations range from 1.38 to 6.12 million in `A2` and 2.06 to 6.62
million in `A4`. Lognormal logistic fits estimate `K = 3.59` and 3.67
million, respectively. Those `K` values describe the center of the
high-density observations much better than an intrinsic maximum: counts
repeatedly move both below and above them.

These oscillating high-density counts raised the possibility that the
long cultures had been refed. The database contains no recorded feeding
events, so we first looked for periodicity rather than assuming a
schedule. After day 6, each episode was observed five times on Monday,
Wednesday, and Friday. In `A4`, Wednesday counts average 4.74 million,
compared with 2.98 million on Monday and 3.09 million on Friday, and a
detrended period scan peaks at 7.16 days. The weekday pattern is weaker
in `A2`, but its long series also oscillates rather than settling.

``` r
passaging_rows <- read.csv(
  file.path(bundle, "data", "passaging_excerpt.csv")
)

recorded_feeding_rows <- passaging_rows |>
  filter(if_any(starts_with("feeding"), ~ !is.na(.x)))

periodicity <- read.csv(
  file.path(bundle, "data", "g1_periodicity_summary.csv")
) |>
  filter(series %in% c("G1_A2", "G1_A4"))
```

We therefore infer weekly refeeding, probably around the Monday
observation, as the working culture model. Other explanations remain
possible, but this model jointly explains why the episodes continued for
forty days and why abundance recurs on a seven-day schedule. Under it,
logistic `r` describes primarily the initial low-density rise, not a
constant forty-day rate, and `K` describes an operating abundance under
repeated glucose renewal rather than an intrinsic maximum.

The simplest protocol model is that feed volume and exchange fraction
were unchanged: `G1` uses the same flask code throughout, and the
metadata record no intervention that would motivate changing either. A
condition-responsive partial exchange is possible, but there is no
positive evidence for it. The interval requires more thought. Feeding
every `N` days would eventually require weekend work unless `N = 7`; a
fixed weekday schedule is also easier to maintain than a rotating one.
Thus a weekly fixed-day schedule is the most economical reading of the
data, although feeding in response to confluence or appearance remains a
plausible alternative.

``` r
feed_pairs <- read.csv(
  file.path(bundle, "data", "g1_monday_wednesday_pair_view.csv")
)

feed_phase_summary <- feed_pairs |>
  summarise(
    n_pairs = n(),
    mean_monday_million = mean(monday_count_million),
    mean_wednesday_million = mean(wednesday_count_million),
    mean_change_per_mM =
      mean(count_change_over_glucose_million_per_mM),
    .by = comparison_group
  )
```

### A glucose-normalized interpretation

If this high-density scale is glucose-limited, nominal concentration is
only one component of exposure. Let `C` be glucose concentration, `V`
the culture volume, `q` the fraction exchanged at each feed, and `T` the
feed interval. Glucose supply per day is proportional to:

``` text
C × V × q / T
```

Under the working assumptions that `V`, `q`, and `T` did not change,
`K/C` preserves relative differences in abundance per glucose supply
rate:

``` r
g1_parameters <- read.csv(
  file.path(bundle, "data", "g1_joint_parameter_view.csv")
)

glucose_normalized_K <- g1_parameters |>
  summarise(
    first_position = min(path_position),
    glucose_mM = first(glucose_mM),
    median_joint_K_million = median(K_million),
    median_K_over_glucose =
      median(K_over_glucose_million_per_mM),
    .by = episode_group
  ) |>
  arrange(first_position)
```

| G1 interval    | Glucose | Median joint `K` | Median `K/C` |
|----------------|--------:|-----------------:|-------------:|
| `A1` entry     | 3.00 mM |           7.34 M |    2.45 M/mM |
| `A2–A5`, early | 1.50 mM |           3.69 M |    2.46 M/mM |
| `A6–A9`, later | 1.50 mM |           6.96 M |    4.64 M/mM |
| `A10–A13`      | 0.75 mM |           3.28 M |    4.38 M/mM |

`A1` contains only two observations, so its `K` is mostly borrowed from
the joint model. More generally, `K/C` is a conditional proxy rather
than an absolute cellular yield. Nevertheless, the result is striking.
During continued culture in 1.5 mM glucose, median `K/C` rises from 2.46
to 4.64 M/mM, an 89% increase. When glucose is then halved, absolute `K`
falls from 6.96 to 3.28 million—approximately in proportion to the media
change—while `K/C` changes by only 6%, from 4.64 to 4.38 M/mM.

That stability across the 1.5→0.75 mM boundary is precisely what the toy
normalization predicts if the later cellular state is retained while
glucose supply becomes the new abundance constraint. Media 86 and 88
have the same recorded base medium, serum, antibiotics, oxygen
condition, and flask code; glucose is the listed difference. Together,
the phase-matched post-feed response, rising fitted `K` within the 1.5
mM run, and preservation of `K/C` after the glucose transition form a
coherent picture of adaptation or conditioning along `G1` toward
supporting more cells per unit glucose supply.
