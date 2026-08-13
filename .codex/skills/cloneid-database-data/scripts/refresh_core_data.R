#!/usr/bin/env Rscript

table_specs <- function() {
  list(
    passaging = list(
      database_table = "Passaging",
      file = "passaging.csv",
      columns = NULL,
      key = "id"
    ),
    media = list(
      database_table = "Media",
      file = "media.csv",
      columns = NULL,
      key = "id"
    ),
    perspective = list(
      database_table = "Perspective",
      file = "perspective.csv",
      columns = c("whichPerspective", "origin"),
      count_as = "n",
      key = c("whichPerspective", "origin")
    ),
    liquid_nitrogen = list(
      database_table = "LiquidNitrogen",
      file = "liquid_nitrogen.csv",
      columns = NULL,
      key = c("Rack", "Row", "BoxRow", "BoxColumn")
    )
  )
}

usage <- function() {
  cat(paste0(
    "Usage:\n",
    "  .codex/skills/cloneid-database-data/scripts/run_core_data_refresh.sh [options]\n\n",
    "Options:\n",
    "  --credentials-file PATH  Read CLONEID_DB_* variables from PATH.\n",
    "                           Defaults to CLONEID_DB_CREDENTIALS_FILE, then\n",
    "                           ~/.config/cloneid/db.env when that file exists.\n",
    "  --baseline PATH          Optional core_data directory to archive and compare.\n",
    "                           Defaults to the repository's local core_data directory.\n",
    "                           Missing baseline CSVs are treated as an empty baseline.\n",
    "  --output-root PATH       Parent directory for immutable refresh runs.\n",
    "                           Defaults to tmp/core_data_refresh in the repository.\n",
    "  --discover-database      Find the one accessible schema containing all four tables.\n",
    "  --help                   Show this help.\n\n",
    "Required environment variables:\n",
    "  CLONEID_DB_HOST, CLONEID_DB_USER, CLONEID_DB_PASSWORD, CLONEID_DB_NAME\n\n",
    "Optional environment variables:\n",
    "  CLONEID_DB_PORT (default 3306), CLONEID_DB_SSL_CA\n"
  ))
}

script_path <- function() {
  file_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
  if (length(file_arg) != 1L) {
    stop("Could not determine the path of the running R script.", call. = FALSE)
  }
  normalizePath(sub("^--file=", "", file_arg), mustWork = TRUE)
}

activate_local_library <- function(workflow_dir) {
  local_library <- file.path(workflow_dir, ".Rlib")
  if (dir.exists(local_library)) {
    .libPaths(unique(c(local_library, .libPaths())))
  }
}

find_repository_root <- function(start) {
  candidate <- normalizePath(start, mustWork = TRUE)
  repeat {
    repository_markers <- c(
      file.path(candidate, "AGENTS.md"),
      file.path(candidate, "scripts", "agentRrunner.sh"),
      file.path(candidate, ".codex", "skills", "cloneid-database-data", "SKILL.md")
    )
    if (all(file.exists(repository_markers))) {
      return(candidate)
    }
    parent <- dirname(candidate)
    if (identical(parent, candidate)) {
      stop("Could not locate the cloneID repository root.", call. = FALSE)
    }
    candidate <- parent
  }
}

parse_arguments <- function(args, defaults) {
  options <- defaults
  index <- 1L
  while (index <= length(args)) {
    argument <- args[[index]]
    if (argument == "--help") {
      options$help <- TRUE
      index <- index + 1L
      next
    }
    if (argument == "--discover-database") {
      options$discover_database <- TRUE
      index <- index + 1L
      next
    }

    option_names <- c("--credentials-file", "--baseline", "--output-root")
    if (!argument %in% option_names) {
      stop(sprintf("Unknown argument: %s", argument), call. = FALSE)
    }
    if (index == length(args)) {
      stop(sprintf("Missing value after %s", argument), call. = FALSE)
    }

    value <- args[[index + 1L]]
    if (argument == "--credentials-file") options$credentials_file <- value
    if (argument == "--baseline") options$baseline <- value
    if (argument == "--output-root") options$output_root <- value
    index <- index + 2L
  }
  options
}

check_credentials_permissions <- function(path) {
  if (.Platform$OS.type == "windows") return(invisible(TRUE))

  info <- file.info(path)
  mode <- as.integer(info$mode)
  group_or_other_bits <- bitwAnd(mode, strtoi("077", base = 8L))
  if (is.na(group_or_other_bits) || group_or_other_bits != 0L) {
    stop(
      sprintf(
        "Credentials file %s must not be accessible by group or other users; run chmod 600 on it.",
        path
      ),
      call. = FALSE
    )
  }
  invisible(TRUE)
}

load_database_config <- function(credentials_file = NULL) {
  source <- "environment"
  if (is.null(credentials_file) || !nzchar(credentials_file)) {
    configured_file <- Sys.getenv("CLONEID_DB_CREDENTIALS_FILE", unset = "")
    default_file <- path.expand("~/.config/cloneid/db.env")
    if (nzchar(configured_file)) {
      credentials_file <- configured_file
    } else if (file.exists(default_file)) {
      credentials_file <- default_file
    }
  }

  if (!is.null(credentials_file) && nzchar(credentials_file)) {
    if (!file.exists(path.expand(credentials_file))) {
      stop(
        sprintf(
          paste0(
            "Credentials file does not exist: %s. Create ~/.config/cloneid/db.env as described in ",
            "workflows/refresh-core-data.md."
          ),
          path.expand(credentials_file)
        ),
        call. = FALSE
      )
    }
    credentials_file <- normalizePath(path.expand(credentials_file), mustWork = TRUE)
    check_credentials_permissions(credentials_file)
    if (!isTRUE(readRenviron(credentials_file))) {
      stop(sprintf("Could not read credentials file: %s", credentials_file), call. = FALSE)
    }
    source <- "credentials_file"
  }

  required <- c(
    host = "CLONEID_DB_HOST",
    user = "CLONEID_DB_USER",
    password = "CLONEID_DB_PASSWORD",
    dbname = "CLONEID_DB_NAME"
  )
  values <- lapply(required, function(name) Sys.getenv(name, unset = ""))
  missing <- names(required)[!vapply(values, nzchar, logical(1))]
  if (length(missing) > 0L) {
    missing_variables <- unname(required[missing])
    stop(
      sprintf(
        paste0(
          "Missing database settings: %s. Create ~/.config/cloneid/db.env as described in ",
          "workflows/refresh-core-data.md."
        ),
        paste(missing_variables, collapse = ", ")
      ),
      call. = FALSE
    )
  }

  port_text <- Sys.getenv("CLONEID_DB_PORT", unset = "3306")
  port <- suppressWarnings(as.integer(port_text))
  if (is.na(port) || port < 1L || port > 65535L) {
    stop("CLONEID_DB_PORT must be an integer from 1 through 65535.", call. = FALSE)
  }

  c(
    values,
    list(
      port = port,
      ssl_ca = Sys.getenv("CLONEID_DB_SSL_CA", unset = ""),
      credential_source = source
    )
  )
}

require_packages <- function(packages) {
  unavailable <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
  if (length(unavailable) > 0L) {
    stop(
      sprintf(
        paste0(
          "Missing or unloadable R packages: %s. Use run_core_data_refresh.sh, which supplies the available MariaDB client library."
        ),
        paste(unavailable, collapse = ", ")
      ),
      call. = FALSE
    )
  }
}

connect_database <- function(config, include_database = TRUE) {
  arguments <- list(
    drv = RMariaDB::MariaDB(),
    host = config$host,
    port = config$port,
    user = config$user,
    password = config$password,
    bigint = "character",
    timezone = "UTC"
  )
  if (include_database) arguments$dbname <- config$dbname
  if (nzchar(config$ssl_ca)) {
    arguments$ssl.ca <- normalizePath(path.expand(config$ssl_ca), mustWork = TRUE)
  }
  do.call(DBI::dbConnect, arguments)
}

resolve_database_case <- function(config) {
  connection <- connect_database(config, include_database = FALSE)
  on.exit(if (DBI::dbIsValid(connection)) DBI::dbDisconnect(connection), add = TRUE)

  databases <- DBI::dbGetQuery(connection, "SHOW DATABASES")[[1L]]
  matches <- databases[tolower(databases) == tolower(config$dbname)]
  if (length(matches) == 1L && !identical(matches[[1L]], config$dbname)) {
    message(sprintf("Resolved database name %s as %s.", config$dbname, matches[[1L]]))
    config$dbname <- matches[[1L]]
  }
  config
}

discover_database <- function(config, specs) {
  connection <- connect_database(config, include_database = FALSE)
  on.exit(if (DBI::dbIsValid(connection)) DBI::dbDisconnect(connection), add = TRUE)

  table_names <- tolower(vapply(specs, `[[`, character(1), "database_table"))
  quoted_names <- paste(as.character(DBI::dbQuoteLiteral(connection, table_names)), collapse = ", ")
  query <- sprintf(
    paste(
      "SELECT table_schema",
      "FROM information_schema.tables",
      "WHERE LOWER(table_name) IN (%s)",
      "GROUP BY table_schema",
      "HAVING COUNT(DISTINCT LOWER(table_name)) = %d"
    ),
    quoted_names,
    length(table_names)
  )
  candidate_result <- DBI::dbGetQuery(connection, query)
  candidates <- candidate_result[[1L]]
  candidates <- setdiff(candidates, c("information_schema", "mysql", "performance_schema", "sys"))
  if (length(candidates) == 0L) {
    nearby <- DBI::dbGetQuery(
      connection,
      paste(
        "SELECT table_schema, table_name",
        "FROM information_schema.tables",
        "WHERE LOWER(table_name) LIKE '%passag%'",
        "OR LOWER(table_name) LIKE '%media%'",
      "OR LOWER(table_name) LIKE '%perspective%'",
      "OR LOWER(table_name) LIKE '%liquid%'",
      "OR LOWER(table_name) LIKE '%nitrogen%'",
        "ORDER BY table_schema, table_name"
      )
    )
    detail <- if (nrow(nearby) == 0L) {
      "No similarly named accessible tables were found."
    } else {
      paste0(
        "Similarly named accessible tables: ",
        paste(paste(nearby[[1L]], nearby[[2L]], sep = "."), collapse = ", ")
      )
    }
    stop(
      sprintf("No accessible database contains all four required tables. %s", detail),
      call. = FALSE
    )
  }
  if (length(candidates) > 1L) {
    stop(
      sprintf(
        "Multiple accessible databases contain the required tables: %s. Set CLONEID_DB_NAME explicitly.",
        paste(candidates, collapse = ", ")
      ),
      call. = FALSE
    )
  }
  message(sprintf("Discovered database containing all required tables: %s", candidates[[1L]]))

  table_query <- sprintf(
    paste(
      "SELECT table_name",
      "FROM information_schema.tables",
      "WHERE table_schema = %s AND LOWER(table_name) IN (%s)"
    ),
    as.character(DBI::dbQuoteLiteral(connection, candidates[[1L]])),
    quoted_names
  )
  actual_tables <- DBI::dbGetQuery(connection, table_query)[[1L]]
  for (name in names(specs)) {
    expected <- tolower(specs[[name]]$database_table)
    matches <- actual_tables[tolower(actual_tables) == expected]
    if (length(matches) != 1L) {
      stop(sprintf("Could not uniquely resolve table %s.", specs[[name]]$database_table), call. = FALSE)
    }
    specs[[name]]$database_table <- matches[[1L]]
  }
  list(database = candidates[[1L]], specs = specs)
}

quoted_select <- function(connection, spec) {
  table <- as.character(DBI::dbQuoteIdentifier(connection, spec$database_table))
  if (!is.null(spec$count_as)) {
    group_fields <- as.character(DBI::dbQuoteIdentifier(connection, spec$columns))
    count_field <- as.character(DBI::dbQuoteIdentifier(connection, spec$count_as))
    return(sprintf(
      "SELECT %s, COUNT(*) AS %s FROM %s GROUP BY %s",
      paste(group_fields, collapse = ", "),
      count_field,
      table,
      paste(group_fields, collapse = ", ")
    ))
  }
  fields <- if (is.null(spec$columns)) {
    "*"
  } else {
    paste(as.character(DBI::dbQuoteIdentifier(connection, spec$columns)), collapse = ", ")
  }
  sprintf("SELECT %s FROM %s", fields, table)
}

normalise_output_column <- function(column) {
  if (inherits(column, "POSIXt")) {
    return(format(column, "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"))
  }
  if (inherits(column, "Date")) {
    return(format(column, "%Y-%m-%d"))
  }
  if (inherits(column, "integer64")) {
    return(as.character(column))
  }
  if (is.factor(column)) {
    return(as.character(column))
  }
  if (is.list(column)) {
    stop("A database query returned an unsupported list column.", call. = FALSE)
  }
  column
}

normalise_output_table <- function(data) {
  output <- as.data.frame(
    lapply(data, normalise_output_column),
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
  names(output) <- names(data)
  output
}

normalise_compare_column <- function(column) {
  value <- normalise_output_column(column)
  value <- as.character(value)
  value[is.na(value) | value == ""] <- NA_character_
  value
}

make_row_keys <- function(data, key_columns, label) {
  if (nrow(data) == 0L) return(character())

  missing_columns <- setdiff(key_columns, names(data))
  if (length(missing_columns) > 0L) {
    stop(
      sprintf("%s is missing key columns: %s", label, paste(missing_columns, collapse = ", ")),
      call. = FALSE
    )
  }

  components <- lapply(key_columns, function(column) {
    value <- normalise_compare_column(data[[column]])
    if (anyNA(value)) {
      stop(sprintf("%s has missing values in key column %s.", label, column), call. = FALSE)
    }
    encoded <- vapply(value, utils::URLencode, character(1), reserved = TRUE)
    paste0(column, "=", encoded)
  })
  keys <- if (length(components) == 1L) {
    components[[1L]]
  } else {
    do.call(paste, c(components, sep = "|"))
  }
  if (anyDuplicated(keys)) {
    stop(sprintf("%s does not have unique values for its configured key.", label), call. = FALSE)
  }
  keys
}

sort_table <- function(data, key_columns, label) {
  keys <- make_row_keys(data, key_columns, label)
  if (length(keys) == 0L) return(data)
  data[order(keys, method = "radix"), , drop = FALSE]
}

download_tables <- function(config, specs) {
  connection <- connect_database(config)
  transaction_open <- FALSE
  on.exit({
    if (transaction_open && DBI::dbIsValid(connection)) {
      try(DBI::dbRollback(connection), silent = TRUE)
    }
    if (DBI::dbIsValid(connection)) DBI::dbDisconnect(connection)
  }, add = TRUE)

  DBI::dbBegin(connection)
  transaction_open <- TRUE
  result <- lapply(names(specs), function(name) {
    spec <- specs[[name]]
    if (!DBI::dbExistsTable(connection, spec$database_table)) {
      stop(sprintf("Database table does not exist: %s", spec$database_table), call. = FALSE)
    }
    if (!is.null(spec$columns)) {
      available_fields <- DBI::dbListFields(connection, spec$database_table)
      missing_fields <- setdiff(spec$columns, available_fields)
      if (length(missing_fields) > 0L) {
        stop(
          sprintf(
            "Table %s is missing requested fields %s. Available fields: %s",
            spec$database_table,
            paste(missing_fields, collapse = ", "),
            paste(available_fields, collapse = ", ")
          ),
          call. = FALSE
        )
      }
    }
    message(sprintf("Downloading %s...", spec$database_table))
    data <- DBI::dbGetQuery(connection, quoted_select(connection, spec))
    data <- normalise_output_table(data)
    sort_table(data, spec$key, sprintf("downloaded table %s", spec$database_table))
  })
  names(result) <- names(specs)

  DBI::dbCommit(connection)
  transaction_open <- FALSE
  result
}

read_comparison_csv <- function(path) {
  utils::read.csv(
    path,
    colClasses = "character",
    na.strings = "",
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
}

empty_diff <- function() {
  data.frame(
    change_type = character(),
    row_key = character(),
    column = character(),
    old_value = character(),
    new_value = character(),
    stringsAsFactors = FALSE
  )
}

row_diff <- function(old, new, key_columns, table_name) {
  old_keys <- make_row_keys(old, key_columns, sprintf("baseline %s", table_name))
  new_keys <- make_row_keys(new, key_columns, sprintf("snapshot %s", table_name))

  added_keys <- setdiff(new_keys, old_keys)
  removed_keys <- setdiff(old_keys, new_keys)
  common_keys <- intersect(old_keys, new_keys)
  common_columns <- intersect(names(old), names(new))
  added_columns <- setdiff(names(new), names(old))
  removed_columns <- setdiff(names(old), names(new))

  pieces <- list()
  if (length(added_keys) > 0L) {
    pieces[[length(pieces) + 1L]] <- data.frame(
      change_type = "added_row",
      row_key = added_keys,
      column = NA_character_,
      old_value = NA_character_,
      new_value = NA_character_,
      stringsAsFactors = FALSE
    )
  }
  if (length(removed_keys) > 0L) {
    pieces[[length(pieces) + 1L]] <- data.frame(
      change_type = "removed_row",
      row_key = removed_keys,
      column = NA_character_,
      old_value = NA_character_,
      new_value = NA_character_,
      stringsAsFactors = FALSE
    )
  }
  if (length(added_columns) > 0L) {
    pieces[[length(pieces) + 1L]] <- data.frame(
      change_type = "added_column",
      row_key = NA_character_,
      column = added_columns,
      old_value = NA_character_,
      new_value = NA_character_,
      stringsAsFactors = FALSE
    )
  }
  if (length(removed_columns) > 0L) {
    pieces[[length(pieces) + 1L]] <- data.frame(
      change_type = "removed_column",
      row_key = NA_character_,
      column = removed_columns,
      old_value = NA_character_,
      new_value = NA_character_,
      stringsAsFactors = FALSE
    )
  }

  modified_keys <- character()
  if (length(common_keys) > 0L) {
    old_index <- match(common_keys, old_keys)
    new_index <- match(common_keys, new_keys)
    for (column in common_columns) {
      old_value <- normalise_compare_column(old[[column]])[old_index]
      new_value <- normalise_compare_column(new[[column]])[new_index]
      same <- (is.na(old_value) & is.na(new_value)) |
        (!is.na(old_value) & !is.na(new_value) & old_value == new_value)
      changed <- which(!same)
      if (length(changed) > 0L) {
        modified_keys <- union(modified_keys, common_keys[changed])
        pieces[[length(pieces) + 1L]] <- data.frame(
          change_type = "modified_cell",
          row_key = common_keys[changed],
          column = column,
          old_value = old_value[changed],
          new_value = new_value[changed],
          stringsAsFactors = FALSE
        )
      }
    }
  }

  detail <- if (length(pieces) == 0L) empty_diff() else do.call(rbind, pieces)
  if (nrow(detail) > 0L) {
    detail <- detail[order(detail$change_type, detail$row_key, detail$column, na.last = TRUE), ]
    rownames(detail) <- NULL
  }
  summary <- data.frame(
    table = table_name,
    baseline_rows = nrow(old),
    snapshot_rows = nrow(new),
    added_rows = length(added_keys),
    removed_rows = length(removed_keys),
    modified_rows = length(modified_keys),
    modified_cells = sum(detail$change_type == "modified_cell"),
    added_columns = paste(added_columns, collapse = ";"),
    removed_columns = paste(removed_columns, collapse = ";"),
    stringsAsFactors = FALSE
  )
  list(detail = detail, summary = summary)
}

write_csv <- function(data, path) {
  utils::write.csv(data, path, row.names = FALSE, na = "")
}

sha256_file <- function(path) {
  unname(digest::digest(path, algo = "sha256", file = TRUE))
}

write_refresh_run <- function(tables, specs, baseline_dir, output_root, config) {
  baseline_dir <- normalizePath(baseline_dir, mustWork = FALSE)
  if (file.exists(baseline_dir) && !dir.exists(baseline_dir)) {
    stop(sprintf("Baseline path is not a directory: %s", baseline_dir), call. = FALSE)
  }
  output_root <- normalizePath(output_root, mustWork = FALSE)
  dir.create(output_root, recursive = TRUE, showWarnings = FALSE, mode = "0700")

  snapshot_id <- format(Sys.time(), "%Y%m%dT%H%M%SZ", tz = "UTC")
  final_dir <- file.path(output_root, snapshot_id)
  partial_dir <- file.path(output_root, paste0(".partial_", snapshot_id))
  if (dir.exists(final_dir) || dir.exists(partial_dir)) {
    stop(sprintf("Refresh run already exists: %s", snapshot_id), call. = FALSE)
  }

  dir.create(file.path(partial_dir, "baseline"), recursive = TRUE, mode = "0700")
  dir.create(file.path(partial_dir, "snapshot"), recursive = TRUE, mode = "0700")
  dir.create(file.path(partial_dir, "diffs"), recursive = TRUE, mode = "0700")
  complete <- FALSE
  on.exit({
    if (!complete && dir.exists(partial_dir)) {
      writeLines(
        "This refresh did not complete. Do not promote files from this directory.",
        file.path(partial_dir, "INCOMPLETE")
      )
    }
  }, add = TRUE)

  summaries <- list()
  manifests <- list()
  schemas <- list()
  for (name in names(specs)) {
    spec <- specs[[name]]
    baseline_source <- file.path(baseline_dir, spec$file)
    baseline_present <- file.exists(baseline_source)
    if (baseline_present) {
      archived_baseline <- file.path(partial_dir, "baseline", spec$file)
      copied <- file.copy(baseline_source, archived_baseline, overwrite = FALSE, copy.mode = TRUE)
      if (!isTRUE(copied)) {
        stop(sprintf("Could not archive baseline file: %s", baseline_source), call. = FALSE)
      }
      old <- read_comparison_csv(archived_baseline)
    } else {
      old <- tables[[name]][0, , drop = FALSE]
    }

    snapshot_file <- file.path(partial_dir, "snapshot", spec$file)
    write_csv(tables[[name]], snapshot_file)

    new <- read_comparison_csv(snapshot_file)
    difference <- row_diff(old, new, spec$key, name)
    write_csv(difference$detail, file.path(partial_dir, "diffs", paste0(name, "_diff.csv")))
    summaries[[name]] <- difference$summary
    manifests[[name]] <- data.frame(
      table = name,
      database_table = spec$database_table,
      file = spec$file,
      key_columns = paste(spec$key, collapse = ";"),
      baseline_present = baseline_present,
      baseline_sha256 = if (baseline_present) sha256_file(archived_baseline) else NA_character_,
      snapshot_sha256 = sha256_file(snapshot_file),
      snapshot_rows = nrow(tables[[name]]),
      snapshot_columns = ncol(tables[[name]]),
      stringsAsFactors = FALSE
    )
    schemas[[name]] <- data.frame(
      table = name,
      column_position = seq_along(tables[[name]]),
      column = names(tables[[name]]),
      r_class = vapply(tables[[name]], function(x) paste(class(x), collapse = ";"), character(1)),
      stringsAsFactors = FALSE
    )
  }

  write_csv(do.call(rbind, summaries), file.path(partial_dir, "diff_summary.csv"))
  write_csv(do.call(rbind, manifests), file.path(partial_dir, "manifest.csv"))
  write_csv(do.call(rbind, schemas), file.path(partial_dir, "schema.csv"))
  writeLines(
    c(
      "status=complete",
      sprintf("snapshot_id=%s", snapshot_id),
      sprintf("retrieved_at_utc=%s", format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")),
      sprintf("credential_source=%s", config$credential_source),
      sprintf("r_version=%s", getRversion()),
      sprintf("dbi_version=%s", as.character(utils::packageVersion("DBI"))),
      sprintf("rmariadb_version=%s", as.character(utils::packageVersion("RMariaDB")))
    ),
    file.path(partial_dir, "RUN_METADATA")
  )

  if (!file.rename(partial_dir, final_dir)) {
    stop(sprintf("Could not finalize refresh run at %s", final_dir), call. = FALSE)
  }
  complete <- TRUE
  final_dir
}

main <- function(args = commandArgs(trailingOnly = TRUE)) {
  workflow_dir <- dirname(script_path())
  activate_local_library(workflow_dir)
  repository_root <- find_repository_root(workflow_dir)
  defaults <- list(
    credentials_file = NULL,
    baseline = file.path(repository_root, "core_data"),
    output_root = file.path(repository_root, "tmp", "core_data_refresh"),
    discover_database = FALSE,
    help = FALSE
  )
  options <- parse_arguments(args, defaults)
  if (isTRUE(options$help)) {
    usage()
    return(invisible(NULL))
  }

  old_umask <- Sys.umask("0077")
  on.exit(Sys.umask(old_umask), add = TRUE)
  require_packages(c("DBI", "RMariaDB", "digest"))
  config <- load_database_config(options$credentials_file)
  config <- resolve_database_case(config)
  specs <- table_specs()
  if (isTRUE(options$discover_database)) {
    discovery <- discover_database(config, specs)
    config$dbname <- discovery$database
    specs <- discovery$specs
  }
  tables <- download_tables(config, specs)
  run_dir <- write_refresh_run(
    tables = tables,
    specs = specs,
    baseline_dir = options$baseline,
    output_root = options$output_root,
    config = config
  )
  message(sprintf("Refresh complete: %s", run_dir))
  message("The repository's local core_data files were not modified.")
  invisible(run_dir)
}

if (sys.nframe() == 0L) {
  main()
}
