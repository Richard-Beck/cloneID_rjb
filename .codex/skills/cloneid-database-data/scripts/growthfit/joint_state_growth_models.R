# Reusable joint serial-passage growth models
#
# Input contract for one coherent span:
#   episode_id     nonempty episode identifier
#   path_position  unique serial lineage position per episode
#   calendar_day   nonnegative integer calendar days since episode seeding
#   selected_count finite count > 0, selected upstream
#
# Each span needs >=2 episodes and each episode needs >=2 observations. An
# episode observed on only one distinct day is allowed, but its growth-rate
# state is then informed by the serial random walk rather than direct change.
# This file performs no database querying, filtering, lineage construction, or
# corrected-count/raw-count selection.
#
# Advertised API: fit_joint_state_lineage().
# The compile/candidate/span functions remain compatibility entry points for
# the development runners, but are not part of the supply-facing API.

.jss_required_likelihood_api_version <- "1.0.0"
if (!exists(".growthfit_likelihood_api_version", inherits = TRUE) ||
    !identical(
      get(".growthfit_likelihood_api_version", inherits = TRUE),
      .jss_required_likelihood_api_version
    )) {
  stop(
    "Source growth_likelihood_models.R API version 1.0.0 before ",
    "joint_state_growth_models.R.",
    call. = FALSE
  )
}

.jss_source_dir <- local({
  source_file <- tryCatch(sys.frame(1)$ofile, error = function(e) NULL)
  if (is.null(source_file) || !nzchar(source_file)) {
    getwd()
  } else {
    dirname(normalizePath(source_file, mustWork = FALSE))
  }
})
.jss_default_template <- file.path(.jss_source_dir, "joint_state_model.cpp")

.jss_require_tmb <- function() {
  if (!requireNamespace("TMB", quietly = TRUE)) {
    stop("The TMB R package is required.", call. = FALSE)
  }
}

.jss_model_spec <- function(curve_model, error_model, n_episode = NULL) {
  curve_model <- match.arg(curve_model, c("exponential", "logistic"))
  error_model <- match.arg(
    error_model, c("normal", "mean_preserving_lognormal")
  )
  logistic <- identical(curve_model, "logistic")
  lognormal <- identical(error_model, "mean_preserving_lognormal")
  list(
    curve_model = curve_model,
    error_model = error_model,
    candidate_model = paste(curve_model, error_model, sep = "__"),
    logistic = logistic,
    lognormal = lognormal,
    curve_code = as.integer(logistic),
    error_code = as.integer(lognormal),
    intercept_parameter = if (logistic) "A" else "N0",
    observation_scale = if (lognormal) "log_count" else "count",
    hyperparameter_count = if (logistic) 5L else 3L,
    random_effect_multiplier = if (logistic) 2L else 1L,
    parameter_count = if (is.null(n_episode)) {
      NA_integer_
    } else {
      as.integer(n_episode) + if (logistic) 5L else 3L
    }
  )
}

compile_joint_state_model <- function(
    template_file = .jss_default_template,
    rebuild = FALSE,
    compile_flags = "-O2") {
  .jss_require_tmb()
  template_file <- normalizePath(template_file, mustWork = TRUE)
  template_name <- basename(template_file)
  dll_stem <- tools::file_path_sans_ext(template_name)
  build_dir <- file.path(tools::R_user_dir("growthfit", "cache"), "tmb")
  dir.create(build_dir, recursive = TRUE, showWarnings = FALSE)
  build_template <- file.path(build_dir, template_name)
  source_changed <- !file.exists(build_template) || !identical(
    unname(tools::md5sum(template_file)),
    unname(tools::md5sum(build_template))
  )
  if (source_changed && !file.copy(
      template_file, build_template, overwrite = TRUE
  )) {
    stop("Could not copy the TMB template into the build cache.", call. = FALSE)
  }
  dll_path <- file.path(build_dir, paste0(dll_stem, .Platform$dynlib.ext))
  needs_compile <- rebuild || source_changed || !file.exists(dll_path)
  if (needs_compile) {
    old_working_directory <- getwd()
    on.exit(setwd(old_working_directory), add = TRUE)
    setwd(build_dir)
    TMB::compile(template_name, flags = compile_flags)
  }
  loaded <- getLoadedDLLs()
  if (dll_stem %in% names(loaded)) {
    loaded_path <- normalizePath(
      loaded[[dll_stem]][["path"]], mustWork = FALSE
    )
    if (!identical(loaded_path, normalizePath(dll_path))) {
      dyn.unload(loaded_path)
    }
  }
  if (!(dll_stem %in% names(getLoadedDLLs()))) {
    dyn.load(dll_path)
  }
  list(
    dll = dll_stem,
    dll_path = normalizePath(dll_path, mustWork = TRUE),
    template_file = template_file
  )
}

.jss_validate_span <- function(span_data) {
  if (!is.data.frame(span_data) || nrow(span_data) == 0L) {
    stop("`span_data` must be a nonempty data.frame.", call. = FALSE)
  }
  required <- c(
    "episode_id", "path_position", "calendar_day", "selected_count"
  )
  missing <- setdiff(required, names(span_data))
  if (length(missing) > 0L) {
    stop(
      "Missing required span column(s): ", paste(missing, collapse = ", "),
      call. = FALSE
    )
  }
  episode_id <- as.character(span_data$episode_id)
  if (anyNA(episode_id) || any(!nzchar(trimws(episode_id)))) {
    stop("`episode_id` must be complete and nonempty.", call. = FALSE)
  }
  for (column in c("path_position", "calendar_day", "selected_count")) {
    value <- span_data[[column]]
    if (!is.numeric(value) || anyNA(value) || any(!is.finite(value))) {
      stop("`", column, "` must be finite numeric data.", call. = FALSE)
    }
  }
  if (any(span_data$calendar_day < 0) || any(
      abs(span_data$calendar_day - round(span_data$calendar_day)) > 1e-8
  )) {
    stop("`calendar_day` must contain nonnegative whole days.", call. = FALSE)
  }
  if (any(span_data$selected_count <= 0)) {
    stop("`selected_count` must be strictly positive.", call. = FALSE)
  }

  episode_position <- unique(span_data[c("episode_id", "path_position")])
  if (anyDuplicated(episode_position$episode_id)) {
    stop("Each episode must map to exactly one path position.", call. = FALSE)
  }
  if (anyDuplicated(episode_position$path_position)) {
    stop("Each path position must map to exactly one episode.", call. = FALSE)
  }
  if (nrow(episode_position) < 2L) {
    stop(
      "A joint serial-passage span must contain at least two episodes.",
      call. = FALSE
    )
  }
  unsupported <- names(which(table(episode_id) < 2L))
  if (length(unsupported) > 0L) {
    stop(
      "Every episode requires >=2 observations (seed plus harvest); failing: ",
      paste(unsupported, collapse = ", "), call. = FALSE
    )
  }

  episode_position <- episode_position[order(episode_position$path_position), ]
  episode_position$episode_index <- seq_len(nrow(episode_position))
  span_data$episode_index <- NULL
  data <- merge(
    span_data, episode_position,
    by = c("episode_id", "path_position"), sort = FALSE
  )
  data <- data[order(
    data$episode_index, data$calendar_day, data$selected_count
  ), ]
  rownames(data) <- NULL

  span_id <- "span_1"
  if ("span_id" %in% names(data)) {
    span_values <- unique(as.character(data$span_id))
    if (length(span_values) != 1L || anyNA(span_values)) {
      stop(
        "Each call must contain exactly one nonmissing `span_id`.",
        call. = FALSE
      )
    }
    span_id <- span_values[[1L]]
  }
  list(data = data, episodes = episode_position, span_id = span_id)
}

.jss_candidate_grid <- function() {
  expand.grid(
    curve_model = c("exponential", "logistic"),
    error_model = c("normal", "mean_preserving_lognormal"),
    stringsAsFactors = FALSE
  )
}

.jss_softplus <- function(x) {
  pmax(x, 0) + log1p(exp(-abs(x)))
}

.jss_log_mean <- function(data, parameter, spec) {
  index <- data$episode_index
  linear_growth <- parameter$r_state[index] * data$calendar_day
  if (!spec$logistic) {
    return(parameter$log_intercept[index] + linear_growth)
  }
  parameter$logK_state[index] - .jss_softplus(
    parameter$log_intercept[index] - linear_growth
  )
}

.jss_episode_starts <- function(data, episodes, spec) {
  n_episode <- nrow(episodes)
  rates <- log_n0 <- log_k <- log_a <- numeric(n_episode)
  for (e in seq_len(n_episode)) {
    current <- data[data$episode_index == e, ]
    log_fit <- tryCatch(
      lm(log(selected_count) ~ calendar_day, data = current),
      error = function(e) NULL
    )
    coefficient <- if (is.null(log_fit)) {
      c(NA_real_, NA_real_)
    } else {
      coef(log_fit)
    }
    rates[[e]] <- if (
      length(coefficient) >= 2L && is.finite(coefficient[[2L]])
    ) coefficient[[2L]] else 0
    minimum_day <- min(current$calendar_day)
    first_count <- median(
      current$selected_count[current$calendar_day == minimum_day]
    )
    log_n0[[e]] <- if (is.finite(coefficient[[1L]])) {
      coefficient[[1L]]
    } else {
      log(first_count) - rates[[e]] * minimum_day
    }
    capacity <- max(current$selected_count) * 1.5
    log_k[[e]] <- log(capacity)
    log_a[[e]] <- log(max(capacity / exp(log_n0[[e]]) - 1, 0.05))
  }
  rates[!is.finite(rates)] <- 0
  log_n0[!is.finite(log_n0)] <- log(median(data$selected_count))
  log_k[!is.finite(log_k)] <- log(max(data$selected_count) * 1.5)
  log_a[!is.finite(log_a)] <- 0

  list(
    log_intercept = if (spec$logistic) log_a else log_n0,
    r_state = rates,
    logK_state = log_k,
    r_initial_mean = median(rates),
    log_sigma_r = log(max(stats::sd(diff(rates)), 0.05, na.rm = TRUE)),
    logK_initial_mean = median(log_k),
    log_sigma_logK = log(max(
      stats::sd(diff(log_k)), 0.05, na.rm = TRUE
    ))
  )
}

.jss_build_tmb <- function(data, episodes, spec, dll_info) {
  .jss_require_tmb()
  starts <- .jss_episode_starts(data, episodes, spec)
  preliminary_log_mean <- .jss_log_mean(data, starts, spec)
  if (spec$lognormal) {
    sigma_start <- sqrt(mean(
      (log(data$selected_count) - preliminary_log_mean)^2
    ))
    sigma_start <- max(sigma_start, 0.05)
  } else {
    preliminary_mean <- exp(preliminary_log_mean)
    sigma_start <- sqrt(mean((data$selected_count - preliminary_mean)^2))
    sigma_start <- max(sigma_start, stats::sd(data$selected_count) * 0.1, 1)
  }
  parameters <- c(starts, list(log_sigma_obs = log(sigma_start)))
  map <- if (spec$logistic) NULL else list(
    logK_state = factor(rep(NA, nrow(episodes))),
    logK_initial_mean = factor(NA),
    log_sigma_logK = factor(NA)
  )
  random <- if (spec$logistic) {
    c("r_state", "logK_state")
  } else {
    "r_state"
  }
  TMB::MakeADFun(
    data = list(
      y = as.numeric(data$selected_count),
      day = as.numeric(data$calendar_day),
      episode = as.integer(data$episode_index - 1L),
      n_episode = nrow(episodes),
      curve_model = spec$curve_code,
      error_model = spec$error_code
    ),
    parameters = parameters,
    map = map,
    random = random,
    DLL = dll_info$dll,
    silent = TRUE
  )
}

.jss_outer_bounds <- function(obj, data, spec) {
  parameter_names <- names(obj$par)
  lower <- upper <- rep(NA_real_, length(obj$par))
  lower[] <- -Inf
  upper[] <- Inf
  names(lower) <- names(upper) <- parameter_names
  log_min <- log(min(data$selected_count))
  log_max <- log(max(data$selected_count))

  intercept <- parameter_names == "log_intercept"
  lower[intercept] <- if (spec$logistic) -20 else log_min - 10
  upper[intercept] <- if (spec$logistic) 20 else log_max + 10
  lower[parameter_names == "r_initial_mean"] <- -5
  upper[parameter_names == "r_initial_mean"] <- 5
  lower[parameter_names == "log_sigma_r"] <- -8
  upper[parameter_names == "log_sigma_r"] <- log(5)
  lower[parameter_names == "logK_initial_mean"] <- log_min - 5
  upper[parameter_names == "logK_initial_mean"] <- log_max + 10
  lower[parameter_names == "log_sigma_logK"] <- -8
  upper[parameter_names == "log_sigma_logK"] <- log(5)
  observation <- parameter_names == "log_sigma_obs"
  lower[observation] <- if (spec$lognormal) {
    -8
  } else {
    log(max(data$selected_count) * 1e-8)
  }
  upper[observation] <- if (spec$lognormal) {
    3
  } else {
    log(max(data$selected_count) * 100)
  }
  list(lower = lower, upper = upper)
}

.jss_make_outer_starts <- function(start, lower, upper) {
  starts <- lapply(c(0, -1, 1), function(shift) {
    candidate <- start
    innovation <- names(candidate) %in% c(
      "log_sigma_r", "log_sigma_logK"
    )
    candidate[innovation] <- candidate[innovation] + shift
    pmin(pmax(candidate, lower), upper)
  })
  starts
}

.jss_extract_se <- function(summary_matrix, parameter_name, n) {
  if (is.null(summary_matrix) || nrow(summary_matrix) == 0L) {
    return(rep(NA_real_, n))
  }
  location <- which(rownames(summary_matrix) == parameter_name)
  if (length(location) != n) return(rep(NA_real_, n))
  as.numeric(summary_matrix[location, "Std. Error"])
}

.jss_run_optimizer <- function(obj, bounds) {
  starts <- .jss_make_outer_starts(obj$par, bounds$lower, bounds$upper)
  attempts <- lapply(starts, function(start) tryCatch(
    nlminb(
      start = start, objective = obj$fn, gradient = obj$gr,
      lower = bounds$lower, upper = bounds$upper,
      control = list(
        iter.max = 1500L, eval.max = 3000L,
        rel.tol = 1e-9, x.tol = 1e-8
      )
    ),
    error = function(e) e
  ))
  valid <- vapply(
    attempts,
    function(x) !inherits(x, "error") && is.finite(x$objective),
    logical(1)
  )
  if (!any(valid)) {
    messages <- vapply(
      attempts,
      function(x) if (inherits(x, "error")) conditionMessage(x) else "nonfinite",
      character(1)
    )
    return(list(error = paste(unique(messages), collapse = " | ")))
  }
  valid_attempts <- attempts[valid]
  opt <- valid_attempts[[which.min(vapply(
    valid_attempts, function(x) x$objective, numeric(1)
  ))]]
  marginal_nll <- tryCatch(obj$fn(opt$par), error = function(e) NA_real_)
  gradient <- tryCatch(
    obj$gr(opt$par),
    error = function(e) rep(NA_real_, length(opt$par))
  )
  parameter <- tryCatch(obj$env$parList(opt$par), error = function(e) NULL)
  if (is.null(parameter) || !is.finite(marginal_nll)) {
    return(list(error = "Could not recover finite optimum and latent modes."))
  }

  sd_report <- tryCatch(
    TMB::sdreport(obj, par.fixed = opt$par, getJointPrecision = TRUE),
    error = function(e) e
  )
  sd_failed <- inherits(sd_report, "error")
  fixed_summary <- if (sd_failed) NULL else tryCatch(
    summary(sd_report, "fixed"), error = function(e) NULL
  )
  random_summary <- if (sd_failed) NULL else tryCatch(
    summary(sd_report, "random"), error = function(e) NULL
  )
  list(
    error = NULL, opt = opt, marginal_nll = marginal_nll,
    gradient = gradient, parameter = parameter, attempts = attempts,
    valid = valid, sd_report = sd_report,
    pd_hessian = if (sd_failed) FALSE else isTRUE(sd_report$pdHess),
    fixed_summary = fixed_summary, random_summary = random_summary
  )
}

.jss_empty_candidate <- function(span_id, data, spec, message) {
  list(
    summary = data.frame(
      span_id = span_id,
      candidate_model = spec$candidate_model,
      curve_model = spec$curve_model,
      error_model = spec$error_model,
      fit_status = "failed",
      message = as.character(message),
      n_episodes = length(unique(data$episode_id)),
      n_observations = nrow(data),
      marginal_logLik = NA_real_, parameter_count = NA_integer_,
      AIC = NA_real_, BIC = NA_real_, AIC_delta = NA_real_,
      BIC_delta = NA_real_, AIC_rank = NA_integer_, BIC_rank = NA_integer_,
      sigma_observation = NA_real_, sigma_observation_scale = NA_character_,
      r_initial_mean = NA_real_, sigma_r_innovation = NA_real_,
      logK_initial_mean = NA_real_, sigma_logK_innovation = NA_real_,
      convergence_code = NA_integer_, iterations = NA_integer_,
      max_abs_gradient = NA_real_, pd_hessian = NA,
      boundary_parameters = NA_character_, laplace_approximation = TRUE,
      random_effect_dimension = NA_integer_, stringsAsFactors = FALSE
    ),
    states = data.frame(), intercepts = data.frame(), fitted = data.frame(),
    hyperparameters = data.frame(), diagnostics = data.frame()
  )
}

.jss_add_model_keys <- function(table, span_id, spec) {
  table$span_id <- span_id
  table$candidate_model <- spec$candidate_model
  table$curve_model <- spec$curve_model
  table$error_model <- spec$error_model
  table
}

.jss_episode_tables <- function(data, episodes, span_id, spec, fit) {
  n_episode <- nrow(episodes)
  parameter <- fit$parameter
  r_state <- as.numeric(parameter$r_state)
  log_k <- if (spec$logistic) {
    as.numeric(parameter$logK_state)
  } else {
    rep(NA_real_, n_episode)
  }
  log_intercept <- as.numeric(parameter$log_intercept)
  r_se <- .jss_extract_se(fit$random_summary, "r_state", n_episode)
  log_k_se <- if (spec$logistic) {
    .jss_extract_se(fit$random_summary, "logK_state", n_episode)
  } else {
    rep(NA_real_, n_episode)
  }
  intercept_se <- .jss_extract_se(
    fit$fixed_summary, "log_intercept", n_episode
  )

  states <- .jss_add_model_keys(episodes, span_id, spec)
  states$n_observations <- as.integer(
    table(data$episode_id)[episodes$episode_id]
  )
  states$n_distinct_calendar_days <- as.integer(tapply(
    data$calendar_day, data$episode_id, function(x) length(unique(x))
  )[episodes$episode_id])
  states$has_direct_within_episode_time_information <-
    states$n_distinct_calendar_days >= 2L
  states$r_per_day <- r_state
  states$r_se <- r_se
  states$r_lower_95 <- r_state - 1.96 * r_se
  states$r_upper_95 <- r_state + 1.96 * r_se
  states$logK <- log_k
  states$logK_se <- log_k_se
  states$K <- exp(log_k)
  states$K_lower_95 <- exp(log_k - 1.96 * log_k_se)
  states$K_upper_95 <- exp(log_k + 1.96 * log_k_se)

  intercepts <- .jss_add_model_keys(episodes, span_id, spec)
  intercepts$intercept_parameter <- spec$intercept_parameter
  intercepts$log_intercept <- log_intercept
  intercepts$log_intercept_se <- intercept_se
  intercepts$intercept <- exp(log_intercept)
  intercepts$intercept_lower_95 <- exp(log_intercept - 1.96 * intercept_se)
  intercepts$intercept_upper_95 <- exp(log_intercept + 1.96 * intercept_se)
  intercepts$implied_N0 <- if (spec$logistic) {
    exp(log_k) / (1 + exp(log_intercept))
  } else {
    exp(log_intercept)
  }
  list(states = states, intercepts = intercepts)
}

.jss_fitted_table <- function(data, span_id, spec, fit) {
  log_mean <- .jss_log_mean(data, fit$parameter, spec)
  fitted_mean <- exp(log_mean)
  sigma <- exp(as.numeric(fit$parameter$log_sigma_obs))
  if (spec$lognormal) {
    conditional_loglik <- dnorm(
      log(data$selected_count), log_mean - 0.5 * sigma^2,
      sigma, log = TRUE
    ) - log(data$selected_count)
    standardized_residual <- (
      log(data$selected_count) - log_mean + 0.5 * sigma^2
    ) / sigma
  } else {
    conditional_loglik <- dnorm(
      data$selected_count, fitted_mean, sigma, log = TRUE
    )
    standardized_residual <- (data$selected_count - fitted_mean) / sigma
  }
  result <- data.frame(
    span_id = span_id,
    candidate_model = spec$candidate_model,
    curve_model = spec$curve_model,
    error_model = spec$error_model,
    episode_id = data$episode_id,
    path_position = data$path_position,
    calendar_day = data$calendar_day,
    observed_count = data$selected_count,
    fitted_mean = fitted_mean,
    residual_original = data$selected_count - fitted_mean,
    log_residual = log(data$selected_count) - log_mean,
    standardized_residual = standardized_residual,
    conditional_observation_loglik = conditional_loglik,
    stringsAsFactors = FALSE
  )
  optional <- intersect(
    c("passage_id", "event", "observation_date", "count_source"), names(data)
  )
  for (column in optional) result[[column]] <- data[[column]]
  result
}

.jss_hyperparameter_table <- function(span_id, spec, fit) {
  parameter <- fit$parameter
  fixed_se <- function(name) {
    .jss_extract_se(fit$fixed_summary, name, 1L)[[1L]]
  }
  name <- c("r_initial_mean", "sigma_r_innovation")
  estimate <- c(
    as.numeric(parameter$r_initial_mean),
    exp(as.numeric(parameter$log_sigma_r))
  )
  standard_error <- c(
    fixed_se("r_initial_mean"),
    estimate[[2L]] * fixed_se("log_sigma_r")
  )
  scale <- c("rate_per_day", "rate_per_day")
  if (spec$logistic) {
    name <- c(name, "logK_initial_mean", "sigma_logK_innovation")
    estimate <- c(
      estimate, as.numeric(parameter$logK_initial_mean),
      exp(as.numeric(parameter$log_sigma_logK))
    )
    standard_error <- c(
      standard_error, fixed_se("logK_initial_mean"),
      estimate[[4L]] * fixed_se("log_sigma_logK")
    )
    scale <- c(scale, "log_count", "log_count")
  }
  sigma <- exp(as.numeric(parameter$log_sigma_obs))
  data.frame(
    span_id = span_id,
    candidate_model = spec$candidate_model,
    parameter = c(name, "sigma_observation"),
    estimate = c(estimate, sigma),
    std_error = c(
      standard_error, sigma * fixed_se("log_sigma_obs")
    ),
    scale = c(scale, spec$observation_scale),
    stringsAsFactors = FALSE
  )
}

.jss_fit_summary <- function(data, episodes, span_id, spec, fit, bounds) {
  opt <- fit$opt
  near_bound <- which(
    is.finite(bounds$lower) & abs(opt$par - bounds$lower) < 0.02 |
      is.finite(bounds$upper) & abs(opt$par - bounds$upper) < 0.02
  )
  boundary <- if (length(near_bound) == 0L) "" else paste(
    unique(names(opt$par)[near_bound]), collapse = ";"
  )
  max_gradient <- if (all(!is.finite(fit$gradient))) {
    NA_real_
  } else {
    max(abs(fit$gradient), na.rm = TRUE)
  }
  sd_failed <- inherits(fit$sd_report, "error")
  message <- if (sd_failed) {
    paste("sdreport failed:", conditionMessage(fit$sd_report))
  } else {
    as.character(opt$message)
  }
  fit_status <- if (
    opt$convergence == 0L && fit$pd_hessian &&
      is.finite(max_gradient) && max_gradient < 1e-2 && !nzchar(boundary)
  ) "converged" else "diagnostic_warning"
  parameter <- fit$parameter
  sigma_observation <- exp(as.numeric(parameter$log_sigma_obs))
  marginal_loglik <- -as.numeric(fit$marginal_nll)
  aic <- -2 * marginal_loglik + 2 * spec$parameter_count
  bic <- -2 * marginal_loglik + log(nrow(data)) * spec$parameter_count

  summary <- data.frame(
    span_id = span_id,
    candidate_model = spec$candidate_model,
    curve_model = spec$curve_model,
    error_model = spec$error_model,
    fit_status = fit_status,
    message = message,
    n_episodes = nrow(episodes),
    n_observations = nrow(data),
    marginal_logLik = marginal_loglik,
    parameter_count = spec$parameter_count,
    AIC = aic, BIC = bic,
    AIC_delta = NA_real_, BIC_delta = NA_real_,
    AIC_rank = NA_integer_, BIC_rank = NA_integer_,
    sigma_observation = sigma_observation,
    sigma_observation_scale = spec$observation_scale,
    r_initial_mean = as.numeric(parameter$r_initial_mean),
    sigma_r_innovation = exp(as.numeric(parameter$log_sigma_r)),
    logK_initial_mean = if (spec$logistic) {
      as.numeric(parameter$logK_initial_mean)
    } else NA_real_,
    sigma_logK_innovation = if (spec$logistic) {
      exp(as.numeric(parameter$log_sigma_logK))
    } else NA_real_,
    convergence_code = opt$convergence,
    iterations = opt$iterations,
    max_abs_gradient = max_gradient,
    pd_hessian = fit$pd_hessian,
    boundary_parameters = boundary,
    laplace_approximation = TRUE,
    random_effect_dimension = nrow(episodes) * spec$random_effect_multiplier,
    stringsAsFactors = FALSE
  )
  diagnostics <- data.frame(
    span_id = span_id,
    candidate_model = spec$candidate_model,
    attempted_starts = length(fit$attempts),
    finite_attempts = sum(fit$valid),
    converged_attempts = sum(vapply(
      fit$attempts,
      function(x) !inherits(x, "error") && identical(x$convergence, 0L),
      logical(1)
    )),
    best_objective = opt$objective,
    max_abs_gradient = max_gradient,
    gradient_warning_threshold = 1e-2,
    pd_hessian = fit$pd_hessian,
    boundary_parameters = boundary,
    stringsAsFactors = FALSE
  )
  list(summary = summary, diagnostics = diagnostics)
}

fit_joint_state_candidate <- function(
    span_data,
    curve_model = c("exponential", "logistic"),
    error_model = c("normal", "mean_preserving_lognormal"),
    dll_info = compile_joint_state_model()) {
  spec <- .jss_model_spec(curve_model, error_model)
  validated <- .jss_validate_span(span_data)
  data <- validated$data
  episodes <- validated$episodes
  span_id <- validated$span_id
  spec$parameter_count <- nrow(episodes) + spec$hyperparameter_count

  obj <- tryCatch(
    .jss_build_tmb(data, episodes, spec, dll_info),
    error = function(e) e
  )
  if (inherits(obj, "error")) {
    return(.jss_empty_candidate(
      span_id, data, spec, conditionMessage(obj)
    ))
  }
  bounds <- .jss_outer_bounds(obj, data, spec)
  fit <- .jss_run_optimizer(obj, bounds)
  if (!is.null(fit$error)) {
    return(.jss_empty_candidate(span_id, data, spec, fit$error))
  }

  episode_tables <- .jss_episode_tables(
    data, episodes, span_id, spec, fit
  )
  fit_tables <- .jss_fit_summary(
    data, episodes, span_id, spec, fit, bounds
  )
  list(
    summary = fit_tables$summary,
    states = episode_tables$states,
    intercepts = episode_tables$intercepts,
    fitted = .jss_fitted_table(data, span_id, spec, fit),
    hyperparameters = .jss_hyperparameter_table(span_id, spec, fit),
    diagnostics = fit_tables$diagnostics
  )
}

.jss_bind_rows <- function(items, component) {
  frames <- lapply(items, `[[`, component)
  frames <- frames[vapply(frames, nrow, integer(1)) > 0L]
  if (length(frames) == 0L) data.frame() else do.call(rbind, frames)
}

fit_joint_state_span <- function(
    span_data,
    dll_info = compile_joint_state_model()) {
  .jss_validate_span(span_data)
  grid <- .jss_candidate_grid()
  fits <- lapply(seq_len(nrow(grid)), function(index) {
    fit_joint_state_candidate(
      span_data,
      curve_model = grid$curve_model[[index]],
      error_model = grid$error_model[[index]],
      dll_info = dll_info
    )
  })
  summary <- .jss_bind_rows(fits, "summary")
  eligible <- is.finite(summary$AIC) & is.finite(summary$BIC)
  if (any(eligible)) {
    summary$AIC_delta[eligible] <- summary$AIC[eligible] -
      min(summary$AIC[eligible])
    summary$BIC_delta[eligible] <- summary$BIC[eligible] -
      min(summary$BIC[eligible])
    summary$AIC_rank[eligible] <- rank(
      summary$AIC[eligible], ties.method = "min"
    )
    summary$BIC_rank[eligible] <- rank(
      summary$BIC[eligible], ties.method = "min"
    )
  }
  list(
    summary = summary,
    states = .jss_bind_rows(fits, "states"),
    intercepts = .jss_bind_rows(fits, "intercepts"),
    fitted = .jss_bind_rows(fits, "fitted"),
    hyperparameters = .jss_bind_rows(fits, "hyperparameters"),
    diagnostics = .jss_bind_rows(fits, "diagnostics")
  )
}

fit_joint_state_lineage <- function(
    lineage_data,
    span_col = "span_id",
    dll_info = compile_joint_state_model()) {
  if (!is.data.frame(lineage_data) || !(span_col %in% names(lineage_data))) {
    stop("`lineage_data` must contain the requested span column.", call. = FALSE)
  }
  span_order <- aggregate(
    lineage_data$path_position,
    list(span = as.character(lineage_data[[span_col]])), min
  )
  span_ids <- span_order$span[order(span_order$x)]
  fits <- lapply(span_ids, function(span_id) {
    current <- lineage_data[
      as.character(lineage_data[[span_col]]) == span_id,
    ]
    current$span_id <- span_id
    fit_joint_state_span(current, dll_info = dll_info)
  })
  components <- c(
    "summary", "states", "intercepts", "fitted",
    "hyperparameters", "diagnostics"
  )
  result <- lapply(components, function(component) {
    frames <- lapply(fits, `[[`, component)
    frames <- frames[vapply(frames, nrow, integer(1)) > 0L]
    if (length(frames) == 0L) data.frame() else do.call(rbind, frames)
  })
  names(result) <- components
  result
}
