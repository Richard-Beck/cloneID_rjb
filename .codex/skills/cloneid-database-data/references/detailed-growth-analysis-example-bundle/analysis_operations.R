library(dplyr)

script_file <- tryCatch(
  normalizePath(sys.frame(1)$ofile, mustWork = TRUE),
  error = function(...) NA_character_
)
if (is.na(script_file)) {
  file_arg <- grep("^--file=", commandArgs(), value = TRUE)
  if (length(file_arg) != 1) {
    stop("Cannot locate analysis_operations.R")
  }
  script_file <- normalizePath(sub("^--file=", "", file_arg))
}
bundle_dir <- dirname(script_file)

source(file.path(bundle_dir, "R", "growth_metadata_summary.R"))

read_view <- function(name) {
  read.csv(
    file.path(bundle_dir, "data", name),
    check.names = FALSE,
    na.strings = c("", "NA")
  )
}

# One row per C episode: runs, duration bins, graph events, and comments.
c_episodes <- read_view("c_episode_metadata_view.csv")
metadata_core <- summarise_growth_metadata(c_episodes)

# Root history and sister arms remain independent, inspectable views.
c_context <- list(
  root = read_view("c_root_context.csv"),
  pre_span_ancestry = read_view("c_pre_span_ancestry.csv"),
  sister_arms = read_view("c_branch_sister_arms.csv")
)

# The cadence table is a direct view, not an inferred culture protocol.
c_observation_cadence <- c_episodes |>
  mutate(
    cadence_signature = if_else(
      n_observations <= 3,
      observation_day_signature,
      "4+ observations"
    )
  ) |>
  count(
    seeding_weekday,
    cadence_signature,
    name = "n_episodes"
  ) |>
  arrange(seeding_weekday, cadence_signature)

duration_edges <- c_episodes |>
  filter(!is.na(duration_bin))

duration_weekday_transitions <- duration_edges |>
  count(
    duration_bin,
    incoming_terminal_observation_weekday,
    seeding_weekday,
    name = "n_edges"
  )

duration_seeding_summary <- duration_edges |>
  summarise(
    n_children = n(),
    median_seeding_count = median(seeding_selected_count),
    q25_seeding_count = quantile(seeding_selected_count, 0.25),
    q75_seeding_count = quantile(seeding_selected_count, 0.75),
    .by = duration_bin
  )

metadata_summary <- list(
  overview = metadata_core$overview,
  episode_timeline = metadata_core$episodes,
  root_context = c_context$root,
  pre_span_history = c_context$pre_span_ancestry,
  media_runs = metadata_core$media_runs,
  protocol_runs = metadata_core$protocol_runs,
  owner_runs = metadata_core$owner_runs,
  count_processing_runs = metadata_core$count_processing_runs,
  inter_episode_durations = list(
    summary = metadata_core$duration_summary,
    runs = metadata_core$duration_runs,
    weekday_transitions = duration_weekday_transitions,
    seeding_counts = duration_seeding_summary
  ),
  observation_cadence = c_observation_cadence,
  graph_events = metadata_core$graph_events,
  sister_branches = split(
    c_context$sister_arms,
    c_context$sister_arms$branch_parent_episode_id
  ),
  comment_summary = metadata_core$comments
)

# The compact span manifest supplies the calendar comparison between
# the C continuation after the split and the G1 sister arm.
analysis_span_episodes <- read_view("analysis_span_episode_ids.csv")

arm_calendar_summary <- analysis_span_episodes |>
  filter(arm == "G1" | (arm == "C" & path_position >= 3)) |>
  summarise(
    n_episodes = n(),
    first_seeding_date = min(substr(seeding_date, 1, 10)),
    last_observation_date = max(substr(last_harvest_date, 1, 10)),
    passage_min = min(passage_num),
    passage_max = max(passage_num),
    .by = arm
  )

# Media are already reduced to the fields used in the example.
media <- read_view("media_view.csv")
experimental_media <- media |>
  filter(media_id %in% c(82, 83, 86, 88))

# Retain the passaging rows themselves for questions that episode
# summaries cannot answer.
passaging_rows <- read_view("passaging_excerpt.csv")

g1_long_episode_rows <- passaging_rows |>
  filter(
    episode_id %in% c(
      "MDA-MB-231_G1_A2_seed",
      "MDA-MB-231_G1_A4_seed"
    )
  ) |>
  select(
    episode_id, id, event, date, calendar_day,
    selected_count, count_source, flask, owner, comment
  )

recorded_feeding_rows <- passaging_rows |>
  filter(if_any(starts_with("feeding"), ~ !is.na(.x)))

# Fit support and AIC are read from fitted-result records. Delta AIC is
# calculated only within an arm, strategy, and fit target.
fit_records <- read_view("model_fit_records.csv")

fit_support_status <- fit_records |>
  count(
    arm, strategy, candidate_model, fit_status,
    criterion_eligible, name = "n_fits"
  )

fit_delta_aic <- fit_records |>
  filter(
    is.finite(AIC),
    is.na(criterion_eligible) | criterion_eligible
  ) |>
  mutate(
    delta_AIC = AIC - min(AIC),
    .by = c(arm, strategy, fit_unit_id)
  ) |>
  arrange(arm, strategy, fit_unit_id, delta_AIC)

# Joint hyperparameters and boundary fields retain the diagnostics behind
# generic diagnostic_warning statuses.
joint_fit_summary <- read_view("joint_fit_summary.csv")

joint_fit_diagnostics <- joint_fit_summary |>
  select(
    arm, candidate_model, fit_status, message,
    sigma_r_innovation, sigma_logK_innovation,
    boundary_parameters, max_abs_gradient, pd_hessian
  )

# Episode-level joint parameters support direct arm-level summaries.
joint_parameters <- read_view(
  "joint_logistic_lognormal_parameters.csv"
)

joint_parameter_arm_summary <- joint_parameters |>
  summarise(
    n_episodes = n(),
    median_r_per_day = median(r_per_day),
    median_K_million = median(K) / 1e6,
    median_N_init_million = median(N_init) / 1e6,
    .by = arm
  )

# The first three observations expose the actual schedules behind the
# compact A1–A13 tables in the worked example.
g1_observations <- read_view("g1_growth_observations.csv")

g1_first_three_observations <- g1_observations |>
  arrange(path_position, calendar_day, precise_day) |>
  slice_head(n = 3, by = episode_id) |>
  select(
    episode_id, path_position, passage_num, seeding_media_id,
    observation_calendar_date, calendar_day, precise_day,
    selected_count, count_source
  )

# Joint Logistic + Lognormal episode parameters are already joined to
# glucose concentration in this stored view.
g1_parameters <- read_view("g1_joint_parameter_view.csv")

g1_parameter_groups <- g1_parameters |>
  summarise(
    first_position = min(path_position),
    n_episodes = n(),
    glucose_mM = first(glucose_mM),
    median_r_per_day = median(r_per_day),
    median_K_million = median(K_million),
    median_N_init_million = median(N_init / 1e6),
    median_K_over_glucose = median(K_over_glucose_million_per_mM),
    .by = episode_group
  ) |>
  arrange(first_position)

# These are stored Monday-to-Wednesday observation pairs; only their
# group summaries are calculated here.
g1_feed_pairs <- read_view("g1_monday_wednesday_pair_view.csv")

g1_feed_phase_summary <- g1_feed_pairs |>
  summarise(
    n_pairs = n(),
    glucose_mM = first(glucose_mM),
    mean_monday_million = mean(monday_count_million),
    mean_wednesday_million = mean(wednesday_count_million),
    wednesday_over_monday =
      mean(wednesday_count_million) / mean(monday_count_million),
    mean_change_per_mM =
      mean(count_change_over_glucose_million_per_mM),
    .by = comparison_group
  )

# Stored outputs from the A2/A4 periodicity screen.
g1_periodicity <- read_view("g1_periodicity_summary.csv")
g1_weekday_periodicity <- read_view("g1_weekday_periodicity_tests.csv")

analysis_views <- list(
  metadata_summary = metadata_summary,
  arm_calendar_summary = arm_calendar_summary,
  experimental_media = experimental_media,
  g1_long_episode_rows = g1_long_episode_rows,
  recorded_feeding_rows = recorded_feeding_rows,
  fit_support_status = fit_support_status,
  fit_delta_aic = fit_delta_aic,
  joint_fit_diagnostics = joint_fit_diagnostics,
  joint_parameter_arm_summary = joint_parameter_arm_summary,
  g1_first_three_observations = g1_first_three_observations,
  g1_parameter_groups = g1_parameter_groups,
  g1_feed_phase_summary = g1_feed_phase_summary,
  g1_periodicity = g1_periodicity,
  g1_weekday_periodicity = g1_weekday_periodicity
)
