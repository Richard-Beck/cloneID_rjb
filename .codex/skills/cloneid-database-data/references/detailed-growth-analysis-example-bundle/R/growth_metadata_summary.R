library(dplyr)

episode_runs <- function(x, variable) {
  x |>
    mutate(
      value = {{ variable }},
      run = consecutive_id(value)
    ) |>
    summarise(
      value = first(value),
      start = first(path_position),
      end = last(path_position),
      n = n(),
      first_episode = first(episode_id),
      last_episode = last(episode_id),
      .by = run
    )
}

summarise_growth_metadata <- function(x) {
  required <- c(
    "analysis_span_id", "episode_id", "path_position",
    "seeding_date", "passage_num", "n_observations",
    "media_id", "protocol_id", "recorded_owner", "count_processing_state",
    "incoming_harvest_to_seed_days", "duration_bin",
    "is_branch_point", "is_multiparent", "episode_child_count",
    "episode_comments"
  )

  stopifnot(
    is.data.frame(x),
    all(required %in% names(x)),
    nrow(x) > 0,
    !anyNA(x$episode_id),
    !anyDuplicated(x$episode_id),
    !anyNA(x$path_position),
    !anyDuplicated(x$path_position),
    n_distinct(x$analysis_span_id) == 1
  )

  x <- arrange(x, path_position)
  duration_edges <- filter(x, !is.na(duration_bin))

  list(
    overview = x |>
      summarise(
        analysis_span_id = first(analysis_span_id),
        n_episodes = n(),
        n_observations = sum(n_observations),
        first_episode = first(episode_id),
        last_episode = last(episode_id),
        start_position = first(path_position),
        end_position = last(path_position),
        start_date = first(seeding_date),
        end_date = last(seeding_date),
        passage_min = min(passage_num),
        passage_max = max(passage_num)
      ),

    episodes = x,

    media_runs = episode_runs(x, media_id),

    protocol_runs = episode_runs(x, protocol_id),

    owner_runs = episode_runs(x, recorded_owner),

    count_processing_runs = episode_runs(x, count_processing_state),

    duration_summary = duration_edges |>
      count(duration_bin, name = "n_edges") |>
      mutate(proportion = n_edges / sum(n_edges)),

    duration_runs = episode_runs(duration_edges, duration_bin),

    graph_events = x |>
      filter(is_branch_point | is_multiparent) |>
      select(
        path_position, episode_id, episode_child_count,
        is_branch_point, is_multiparent
      ),

    comments = x |>
      filter(!is.na(episode_comments), nzchar(episode_comments)) |>
      summarise(
        n_episodes = n(),
        first_position = min(path_position),
        last_position = max(path_position),
        positions = paste(path_position, collapse = ","),
        .by = episode_comments
      )
  )
}
