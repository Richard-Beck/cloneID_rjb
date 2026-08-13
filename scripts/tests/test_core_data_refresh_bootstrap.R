#!/usr/bin/env Rscript

script <- file.path(
  getwd(), ".codex", "skills", "cloneid-database-data", "scripts", "refresh_core_data.R"
)
source(script, local = environment())

scratch <- tempfile("cloneid_core_refresh_bootstrap_")
on.exit(unlink(scratch, recursive = TRUE, force = TRUE), add = TRUE)
dir.create(scratch, recursive = TRUE)

tables <- list(
  passaging = data.frame(id = "passage-1", stringsAsFactors = FALSE),
  media = data.frame(id = "medium-1", stringsAsFactors = FALSE),
  perspective = data.frame(
    whichPerspective = "GenomePerspective", origin = "passage-1", n = 1L,
    stringsAsFactors = FALSE
  ),
  liquid_nitrogen = data.frame(
    Rack = "1", Row = "1", BoxRow = "A", BoxColumn = "1",
    stringsAsFactors = FALSE
  )
)

run_dir <- write_refresh_run(
  tables = tables,
  specs = table_specs(),
  baseline_dir = file.path(scratch, "missing_core_data"),
  output_root = file.path(scratch, "runs"),
  config = list(credential_source = "bootstrap-test")
)

manifest <- read.csv(file.path(run_dir, "manifest.csv"), stringsAsFactors = FALSE)
summary <- read.csv(file.path(run_dir, "diff_summary.csv"), stringsAsFactors = FALSE)

stopifnot(
  nrow(manifest) == 4L,
  all(!manifest$baseline_present),
  all(summary$baseline_rows == 0L),
  all(summary$snapshot_rows == 1L),
  all(summary$added_rows == 1L),
  all(file.exists(file.path(run_dir, "snapshot", manifest$file)))
)

message("PASS: core-data refresh supports a missing baseline directory")
