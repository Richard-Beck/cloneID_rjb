# Rolling finite-window growth models
#
# Supply contract: callers provide positive finite abundances, complete episode
# IDs, and finite nonnegative integer calendar days from each episode's seeding
# date. The four candidates cross exponential/logistic mean curves with Normal
# or mean-preserving Lognormal errors. Episode intercepts are free; r (and K for
# logistic fits) and dispersion are shared within a window. No data extraction,
# cloneID filtering, file I/O, plotting, or command-line behavior is included.

.growthfit_likelihood_api_version <- "1.0.0"

.fw_specs <- data.frame(
  curve_model = c("exponential", "logistic", "exponential", "logistic"),
  error_model = c(
    "normal", "normal", "mean_preserving_lognormal",
    "mean_preserving_lognormal"
  ),
  stringsAsFactors = FALSE
)

.fw_positive_finite <- function(x) !is.na(x) & is.finite(x) & x > 0

.fw_validate_window_data <- function(
    data, episode_col, day_col, count_col, observation_id_col = NULL) {
  if (!is.data.frame(data) || nrow(data) == 0L) {
    stop("`data` must be a nonempty data.frame.", call. = FALSE)
  }
  requested <- c(episode_col, day_col, count_col, observation_id_col)
  if (anyNA(requested) || any(!nzchar(requested))) {
    stop("Column names must be nonmissing, nonempty strings.", call. = FALSE)
  }
  missing_columns <- setdiff(requested, names(data))
  if (length(missing_columns)) {
    stop("Missing required column(s): ", paste(missing_columns, collapse = ", "),
         call. = FALSE)
  }

  episode <- as.character(data[[episode_col]])
  if (anyNA(episode) || any(!nzchar(trimws(episode)))) {
    stop("Episode identifiers must be complete and nonempty.", call. = FALSE)
  }
  day <- data[[day_col]]
  if (!is.numeric(day) || anyNA(day) || any(!is.finite(day)) ||
      any(day < 0) || any(abs(day - round(day)) > 1e-8)) {
    stop("Calendar days must be finite, nonnegative whole numbers.",
         call. = FALSE)
  }
  count <- data[[count_col]]
  if (!is.numeric(count) || any(!.fw_positive_finite(count))) {
    stop("Abundances must be numeric, finite, and strictly positive.",
         call. = FALSE)
  }
  observation_id <- if (is.null(observation_id_col)) {
    as.character(seq_len(nrow(data)))
  } else {
    as.character(data[[observation_id_col]])
  }
  if (anyNA(observation_id) || any(!nzchar(observation_id)) ||
      anyDuplicated(observation_id)) {
    stop("Observation identifiers must be complete, nonempty, and unique.",
         call. = FALSE)
  }

  episode_levels <- unique(episode)
  episode_index <- match(episode, episode_levels)
  ordering <- order(episode_index, day, observation_id)
  list(
    episode = episode[ordering], episode_levels = episode_levels,
    episode_index = episode_index[ordering], day = as.numeric(day[ordering]),
    count = as.numeric(count[ordering]),
    observation_id = observation_id[ordering]
  )
}

.fw_profile_dispersion <- function(y, mu, error_model) {
  invalid <- length(y) != length(mu) || any(!.fw_positive_finite(y)) ||
    any(!.fw_positive_finite(mu))
  if (invalid) {
    return(list(
      variance = NA_real_, sd = NA_real_, scale = NA_character_,
      collapse_threshold_sd = NA_real_, variance_collapse = NA,
      max_original_scale_variance = NA_real_
    ))
  }
  if (error_model == "normal") {
    variance <- mean((y - mu)^2)
    sigma <- sqrt(variance)
    threshold <- max(y) * 1e-8
    return(list(
      variance = variance, sd = sigma, scale = "original_count",
      collapse_threshold_sd = threshold,
      variance_collapse = !is.finite(sigma) || sigma <= threshold,
      max_original_scale_variance = variance
    ))
  }
  if (error_model == "mean_preserving_lognormal") {
    d2 <- mean((log(y) - log(mu))^2)
    q <- if (d2 == 0) 0 else 2 * d2 / (sqrt(1 + d2) + 1)
    sigma <- sqrt(q)
    return(list(
      variance = q, sd = sigma, scale = "log_count",
      collapse_threshold_sd = 1e-8,
      variance_collapse = !is.finite(sigma) || sigma <= 1e-8,
      max_original_scale_variance = if (is.finite(q)) {
        max(mu^2 * expm1(q))
      } else {
        NA_real_
      }
    ))
  }
  stop("Unknown error model: ", error_model, call. = FALSE)
}

.fw_loglik <- function(y, mu, error_model, dispersion_sd) {
  invalid <- length(y) != length(mu) || any(!.fw_positive_finite(y)) ||
    any(!.fw_positive_finite(mu)) || length(dispersion_sd) != 1L ||
    !is.finite(dispersion_sd) || dispersion_sd <= 0
  if (invalid) return(NA_real_)
  if (error_model == "normal") {
    return(sum(dnorm(y, mean = mu, sd = dispersion_sd, log = TRUE)))
  }
  if (error_model == "mean_preserving_lognormal") {
    q <- dispersion_sd^2
    return(sum(dnorm(
      log(y), mean = log(mu) - q / 2, sd = dispersion_sd, log = TRUE
    ) - log(y)))
  }
  stop("Unknown error model: ", error_model, call. = FALSE)
}

.fw_mean <- function(day, episode_index, parameter, curve_model, n_episodes) {
  if (curve_model == "exponential") {
    eta <- parameter[seq_len(n_episodes)][episode_index] +
      parameter[[n_episodes + 1L]] * day
    if (any(!is.finite(eta)) || any(eta > 700)) {
      return(rep(NA_real_, length(day)))
    }
    return(exp(pmax(eta, -700)))
  }
  if (curve_model == "logistic") {
    log_K <- parameter[[1L]]
    log_A <- parameter[seq.int(2L, n_episodes + 1L)]
    if (!is.finite(log_K) || log_K > 700) {
      return(rep(NA_real_, length(day)))
    }
    eta <- parameter[[n_episodes + 2L]] * day - log_A[episode_index]
    mu <- exp(log_K) * plogis(eta)
    if (any(!.fw_positive_finite(mu))) return(rep(NA_real_, length(day)))
    return(mu)
  }
  stop("Unknown curve model: ", curve_model, call. = FALSE)
}

.fw_rate_starts <- function(day, y, episode_index, n_episodes) {
  centered_day <- day - ave(day, episode_index, FUN = mean)
  log_y <- log(y)
  centered_log_y <- log_y - ave(log_y, episode_index, FUN = mean)
  denominator <- sum(centered_day^2)
  pooled <- if (!is.finite(denominator) || denominator <= 0) {
    0
  } else {
    sum(centered_day * centered_log_y) / denominator
  }
  if (!is.finite(pooled)) pooled <- 0

  endpoints <- rep(NA_real_, n_episodes)
  for (episode_number in seq_len(n_episodes)) {
    index <- which(episode_index == episode_number)
    earliest <- index[which.min(day[index])]
    latest <- index[which.max(day[index])]
    elapsed <- day[[latest]] - day[[earliest]]
    if (elapsed > 0) {
      endpoints[[episode_number]] <-
        (log(y[[latest]]) - log(y[[earliest]])) / elapsed
    }
  }
  endpoints <- endpoints[is.finite(endpoints)]
  list(
    pooled = pooled,
    endpoint = if (length(endpoints)) median(endpoints) else 0
  )
}

.fw_bounds <- function(y, curve_model, n_episodes) {
  log_min <- log(min(y))
  log_max <- log(max(y))
  if (curve_model == "exponential") {
    return(list(
      lower = c(rep(log_min - 20, n_episodes), -20),
      upper = c(rep(log_max + 20, n_episodes), 20),
      names = c(paste0("log_N0__", seq_len(n_episodes)), "r_per_day")
    ))
  }
  if (curve_model == "logistic") {
    return(list(
      lower = c(log_min - 20, rep(-50, n_episodes), -20),
      upper = c(log_max + log(1e6), rep(50, n_episodes), 20),
      names = c("log_K", paste0("log_A__", seq_len(n_episodes)), "r_per_day")
    ))
  }
  stop("Unknown curve model: ", curve_model, call. = FALSE)
}

.fw_starts <- function(day, y, episode_index, n_episodes, curve_model) {
  rates <- .fw_rate_starts(day, y, episode_index, n_episodes)
  if (curve_model == "exponential") {
    candidate_rates <- unique(c(
      rates$pooled, rates$endpoint, 0, 0.1, -0.1, 0.5, -0.5
    ))
    candidate_rates <- candidate_rates[is.finite(candidate_rates)]
    starts <- list()
    for (rate in candidate_rates) {
      log_scale <- vapply(seq_len(n_episodes), function(e) {
        index <- episode_index == e
        mean(log(y[index]) - rate * day[index])
      }, numeric(1))
      starts[[length(starts) + 1L]] <- c(log_scale, rate)
      normal_scale <- vapply(seq_len(n_episodes), function(e) {
        index <- episode_index == e
        multiplier <- exp(pmin(pmax(rate * day[index], -300), 300))
        estimate <- sum(y[index] * multiplier) / sum(multiplier^2)
        log(max(estimate, .Machine$double.xmin))
      }, numeric(1))
      starts[[length(starts) + 1L]] <- c(normal_scale, rate)
    }
    return(starts)
  }
  if (curve_model == "logistic") {
    candidate_rates <- unique(c(
      rates$pooled, rates$endpoint, 0, 0.1, -0.1
    ))
    candidate_rates <- candidate_rates[is.finite(candidate_rates)]
    starts <- list()
    for (multiplier in c(1.05, 2, 20, 500)) {
      K <- max(y) * multiplier
      for (rate in candidate_rates) {
        log_A <- vapply(seq_len(n_episodes), function(e) {
          index <- which(episode_index == e)
          first <- index[which.min(day[index])]
          fraction <- min(max(y[[first]] / K, 1e-10), 1 - 1e-10)
          log((1 - fraction) / fraction) + rate * day[[first]]
        }, numeric(1))
        starts[[length(starts) + 1L]] <- c(log(K), log_A, rate)
      }
    }
    return(starts)
  }
  stop("Unknown curve model: ", curve_model, call. = FALSE)
}

.fw_optimize <- function(starts, objective, lower, upper) {
  best_converged <- best_finite <- NULL
  attempts <- finite_attempts <- converged_attempts <- 0L
  for (start in starts) {
    attempts <- attempts + 1L
    start <- pmin(pmax(as.numeric(start), lower), upper)
    fit <- tryCatch(
      optim(
        par = start, fn = objective, method = "L-BFGS-B",
        lower = lower, upper = upper,
        control = list(maxit = 1200L, factr = 1e7, pgtol = 1e-8)
      ),
      error = function(e) NULL
    )
    if (is.null(fit) || !is.finite(fit$value)) next
    finite_attempts <- finite_attempts + 1L
    start_value <- objective(start)
    if (is.finite(start_value) && start_value < fit$value) {
      fit$par <- start
      fit$value <- start_value
    }
    if (is.null(best_finite) || fit$value < best_finite$value) best_finite <- fit
    if (fit$convergence == 0L) {
      converged_attempts <- converged_attempts + 1L
      if (is.null(best_converged) || fit$value < best_converged$value) {
        best_converged <- fit
      }
    }
  }
  list(
    fit = best_converged, best_finite = best_finite, attempts = attempts,
    finite_attempts = finite_attempts,
    converged_attempts = converged_attempts
  )
}

.fw_empty_fit <- function(
    curve_model, error_model, status, n_observations, n_episodes,
    mean_parameter_count, episodes_with_time_variation) {
  list(
    curve_model = curve_model, error_model = error_model,
    candidate_model = paste(curve_model, error_model, sep = "__"),
    fit_status = status, criterion_eligible = FALSE,
    ineligibility_reason = status, n_observations = n_observations,
    n_episodes = n_episodes, n_distinct_episode_days = NA_integer_,
    episodes_with_time_variation = episodes_with_time_variation,
    mean_parameter_count = mean_parameter_count,
    total_parameter_count = mean_parameter_count + 1L,
    residual_df = n_observations - mean_parameter_count,
    converged = FALSE, optimizer_attempts = 0L,
    finite_optimizer_attempts = 0L, converged_optimizer_attempts = 0L,
    optimizer_convergence_code = NA_integer_, optimizer_message = NA_character_,
    parameter_on_boundary = NA, boundary_parameters = NA_character_,
    variance_collapse = NA, dispersion_variance = NA_real_,
    dispersion_sd = NA_real_, dispersion_scale = NA_character_,
    max_original_scale_variance = NA_real_, logLik = NA_real_,
    AIC = NA_real_, AIC_rank = NA_integer_, AIC_delta = NA_real_,
    AIC_selected = FALSE, BIC = NA_real_, BIC_rank = NA_integer_,
    BIC_delta = NA_real_, BIC_selected = FALSE,
    rmse_original_count = NA_real_, shared_r_per_day = NA_real_,
    shared_doubling_time_days = NA_real_, shared_K = NA_real_,
    parameter = NULL, fitted = rep(NA_real_, n_observations)
  )
}

.fw_fit_candidate <- function(input, curve_model, error_model) {
  n <- length(input$count)
  E <- length(input$episode_levels)
  p_mean <- E + if (curve_model == "exponential") 1L else 2L
  distinct_days <- vapply(seq_len(E), function(e) {
    length(unique(input$day[input$episode_index == e]))
  }, integer(1))
  episodes_with_time <- sum(distinct_days >= 2L)
  empty <- function(status) {
    result <- .fw_empty_fit(
      curve_model, error_model, status, n, E, p_mean, episodes_with_time
    )
    result$n_distinct_episode_days <- sum(distinct_days)
    result
  }
  if (n <= p_mean) return(empty("no_residual_degrees_of_freedom"))
  if (episodes_with_time == 0L) return(empty("no_within_episode_time_variation"))

  bounds <- .fw_bounds(input$count, curve_model, E)
  starts <- .fw_starts(
    input$day, input$count, input$episode_index, E, curve_model
  )
  objective <- function(parameter) {
    mu <- .fw_mean(input$day, input$episode_index, parameter, curve_model, E)
    if (any(!.fw_positive_finite(mu))) return(.Machine$double.xmax / 1e100)
    dispersion <- .fw_profile_dispersion(input$count, mu, error_model)
    safe_sd <- max(dispersion$sd, dispersion$collapse_threshold_sd, na.rm = TRUE)
    likelihood <- .fw_loglik(input$count, mu, error_model, safe_sd)
    if (is.finite(likelihood)) -likelihood else .Machine$double.xmax / 1e100
  }
  optimization <- .fw_optimize(starts, objective, bounds$lower, bounds$upper)
  if (is.null(optimization$fit)) {
    result <- empty(if (is.null(optimization$best_finite)) {
      "optimizer_failed"
    } else {
      "optimizer_nonconverged"
    })
    result$optimizer_attempts <- optimization$attempts
    result$finite_optimizer_attempts <- optimization$finite_attempts
    result$converged_optimizer_attempts <- optimization$converged_attempts
    if (!is.null(optimization$best_finite)) {
      result$optimizer_convergence_code <- optimization$best_finite$convergence
      result$optimizer_message <- if (is.null(optimization$best_finite$message)) {
        NA_character_
      } else {
        as.character(optimization$best_finite$message)
      }
    }
    return(result)
  }

  fit <- optimization$fit
  parameter <- fit$par
  names(parameter) <- bounds$names
  mu <- .fw_mean(input$day, input$episode_index, parameter, curve_model, E)
  dispersion <- .fw_profile_dispersion(input$count, mu, error_model)
  likelihood <- .fw_loglik(input$count, mu, error_model, dispersion$sd)
  tolerance <- 1e-5 * pmax(1, abs(bounds$lower), abs(bounds$upper))
  boundary <- bounds$names[
    abs(parameter - bounds$lower) <= tolerance |
      abs(parameter - bounds$upper) <= tolerance
  ]
  k <- p_mean + 1L
  AIC <- if (is.finite(likelihood)) -2 * likelihood + 2 * k else NA_real_
  BIC <- if (is.finite(likelihood)) -2 * likelihood + log(n) * k else NA_real_

  reasons <- character()
  if (!isTRUE(fit$convergence == 0L)) reasons <- c(reasons, "optimizer_nonconverged")
  if (!is.finite(dispersion$variance) || dispersion$variance <= 0) {
    reasons <- c(reasons, "nonfinite_or_nonpositive_dispersion")
  }
  if (isTRUE(dispersion$variance_collapse)) reasons <- c(reasons, "variance_collapse")
  if (length(boundary)) reasons <- c(reasons, "mean_parameter_on_boundary")
  if (!is.finite(likelihood) || !is.finite(AIC) || !is.finite(BIC)) {
    reasons <- c(reasons, "nonfinite_likelihood_or_criterion")
  }
  reasons <- unique(reasons)
  eligible <- !length(reasons)
  r <- parameter[[if (curve_model == "exponential") E + 1L else E + 2L]]
  K <- if (curve_model == "logistic") exp(parameter[[1L]]) else NA_real_
  list(
    curve_model = curve_model, error_model = error_model,
    candidate_model = paste(curve_model, error_model, sep = "__"),
    fit_status = if (eligible) "ok" else reasons[[1L]],
    criterion_eligible = eligible,
    ineligibility_reason = paste(reasons, collapse = ";"),
    n_observations = n, n_episodes = E,
    n_distinct_episode_days = sum(distinct_days),
    episodes_with_time_variation = episodes_with_time,
    mean_parameter_count = p_mean, total_parameter_count = k,
    residual_df = n - p_mean, converged = TRUE,
    optimizer_attempts = optimization$attempts,
    finite_optimizer_attempts = optimization$finite_attempts,
    converged_optimizer_attempts = optimization$converged_attempts,
    optimizer_convergence_code = fit$convergence,
    optimizer_message = if (is.null(fit$message)) NA_character_ else as.character(fit$message),
    parameter_on_boundary = length(boundary) > 0L,
    boundary_parameters = paste(boundary, collapse = ";"),
    variance_collapse = dispersion$variance_collapse,
    dispersion_variance = dispersion$variance, dispersion_sd = dispersion$sd,
    dispersion_scale = dispersion$scale,
    max_original_scale_variance = dispersion$max_original_scale_variance,
    logLik = likelihood, AIC = AIC, AIC_rank = NA_integer_,
    AIC_delta = NA_real_, AIC_selected = FALSE, BIC = BIC,
    BIC_rank = NA_integer_, BIC_delta = NA_real_, BIC_selected = FALSE,
    rmse_original_count = sqrt(mean((input$count - mu)^2)),
    shared_r_per_day = r,
    shared_doubling_time_days = if (r > 0) log(2) / r else NA_real_,
    shared_K = K, parameter = parameter, fitted = mu
  )
}

.fw_add_selection <- function(fits, criterion) {
  values <- vapply(fits, function(x) x[[criterion]], numeric(1))
  eligible <- which(vapply(
    fits, function(x) isTRUE(x$criterion_eligible), logical(1)
  ) & is.finite(values))
  if (!length(eligible)) return(fits)
  minimum <- min(values[eligible])
  deltas <- values[eligible] - minimum
  ranks <- rank(values[eligible], ties.method = "min")
  tolerance <- sqrt(.Machine$double.eps) * max(1, abs(minimum))
  for (offset in seq_along(eligible)) {
    i <- eligible[[offset]]
    fits[[i]][[paste0(criterion, "_delta")]] <- deltas[[offset]]
    fits[[i]][[paste0(criterion, "_rank")]] <- as.integer(ranks[[offset]])
    fits[[i]][[paste0(criterion, "_selected")]] <- deltas[[offset]] <= tolerance
  }
  fits
}

.fw_candidate_row <- function(fit) {
  keep <- setdiff(names(fit), c("parameter", "fitted"))
  as.data.frame(fit[keep], stringsAsFactors = FALSE, check.names = FALSE)
}

.fw_coefficient_rows <- function(fit, episode_levels) {
  rows <- lapply(seq_along(episode_levels), function(e) {
    if (is.null(fit$parameter)) {
      log_N0 <- N0 <- log_A <- A <- initial_mean <- NA_real_
    } else if (fit$curve_model == "exponential") {
      log_N0 <- fit$parameter[[e]]
      N0 <- exp(log_N0)
      log_A <- A <- NA_real_
      initial_mean <- N0
    } else {
      log_N0 <- N0 <- NA_real_
      log_A <- fit$parameter[[e + 1L]]
      A <- exp(log_A)
      initial_mean <- fit$shared_K / (1 + A)
    }
    data.frame(
      episode_id = episode_levels[[e]], episode_index_in_window = e,
      log_N0 = log_N0, N0 = N0, log_A = log_A, A = A,
      predicted_initial_mean = initial_mean,
      shared_r_per_day = fit$shared_r_per_day, shared_K = fit$shared_K,
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, rows)
}

.fw_identity <- function(fit, candidate_id) {
  data.frame(
    candidate_id = candidate_id, candidate_model = fit$candidate_model,
    curve_model = fit$curve_model, error_model = fit$error_model,
    fit_status = fit$fit_status, criterion_eligible = fit$criterion_eligible,
    stringsAsFactors = FALSE
  )
}

#' Fit and compare four candidates in one supplied episode window.
#'
#' @return A list of `candidate_fits`, `episode_coefficients`, and
#'   `fitted_observations` data.frames.
fit_finite_growth_window <- function(
    data, episode_col = "episode_id", day_col = "calendar_day",
    count_col = "selected_count", observation_id_col = NULL) {
  input <- .fw_validate_window_data(
    data, episode_col, day_col, count_col, observation_id_col
  )
  fits <- lapply(seq_len(nrow(.fw_specs)), function(i) {
    .fw_fit_candidate(
      input, .fw_specs$curve_model[[i]], .fw_specs$error_model[[i]]
    )
  })
  fits <- .fw_add_selection(.fw_add_selection(fits, "AIC"), "BIC")

  candidates <- coefficients <- fitted <- vector("list", length(fits))
  for (i in seq_along(fits)) {
    fit <- fits[[i]]
    candidate_id <- sprintf("candidate_%02d", i)
    candidates[[i]] <- cbind(
      data.frame(candidate_id = candidate_id, stringsAsFactors = FALSE),
      .fw_candidate_row(fit)
    )
    identity <- .fw_identity(fit, candidate_id)
    coefficients[[i]] <- cbind(
      identity[rep(1L, length(input$episode_levels)), , drop = FALSE],
      .fw_coefficient_rows(fit, input$episode_levels)
    )
    fitted[[i]] <- cbind(
      identity[rep(1L, length(input$count)), , drop = FALSE],
      data.frame(
        observation_id = input$observation_id, episode_id = input$episode,
        episode_index_in_window = input$episode_index,
        calendar_day = input$day, observed_count = input$count,
        fitted_mean = fit$fitted, residual = input$count - fit$fitted,
        stringsAsFactors = FALSE
      )
    )
  }
  list(
    candidate_fits = do.call(rbind, candidates),
    episode_coefficients = do.call(rbind, coefficients),
    fitted_observations = do.call(rbind, fitted)
  )
}

#' Create rolling episode windows independently within supplied spans.
make_finite_episode_windows <- function(
    episode_order, group_sizes = c(2L, 3L, 5L),
    episode_col = "episode_id", span_col = "coherent_span_id",
    position_col = "span_position") {
  if (!is.data.frame(episode_order) || !nrow(episode_order)) {
    stop("`episode_order` must be a nonempty data.frame.", call. = FALSE)
  }
  required <- c(episode_col, span_col, position_col)
  missing_columns <- setdiff(required, names(episode_order))
  if (length(missing_columns)) {
    stop("Missing episode-order column(s): ",
         paste(missing_columns, collapse = ", "), call. = FALSE)
  }
  group_sizes <- sort(unique(as.integer(group_sizes)))
  if (!length(group_sizes) || anyNA(group_sizes) || any(group_sizes < 1L)) {
    stop("`group_sizes` must contain positive integers.", call. = FALSE)
  }
  episode_id <- as.character(episode_order[[episode_col]])
  span_id <- as.character(episode_order[[span_col]])
  position <- episode_order[[position_col]]
  if (anyNA(episode_id) || anyNA(span_id) || anyDuplicated(episode_id) ||
      anyNA(position) || any(!is.finite(position))) {
    stop("Episode order IDs/positions must be complete; episode IDs must be unique.",
         call. = FALSE)
  }

  rows <- list()
  row_index <- 0L
  for (span in unique(span_id)) {
    selected <- which(span_id == span)
    selected <- selected[order(position[selected], episode_id[selected])]
    span_episodes <- episode_id[selected]
    span_positions <- position[selected]
    for (group_size in group_sizes) {
      if (group_size > length(selected)) next
      for (start in seq_len(length(selected) - group_size + 1L)) {
        members <- seq.int(start, start + group_size - 1L)
        window_id <- sprintf("%s__g%02d__w%03d", span, group_size, start)
        for (member_number in seq_along(members)) {
          row_index <- row_index + 1L
          member <- members[[member_number]]
          rows[[row_index]] <- data.frame(
            window_id = window_id, coherent_span_id = span,
            group_size = group_size, window_number = start,
            window_start_span_position = min(span_positions[members]),
            window_end_span_position = max(span_positions[members]),
            episode_index_in_window = member_number,
            episode_id = span_episodes[[member]],
            span_position = span_positions[[member]], stringsAsFactors = FALSE
          )
        }
      }
    }
  }
  if (!length(rows)) return(data.frame())
  do.call(rbind, rows)
}

.fw_attach_metadata <- function(metadata, table) {
  cbind(metadata[rep(1L, nrow(table)), , drop = FALSE], table)
}

#' Construct and fit all rolling windows, independently within each span.
fit_rolling_finite_windows <- function(
    observations, episode_order, group_sizes = c(2L, 3L, 5L),
    episode_col = "episode_id", day_col = "calendar_day",
    count_col = "selected_count", observation_id_col = NULL,
    span_col = "coherent_span_id", position_col = "span_position",
    progress = interactive()) {
  windows <- make_finite_episode_windows(
    episode_order, group_sizes, episode_col, span_col, position_col
  )
  if (!nrow(windows)) stop("No rolling windows could be constructed.", call. = FALSE)
  window_ids <- unique(windows$window_id)
  outputs <- list(
    candidate_fits = vector("list", length(window_ids)),
    episode_coefficients = vector("list", length(window_ids)),
    fitted_observations = vector("list", length(window_ids))
  )
  window_summary <- windows[!duplicated(windows$window_id), c(
    "window_id", "coherent_span_id", "group_size", "window_number",
    "window_start_span_position", "window_end_span_position"
  )]

  for (window_index in seq_along(window_ids)) {
    window_id <- window_ids[[window_index]]
    members <- windows[windows$window_id == window_id, , drop = FALSE]
    member_ids <- members$episode_id
    selected <- observations[
      observations[[episode_col]] %in% member_ids, , drop = FALSE
    ]
    selected[[episode_col]] <- factor(
      as.character(selected[[episode_col]]), levels = member_ids
    )
    selected <- selected[
      order(selected[[episode_col]], selected[[day_col]]), , drop = FALSE
    ]
    selected[[episode_col]] <- as.character(selected[[episode_col]])
    missing_members <- setdiff(member_ids, unique(selected[[episode_col]]))
    if (length(missing_members)) {
      stop("Window ", window_id, " lacks observations for: ",
           paste(missing_members, collapse = ", "), call. = FALSE)
    }
    fit <- fit_finite_growth_window(
      selected, episode_col, day_col, count_col, observation_id_col
    )
    metadata <- window_summary[
      window_summary$window_id == window_id, , drop = FALSE
    ]
    for (name in names(outputs)) {
      outputs[[name]][[window_index]] <-
        .fw_attach_metadata(metadata, fit[[name]])
    }
    if (isTRUE(progress) &&
        (window_index %% 10L == 0L || window_index == length(window_ids))) {
      message("Fitted ", window_index, "/", length(window_ids), " windows")
    }
  }
  list(
    windows = windows,
    candidate_fits = do.call(rbind, outputs$candidate_fits),
    episode_coefficients = do.call(rbind, outputs$episode_coefficients),
    fitted_observations = do.call(rbind, outputs$fitted_observations)
  )
}

.gf_episode_reasons <- function(row) {
  reasons <- character()
  if (row$fit_status != "ok") reasons <- c(reasons, row$fit_status)
  if (!isTRUE(row$converged)) reasons <- c(reasons, "not_converged")
  if (row$distinct_calendar_days < row$required_distinct_calendar_days) {
    reasons <- c(reasons, "insufficient_distinct_calendar_days")
  }
  if (row$n_observations <= row$mean_parameter_count) {
    reasons <- c(reasons, "no_residual_degrees_of_freedom")
  }
  if (!isTRUE(row$finite_positive_variance)) {
    reasons <- c(reasons, "nonfinite_or_nonpositive_dispersion")
  }
  if (isTRUE(row$variance_collapse)) reasons <- c(reasons, "variance_collapse")
  if (isTRUE(row$parameter_on_boundary)) {
    reasons <- c(reasons, "mean_parameter_on_boundary")
  }
  if (!is.finite(row$logLik) || !is.finite(row$AIC) || !is.finite(row$BIC)) {
    reasons <- c(reasons, "nonfinite_likelihood_or_criterion")
  }
  unique(reasons)
}

.gf_rank_episode_rows <- function(results, criterion) {
  rank_name <- paste0(criterion, "_rank")
  delta_name <- paste0(criterion, "_delta")
  selected_name <- paste0(criterion, "_selected")
  results[[rank_name]] <- NA_integer_
  results[[delta_name]] <- NA_real_
  results[[selected_name]] <- FALSE
  eligible <- which(results$criterion_eligible & is.finite(results[[criterion]]))
  if (!length(eligible)) return(results)
  values <- results[[criterion]][eligible]
  minimum <- min(values)
  deltas <- values - minimum
  results[[rank_name]][eligible] <- as.integer(rank(values, ties.method = "min"))
  results[[delta_name]][eligible] <- deltas
  tolerance <- sqrt(.Machine$double.eps) * max(1, abs(minimum))
  results[[selected_name]][eligible] <- deltas <= tolerance
  results
}

#' Fit and compare four growth models for one culture episode.
#'
#' This legacy-compatible adapter retains the established signature and
#' flattened four-row schema while delegating all likelihood work to
#' `fit_finite_growth_window()` with E = 1. In addition to the shared engine's
#' support rules, it retains the legacy requirement of at least two distinct
#' dates for exponential and three for logistic candidates.
fit_episode_growth_models <- function(
    episode_data, day_col = "calendar_day", count_col = "selected_count",
    episode_id_col = NULL) {
  if (!is.data.frame(episode_data) || nrow(episode_data) == 0L) {
    stop("`episode_data` must contain at least one observation.", call. = FALSE)
  }
  requested <- c(day_col, count_col, episode_id_col)
  if (anyNA(requested) || any(!nzchar(requested))) {
    stop("Column-name arguments must be nonmissing, nonempty strings.",
         call. = FALSE)
  }
  missing_columns <- setdiff(requested, names(episode_data))
  if (length(missing_columns)) {
    stop("`episode_data` is missing required column(s): ",
         paste(missing_columns, collapse = ", "), call. = FALSE)
  }
  episode_id <- NA_character_
  working <- episode_data
  if (is.null(episode_id_col)) {
    internal_episode_col <- ".growthfit_episode_id"
    while (internal_episode_col %in% names(working)) {
      internal_episode_col <- paste0(internal_episode_col, "_")
    }
    working[[internal_episode_col]] <- "episode_1"
  } else {
    internal_episode_col <- episode_id_col
    ids <- as.character(working[[episode_id_col]])
    if (anyNA(ids) || any(!nzchar(trimws(ids)))) {
      stop("The episode-ID column must be complete and nonempty.", call. = FALSE)
    }
    ids <- unique(ids)
    if (length(ids) != 1L) {
      stop("`episode_data` must contain observations from exactly one episode.",
           call. = FALSE)
    }
    episode_id <- ids[[1L]]
  }
  day <- working[[day_col]]
  count <- working[[count_col]]
  if (!is.numeric(day)) stop("The calendar-day column must be numeric.", call. = FALSE)
  if (anyNA(day) || any(!is.finite(day))) {
    stop("The calendar-day column must contain only finite values.", call. = FALSE)
  }
  if (any(day < 0) || any(abs(day - round(day)) > 1e-8)) {
    stop("The calendar-day column must contain nonnegative whole days since seeding.",
         call. = FALSE)
  }
  if (!is.numeric(count)) stop("The selected-count column must be numeric.", call. = FALSE)
  if (any(!.fw_positive_finite(count))) {
    stop("The selected-count column must contain only finite values strictly > 0.",
         call. = FALSE)
  }

  working <- working[order(day, count), , drop = FALSE]
  fit <- fit_finite_growth_window(
    working, episode_col = internal_episode_col,
    day_col = day_col, count_col = count_col
  )
  candidates <- fit$candidate_fits
  coefficients <- fit$episode_coefficients
  n <- nrow(working)
  distinct_days <- length(unique(working[[day_col]]))
  rows <- vector("list", nrow(candidates))

  for (i in seq_len(nrow(candidates))) {
    candidate <- candidates[i, , drop = FALSE]
    coefficient <- coefficients[
      coefficients$candidate_id == candidate$candidate_id, , drop = FALSE
    ]
    p_mean <- candidate$mean_parameter_count[[1L]]
    unsupported_distinct <- distinct_days < p_mean
    unsupported_residual <- n <= p_mean
    if (unsupported_distinct || unsupported_residual) {
      candidate$fit_status <- if (unsupported_distinct) {
        "insufficient_distinct_calendar_days"
      } else {
        "no_residual_degrees_of_freedom"
      }
      candidate$converged <- FALSE
      candidate$optimizer_attempts <- 0L
      candidate$finite_optimizer_attempts <- 0L
      candidate$converged_optimizer_attempts <- 0L
      candidate$optimizer_convergence_code <- NA_integer_
      candidate$optimizer_message <- NA_character_
      candidate$parameter_on_boundary <- NA
      candidate$boundary_parameters <- NA_character_
      candidate$variance_collapse <- NA
      numeric_na <- c(
        "dispersion_variance", "dispersion_sd",
        "max_original_scale_variance", "logLik", "AIC", "BIC",
        "rmse_original_count", "shared_r_per_day",
        "shared_doubling_time_days", "shared_K"
      )
      candidate[numeric_na] <- NA_real_
      candidate$dispersion_scale <- NA_character_
      coefficient[c(
        "log_N0", "N0", "log_A", "A", "predicted_initial_mean",
        "shared_r_per_day", "shared_K"
      )] <- NA_real_
    }
    finite_variance <- is.finite(candidate$dispersion_variance[[1L]]) &&
      candidate$dispersion_variance[[1L]] > 0
    row <- data.frame(
      episode_id = episode_id,
      candidate_model = candidate$candidate_model,
      criterion_eligible = FALSE,
      ineligibility_reason = "",
      fit_status = candidate$fit_status,
      curve_model = candidate$curve_model,
      error_model = candidate$error_model,
      n_observations = n,
      distinct_calendar_days = distinct_days,
      required_distinct_calendar_days = p_mean,
      mean_parameter_count = p_mean,
      total_parameter_count = p_mean + 1L,
      residual_df = n - p_mean,
      fragile_one_residual_df = n - p_mean == 1L,
      converged = candidate$converged,
      optimizer_attempts = candidate$optimizer_attempts,
      finite_optimizer_attempts = candidate$finite_optimizer_attempts,
      converged_optimizer_attempts = candidate$converged_optimizer_attempts,
      optimizer_convergence_code = candidate$optimizer_convergence_code,
      optimizer_message = candidate$optimizer_message,
      parameter_on_boundary = candidate$parameter_on_boundary,
      boundary_parameters = candidate$boundary_parameters,
      finite_positive_variance = finite_variance,
      variance_collapse = candidate$variance_collapse,
      logLik = candidate$logLik,
      AIC = candidate$AIC,
      BIC = candidate$BIC,
      rmse_original_count = candidate$rmse_original_count,
      dispersion_variance = candidate$dispersion_variance,
      dispersion_sd = candidate$dispersion_sd,
      dispersion_scale = candidate$dispersion_scale,
      collapse_threshold_sd = if (finite_variance) {
        if (candidate$error_model == "normal") max(count) * 1e-8 else 1e-8
      } else {
        NA_real_
      },
      max_original_scale_variance = candidate$max_original_scale_variance,
      N0 = coefficient$N0,
      K = coefficient$shared_K,
      A = coefficient$A,
      r_per_day = candidate$shared_r_per_day,
      doubling_time_days = candidate$shared_doubling_time_days,
      predicted_day_zero = coefficient$predicted_initial_mean,
      normal_sigma = if (candidate$error_model == "normal") {
        candidate$dispersion_sd
      } else {
        NA_real_
      },
      lognormal_sigma_log = if (
        candidate$error_model == "mean_preserving_lognormal"
      ) candidate$dispersion_sd else NA_real_,
      lognormal_implied_CV = if (
        candidate$error_model == "mean_preserving_lognormal" && finite_variance
      ) sqrt(expm1(candidate$dispersion_variance)) else NA_real_,
      stringsAsFactors = FALSE,
      check.names = FALSE
    )
    reasons <- .gf_episode_reasons(row)
    row$criterion_eligible <- length(reasons) == 0L
    row$ineligibility_reason <- paste(reasons, collapse = ";")
    rows[[i]] <- row
  }
  results <- do.call(rbind, rows)
  rownames(results) <- NULL
  results <- .gf_rank_episode_rows(results, "AIC")
  .gf_rank_episode_rows(results, "BIC")
}
