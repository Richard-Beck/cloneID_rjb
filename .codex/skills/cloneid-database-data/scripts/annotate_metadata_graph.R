#!/usr/bin/env Rscript

options(stringsAsFactors = FALSE)

root_dir <- normalizePath(getwd(), mustWork = TRUE)
core_dir <- file.path(root_dir, "core_data")
out_dir <- file.path(root_dir, "data")
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

owned_outputs <- c(
  "annotated_passaging_nodes.csv",
  "passaging_edges.csv",
  "culture_episodes.csv",
  "culture_episode_edges.csv",
  "metadata_graph_qc_summary.csv"
)
for (path in file.path(out_dir, owned_outputs)) {
  if (file.exists(path)) unlink(path)
}

read_csv <- function(path) read.csv(path, stringsAsFactors = FALSE, na.strings = c("", "NA", "NaN"))

clean_chr <- function(x) {
  x <- trimws(as.character(x))
  x[is.na(x) | x == ""] <- NA_character_
  x
}

num <- function(x) suppressWarnings(as.numeric(clean_chr(x)))

parse_iso_datetime <- function(x) {
  x <- clean_chr(x)
  out <- as.POSIXct(rep(NA_character_, length(x)), tz = "UTC")
  ok <- !is.na(x) & grepl("^\\d{4}-\\d{2}-\\d{2}T", x)
  out[ok] <- as.POSIXct(x[ok], format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC")
  out
}

fmt_time <- function(x) {
  out <- rep(NA_character_, length(x))
  ok <- !is.na(x)
  out[ok] <- format(x[ok], "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  out
}

collapse_unique <- function(x, sep = "|") {
  x <- unique(clean_chr(x))
  x <- x[!is.na(x)]
  if (length(x) == 0) NA_character_ else paste(x, collapse = sep)
}

flag_join <- function(...) {
  vals <- unlist(list(...), use.names = FALSE)
  vals <- vals[!is.na(vals) & vals != ""]
  if (length(vals) == 0) "" else paste(unique(vals), collapse = ";")
}

row_collapse <- function(mat) {
  apply(as.matrix(mat), 1, function(z) {
    z <- clean_chr(z)
    z <- z[!is.na(z)]
    if (length(z) == 0) NA_character_ else paste(z, collapse = " + ")
  })
}

media_nonzero <- function(df, value_col, pct_col = NULL, suffix = "") {
  if (!value_col %in% names(df)) return(rep(NA_character_, nrow(df)))
  val <- clean_chr(df[[value_col]])
  keep <- !is.na(val)
  out <- val
  if (!is.null(pct_col) && pct_col %in% names(df)) {
    pct <- num(df[[pct_col]])
    keep <- keep & (is.na(pct) | pct != 0)
    with_pct <- keep & !is.na(pct)
    out[with_pct] <- paste0(val[with_pct], " ", pct[with_pct], suffix)
  }
  out[!keep] <- NA_character_
  out
}

make_graph_metrics <- function(node_ids, edges) {
  n <- length(node_ids)
  idx <- setNames(seq_along(node_ids), node_ids)
  children <- vector("list", n)
  parents <- vector("list", n)
  for (i in seq_len(n)) {
    children[[i]] <- integer()
    parents[[i]] <- integer()
  }
  valid <- nrow(edges) > 0
  if (valid) {
    pidx <- unname(idx[edges$parent_id])
    cidx <- unname(idx[edges$child_id])
    keep <- !is.na(pidx) & !is.na(cidx) & pidx != cidx
    pidx <- pidx[keep]
    cidx <- cidx[keep]
    for (i in seq_along(pidx)) {
      children[[pidx[i]]] <- c(children[[pidx[i]]], cidx[i])
      parents[[cidx[i]]] <- c(parents[[cidx[i]]], pidx[i])
    }
  }

  child_count <- lengths(children)
  parent_count <- lengths(parents)

  uf_parent <- seq_len(n)
  uf_find <- function(x) {
    while (uf_parent[x] != x) {
      uf_parent[x] <<- uf_parent[uf_parent[x]]
      x <- uf_parent[x]
    }
    x
  }
  uf_union <- function(a, b) {
    ra <- uf_find(a)
    rb <- uf_find(b)
    if (ra != rb) uf_parent[rb] <<- ra
  }
  if (valid) {
    pidx <- unname(idx[edges$parent_id])
    cidx <- unname(idx[edges$child_id])
    keep <- !is.na(pidx) & !is.na(cidx) & pidx != cidx
    for (i in which(keep)) uf_union(pidx[i], cidx[i])
  }
  component_raw <- vapply(seq_len(n), uf_find, integer(1))
  component_id <- match(component_raw, unique(component_raw))
  component_rep <- ave(node_ids, component_id, FUN = function(x) x[1])

  indegree <- parent_count
  queue <- which(indegree == 0)
  topo <- integer()
  head_pos <- 1
  while (head_pos <= length(queue)) {
    v <- queue[head_pos]
    head_pos <- head_pos + 1
    topo <- c(topo, v)
    for (ch in children[[v]]) {
      indegree[ch] <- indegree[ch] - 1
      if (indegree[ch] == 0) queue <- c(queue, ch)
    }
  }
  has_cycle <- length(topo) < n
  depth <- rep(NA_integer_, n)
  depth[parent_count == 0] <- 0L
  for (v in topo) {
    for (ch in children[[v]]) {
      proposed <- depth[v] + 1L
      if (is.na(depth[ch]) || proposed > depth[ch]) depth[ch] <- proposed
    }
  }

  root_ids <- vapply(seq_len(n), function(start) {
    seen <- rep(FALSE, n)
    stack <- start
    roots <- integer()
    while (length(stack) > 0) {
      v <- stack[length(stack)]
      stack <- stack[-length(stack)]
      if (!seen[v]) {
        seen[v] <- TRUE
        if (length(parents[[v]]) == 0) {
          roots <- c(roots, v)
        } else {
          stack <- c(stack, parents[[v]][!seen[parents[[v]]]])
        }
      }
    }
    if (length(roots) == 0) NA_character_ else paste(node_ids[sort(unique(roots))], collapse = "|")
  }, character(1))

  count_reachable <- function(start, adjacency) {
    seen <- rep(FALSE, n)
    stack <- adjacency[[start]]
    while (length(stack) > 0) {
      v <- stack[length(stack)]
      stack <- stack[-length(stack)]
      if (!seen[v]) {
        seen[v] <- TRUE
        nxt <- adjacency[[v]]
        if (length(nxt) > 0) stack <- c(stack, nxt[!seen[nxt]])
      }
    }
    sum(seen)
  }

  data.frame(
    id = node_ids,
    component_id = component_id,
    component_representative_id = component_rep,
    depth = depth,
    parent_count = parent_count,
    child_count = child_count,
    ancestor_count = vapply(seq_len(n), count_reachable, integer(1), adjacency = parents),
    descendant_count = vapply(seq_len(n), count_reachable, integer(1), adjacency = children),
    is_root = parent_count == 0,
    is_leaf = child_count == 0,
    is_branch_point = child_count > 1,
    is_multiparent = parent_count > 1,
    root_ancestor_ids = root_ids,
    has_cycle = has_cycle,
    stringsAsFactors = FALSE
  )
}

message("Reading metadata tables")
passaging <- read_csv(file.path(core_dir, "passaging.csv"))
media <- read_csv(file.path(core_dir, "media.csv"))
perspective <- read_csv(file.path(core_dir, "perspective.csv"))
message("No reviewed protocol mapping is configured; protocol fields will be blank")

required_passaging <- c("id", "cellLine", "event", "passaged_from_id1", "passaged_from_id2",
                        "growthType", "passage", "cellCount", "date", "media",
                        "correctedCount", "areaOccupied_um2", "cellSize_um2")
missing_passaging <- setdiff(required_passaging, names(passaging))
if (length(missing_passaging) > 0) stop("Missing passaging columns: ", paste(missing_passaging, collapse = ", "))
if (!"id" %in% names(media)) stop("Missing media column: id")
if (!all(c("whichPerspective", "origin", "n") %in% names(perspective))) stop("Missing perspective columns")

passaging$id_clean <- clean_chr(passaging$id)
passaging$protocol_id <- rep(NA_character_, nrow(passaging))
passaging$cellLine_clean <- clean_chr(passaging$cellLine)
passaging$event_clean <- clean_chr(passaging$event)
passaging$parent1_clean <- clean_chr(passaging$passaged_from_id1)
passaging$parent2_clean <- clean_chr(passaging$passaged_from_id2)
passaging$growthType_clean <- clean_chr(passaging$growthType)
passaging$media_clean <- clean_chr(passaging$media)
passaging$date_parsed <- parse_iso_datetime(passaging$date)
passaging$date_parsed_iso <- fmt_time(passaging$date_parsed)
passaging$passage_num <- num(passaging$passage)
passaging$cellCount_num <- num(passaging$cellCount)
passaging$correctedCount_num <- num(passaging$correctedCount)
passaging$areaOccupied_um2_num <- num(passaging$areaOccupied_um2)
passaging$cellSize_um2_num <- num(passaging$cellSize_um2)

node_ids <- passaging$id_clean
if (any(is.na(node_ids))) stop("Passaging id contains missing values")
if (any(duplicated(node_ids))) stop("Passaging id contains duplicate values")

media$id_clean <- clean_chr(media$id)
media_cols <- names(media)
serum_part <- media_nonzero(media, "FBS", "FBS_pct", "%")
media$media_base_label <- row_collapse(cbind(media_nonzero(media, "base1", "base1_pct", "%"),
                                             media_nonzero(media, "base2", "base2_pct", "%")))
media$media_energy_label <- row_collapse(cbind(media_nonzero(media, "EnergySource", "EnergySource_nM", " nM"),
                                               media_nonzero(media, "EnergySource2", "EnergySource2_pct", "%")))
media$media_antibiotic_label <- row_collapse(cbind(media_nonzero(media, "antibiotic", "antibiotic_pct", "%"),
                                                   media_nonzero(media, "antibiotic2", "antibiotic2_pct", "%"),
                                                   media_nonzero(media, "antibiotic3", "antibiotic3_pct", "%"),
                                                   media_nonzero(media, "antibiotic4", "antibiotic4_pct", "%"),
                                                   media_nonzero(media, "antimycotic", "antimycotic_pct", "%")))
if ("Stressor" %in% media_cols) {
  stressor <- clean_chr(media$Stressor)
  conc <- if ("Stressor_concentration" %in% media_cols) clean_chr(media$Stressor_concentration) else NA_character_
  unit <- if ("Stressor_unit" %in% media_cols) clean_chr(media$Stressor_unit) else NA_character_
  media$media_stressor_label <- stressor
  with_conc <- !is.na(stressor) & !is.na(conc)
  media$media_stressor_label[with_conc] <- paste(stressor[with_conc], conc[with_conc], unit[with_conc])
} else {
  media$media_stressor_label <- NA_character_
}
media$oxygen_pct_num <- if ("oxygen_pct" %in% media_cols) num(media$oxygen_pct) else NA_real_
media$media_label <- apply(cbind(media$media_base_label, serum_part, media$media_energy_label,
                                 media$media_stressor_label,
                                 ifelse(is.na(media$oxygen_pct_num), NA_character_, paste0("O2 ", media$oxygen_pct_num, "%"))),
                           1, function(z) collapse_unique(z, sep = "; "))
media$media_broad_category <- vapply(media$media_base_label, function(x) {
  x0 <- toupper(ifelse(is.na(x), "", x))
  if (grepl("RPMI", x0)) "RPMI-based"
  else if (grepl("MCCOY|MC COY", x0)) "McCoy-based"
  else if (grepl("DMEM", x0)) "DMEM-based"
  else if (grepl("EMEM", x0)) "EMEM-based"
  else if (grepl("IMDM", x0)) "IMDM-based"
  else if (grepl("EBSS|HBSS|PBS", x0)) "salt-solution"
  else if (x0 == "") "unknown"
  else "other"
}, character(1))

perspective$origin_clean <- clean_chr(perspective$origin)
perspective$whichPerspective_clean <- clean_chr(perspective$whichPerspective)
perspective$n_num <- num(perspective$n)
perspective$assay_type_inferred <- ifelse(
  !is.na(perspective$n_num) & perspective$n_num == 1, "bulk-like",
  ifelse(!is.na(perspective$n_num) & perspective$n_num >= 15 & perspective$n_num <= 35, "karyotype-like",
         ifelse(!is.na(perspective$n_num) & perspective$n_num > 50,
                "single-cell/high-throughput-like", "ambiguous/unknown"))
)

perspective_split <- split(perspective, perspective$origin_clean)
perspective_summary <- data.frame(
  id_clean = names(perspective_split),
  perspective_count = vapply(perspective_split, nrow, integer(1)),
  perspective_types = vapply(perspective_split, function(d) collapse_unique(d$whichPerspective_clean), character(1)),
  perspective_n_values = vapply(perspective_split, function(d) paste(d$n_num, collapse = "|"), character(1)),
  perspective_n_min = vapply(perspective_split, function(d) suppressWarnings(min(d$n_num, na.rm = TRUE)), numeric(1)),
  perspective_n_max = vapply(perspective_split, function(d) suppressWarnings(max(d$n_num, na.rm = TRUE)), numeric(1)),
  inferred_assay_labels = vapply(perspective_split, function(d) collapse_unique(d$assay_type_inferred), character(1))
)
perspective_summary$perspective_n_min[is.infinite(perspective_summary$perspective_n_min)] <- NA_real_
perspective_summary$perspective_n_max[is.infinite(perspective_summary$perspective_n_max)] <- NA_real_

make_edges <- function(parent_col, parent_slot) {
  parent <- clean_chr(passaging[[parent_col]])
  keep <- !is.na(parent)
  data.frame(parent_id = parent[keep], child_id = passaging$id_clean[keep],
             parent_slot = parent_slot, stringsAsFactors = FALSE)
}
row_edges <- rbind(make_edges("parent1_clean", "passaged_from_id1"),
                   make_edges("parent2_clean", "passaged_from_id2"))
row_edges$edge_id <- seq_len(nrow(row_edges))
row_edges$parent_exists <- row_edges$parent_id %in% node_ids
row_edges$child_exists <- row_edges$child_id %in% node_ids
row_edges$self_loop <- row_edges$parent_id == row_edges$child_id
valid_row_edges <- row_edges[row_edges$parent_exists & row_edges$child_exists & !row_edges$self_loop, ]

row_graph <- make_graph_metrics(node_ids, valid_row_edges[, c("parent_id", "child_id")])
idx <- setNames(seq_along(node_ids), node_ids)

parent_events_by_child <- split(passaging$event_clean[match(valid_row_edges$parent_id, node_ids)], valid_row_edges$child_id)
parent_ids_by_child <- split(valid_row_edges$parent_id, valid_row_edges$child_id)
child_ids_by_parent <- split(valid_row_edges$child_id, valid_row_edges$parent_id)

get_parent_ids_by_event <- function(child_id, event) {
  pids <- parent_ids_by_child[[child_id]]
  if (is.null(pids)) return(character())
  pevents <- passaging$event_clean[match(pids, node_ids)]
  pids[pevents == event & !is.na(pevents)]
}

is_seeding <- !is.na(passaging$event_clean) & passaging$event_clean == "seeding"
is_harvest <- !is.na(passaging$event_clean) & passaging$event_clean == "harvest"

culture_episode_id <- rep(NA_character_, nrow(passaging))
episode_assignment_status <- rep("not_assigned", nrow(passaging))
culture_episode_id[is_seeding] <- passaging$id_clean[is_seeding]
episode_assignment_status[is_seeding] <- "seeding_episode"

for (i in which(is_harvest)) {
  seeding_parents <- get_parent_ids_by_event(passaging$id_clean[i], "seeding")
  all_parents <- parent_ids_by_child[[passaging$id_clean[i]]]
  if (length(seeding_parents) == 1) {
    culture_episode_id[i] <- seeding_parents[1]
    episode_assignment_status[i] <- "assigned_from_single_seeding_parent"
  } else if (length(seeding_parents) > 1) {
    culture_episode_id[i] <- paste(seeding_parents, collapse = "|")
    episode_assignment_status[i] <- "ambiguous_multiple_seeding_parents"
  } else if (is.null(all_parents) || length(all_parents) == 0) {
    episode_assignment_status[i] <- "missing_seeding_parent"
  } else {
    episode_assignment_status[i] <- "nonstandard_no_seeding_parent"
  }
}

previous_episode_id <- rep(NA_character_, nrow(passaging))
previous_episode_status <- rep(NA_character_, nrow(passaging))
for (i in which(is_seeding)) {
  harvest_parents <- get_parent_ids_by_event(passaging$id_clean[i], "harvest")
  if (length(harvest_parents) == 1) {
    parent_idx <- idx[harvest_parents[1]]
    previous_episode_id[i] <- culture_episode_id[parent_idx]
    previous_episode_status[i] <- "from_single_harvest_parent"
  } else if (length(harvest_parents) > 1) {
    previous_episode_id[i] <- paste(unique(culture_episode_id[idx[harvest_parents]]), collapse = "|")
    previous_episode_status[i] <- "from_multiple_harvest_parents"
  } else if (!is.null(parent_ids_by_child[[passaging$id_clean[i]]])) {
    previous_episode_status[i] <- "nonstandard_parent_not_harvest"
  } else {
    previous_episode_status[i] <- "root_or_import"
  }
}

passaging$culture_episode_id <- culture_episode_id
passaging$episode_assignment_status <- episode_assignment_status
passaging$previous_episode_id <- previous_episode_id
passaging$previous_episode_status <- previous_episode_status

episode_harvests <- split(which(is_harvest & culture_episode_id %in% passaging$id_clean[is_seeding] &
                                  episode_assignment_status == "assigned_from_single_seeding_parent"),
                          culture_episode_id[is_harvest & culture_episode_id %in% passaging$id_clean[is_seeding] &
                                               episode_assignment_status == "assigned_from_single_seeding_parent"])
observation_number <- rep(NA_integer_, nrow(passaging))
days_since_seeding <- rep(NA_real_, nrow(passaging))
is_terminal_harvest_candidate <- rep(FALSE, nrow(passaging))
for (eid in names(episode_harvests)) {
  hidx <- episode_harvests[[eid]]
  seed_idx <- idx[eid]
  ord <- order(is.na(passaging$date_parsed[hidx]), passaging$date_parsed[hidx], passaging$id_clean[hidx])
  hidx <- hidx[ord]
  observation_number[hidx] <- seq_along(hidx)
  days_since_seeding[hidx] <- as.numeric(difftime(passaging$date_parsed[hidx], passaging$date_parsed[seed_idx], units = "days"))
  dated <- hidx[!is.na(passaging$date_parsed[hidx])]
  terminal <- if (length(dated) > 0) dated[which.max(passaging$date_parsed[dated])] else hidx[length(hidx)]
  is_terminal_harvest_candidate[terminal] <- TRUE
}
passaging$observation_number <- observation_number
passaging$days_since_seeding <- days_since_seeding
passaging$is_terminal_harvest_candidate <- is_terminal_harvest_candidate

media_join <- media[, c("id_clean", "media_label", "media_broad_category", "media_base_label",
                        "media_energy_label", "media_antibiotic_label", "media_stressor_label",
                        "oxygen_pct_num")]
nodes <- merge(passaging, media_join, by.x = "media_clean", by.y = "id_clean", all.x = TRUE, sort = FALSE)
nodes <- merge(nodes, perspective_summary, by = "id_clean", all.x = TRUE, sort = FALSE)
nodes <- nodes[match(node_ids, nodes$id_clean), ]
nodes$perspective_count[is.na(nodes$perspective_count)] <- 0L
nodes$has_perspective <- nodes$perspective_count > 0
nodes$has_media <- !is.na(nodes$media_clean)
nodes$media_resolved <- nodes$has_media & !is.na(nodes$media_label)
nodes$malformed_date <- !is.na(clean_chr(nodes$date)) & is.na(nodes$date_parsed)

nodes$row_component_id <- paste0("row_component_", row_graph$component_id)
nodes$row_component_numeric_id <- row_graph$component_id
nodes$row_component_representative_id <- row_graph$component_representative_id
nodes$row_lineage_depth <- row_graph$depth
nodes$row_parent_count <- row_graph$parent_count
nodes$row_child_count <- row_graph$child_count
nodes$row_ancestor_count <- row_graph$ancestor_count
nodes$row_descendant_count <- row_graph$descendant_count
nodes$row_is_root <- row_graph$is_root
nodes$row_is_leaf <- row_graph$is_leaf
nodes$row_is_branch_point <- row_graph$is_branch_point
nodes$row_is_multiparent <- row_graph$is_multiparent
nodes$row_root_ancestor_ids <- row_graph$root_ancestor_ids
nodes$row_in_cycle_or_unresolved_depth <- is.na(row_graph$depth)

row_edges$parent_event <- passaging$event_clean[match(row_edges$parent_id, node_ids)]
row_edges$child_event <- passaging$event_clean[match(row_edges$child_id, node_ids)]
row_edges$parent_cellLine <- passaging$cellLine_clean[match(row_edges$parent_id, node_ids)]
row_edges$child_cellLine <- passaging$cellLine_clean[match(row_edges$child_id, node_ids)]
row_edges$parent_media <- passaging$media_clean[match(row_edges$parent_id, node_ids)]
row_edges$child_media <- passaging$media_clean[match(row_edges$child_id, node_ids)]
row_edges$parent_culture_episode_id <- passaging$culture_episode_id[match(row_edges$parent_id, node_ids)]
row_edges$child_culture_episode_id <- passaging$culture_episode_id[match(row_edges$child_id, node_ids)]
row_edges$parent_date <- passaging$date_parsed_iso[match(row_edges$parent_id, node_ids)]
row_edges$child_date <- passaging$date_parsed_iso[match(row_edges$child_id, node_ids)]
row_edges$days_between_parent_child <- as.numeric(difftime(passaging$date_parsed[match(row_edges$child_id, node_ids)],
                                                           passaging$date_parsed[match(row_edges$parent_id, node_ids)],
                                                           units = "days"))
child_parent_counts <- table(valid_row_edges$child_id)
row_edges$child_parent_count <- as.integer(child_parent_counts[row_edges$child_id])
row_edges$child_parent_count[is.na(row_edges$child_parent_count)] <- 0L
row_edges$is_multiparent_edge <- row_edges$child_parent_count > 1
row_edges$edge_kind_base <- ifelse(row_edges$parent_event == "seeding" & row_edges$child_event == "harvest", "observation_edge",
                                   ifelse(row_edges$parent_event == "harvest" & row_edges$child_event == "seeding", "propagation_edge",
                                          ifelse(row_edges$parent_event == "harvest" & row_edges$child_event == "harvest", "nonstandard_harvest_to_harvest",
                                                 ifelse(row_edges$parent_event == "seeding" & row_edges$child_event == "seeding", "nonstandard_seeding_to_seeding",
                                                        "nonstandard_other"))))
row_edges$edge_kind <- ifelse(row_edges$is_multiparent_edge,
                              paste(row_edges$edge_kind_base, "multiparent_edge", sep = "|"),
                              row_edges$edge_kind_base)
row_edges$media_changed <- !is.na(row_edges$parent_media) & !is.na(row_edges$child_media) & row_edges$parent_media != row_edges$child_media
row_edges$cellLine_changed <- !is.na(row_edges$parent_cellLine) & !is.na(row_edges$child_cellLine) & row_edges$parent_cellLine != row_edges$child_cellLine
row_edges$child_before_parent <- !is.na(row_edges$days_between_parent_child) & row_edges$days_between_parent_child < 0
row_edges$edge_qc_flags <- mapply(
  flag_join,
  ifelse(!row_edges$parent_exists, "missing_parent_node", NA_character_),
  ifelse(!row_edges$child_exists, "missing_child_node", NA_character_),
  ifelse(row_edges$self_loop, "self_loop", NA_character_),
  ifelse(row_edges$edge_kind_base %in% c("nonstandard_harvest_to_harvest", "nonstandard_seeding_to_seeding", "nonstandard_other"),
         row_edges$edge_kind_base, NA_character_),
  ifelse(row_edges$is_multiparent_edge, "multiparent_child", NA_character_),
  ifelse(row_edges$child_before_parent, "child_date_before_parent_date", NA_character_),
  ifelse(row_edges$cellLine_changed, "cell_line_changed", NA_character_),
  ifelse(row_edges$media_changed, "media_changed", NA_character_),
  SIMPLIFY = TRUE, USE.NAMES = FALSE
)

invalid_parent_by_child <- split(row_edges$parent_id[!row_edges$parent_exists | row_edges$self_loop],
                                 row_edges$child_id[!row_edges$parent_exists | row_edges$self_loop])
nodes$invalid_parent_refs <- vapply(nodes$id_clean, function(id) {
  vals <- invalid_parent_by_child[[id]]
  if (is.null(vals)) NA_character_ else paste(vals, collapse = "|")
}, character(1))
nodes$has_invalid_parent_ref <- !is.na(nodes$invalid_parent_refs)
nodes$has_nonstandard_episode_assignment <- nodes$episode_assignment_status %in%
  c("ambiguous_multiple_seeding_parents", "missing_seeding_parent", "nonstandard_no_seeding_parent")
nodes$qc_flags <- mapply(
  flag_join,
  ifelse(nodes$malformed_date, "malformed_date", NA_character_),
  ifelse(nodes$has_media & !nodes$media_resolved, "unresolved_media", NA_character_),
  ifelse(!nodes$has_media, "missing_media", NA_character_),
  ifelse(nodes$has_invalid_parent_ref, "invalid_parent_ref", NA_character_),
  ifelse(nodes$row_in_cycle_or_unresolved_depth, "row_cycle_or_unresolved_depth", NA_character_),
  ifelse(nodes$row_is_multiparent, "multiple_parents", NA_character_),
  ifelse(nodes$has_nonstandard_episode_assignment, nodes$episode_assignment_status, NA_character_),
  SIMPLIFY = TRUE, USE.NAMES = FALSE
)

seed_idx <- which(is_seeding)
episode_ids <- passaging$id_clean[seed_idx]
episode_edge_rows <- row_edges[row_edges$parent_exists & row_edges$child_exists &
                                row_edges$parent_event == "harvest" & row_edges$child_event == "seeding", ]
episode_edges <- data.frame(
  episode_edge_id = seq_len(nrow(episode_edge_rows)),
  parent_episode_id = episode_edge_rows$parent_culture_episode_id,
  child_episode_id = episode_edge_rows$child_id,
  via_harvest_id = episode_edge_rows$parent_id,
  row_edge_id = episode_edge_rows$edge_id,
  edge_kind = ifelse(episode_edge_rows$is_multiparent_edge, "propagation_edge|multiparent_edge", "propagation_edge"),
  row_edge_days_between = episode_edge_rows$days_between_parent_child,
  stringsAsFactors = FALSE
)

direct_seed_rows <- row_edges[row_edges$parent_exists & row_edges$child_exists &
                               row_edges$parent_event == "seeding" & row_edges$child_event == "seeding", ]
if (nrow(direct_seed_rows) > 0) {
  direct_episode_edges <- data.frame(
    episode_edge_id = seq_len(nrow(direct_seed_rows)) + nrow(episode_edges),
    parent_episode_id = direct_seed_rows$parent_id,
    child_episode_id = direct_seed_rows$child_id,
    via_harvest_id = NA_character_,
    row_edge_id = direct_seed_rows$edge_id,
    edge_kind = ifelse(direct_seed_rows$is_multiparent_edge,
                       "nonstandard_direct_seeding_to_seeding|multiparent_edge",
                       "nonstandard_direct_seeding_to_seeding"),
    row_edge_days_between = direct_seed_rows$days_between_parent_child,
    stringsAsFactors = FALSE
  )
  episode_edges <- rbind(episode_edges, direct_episode_edges)
}
episode_edges$parent_episode_exists <- episode_edges$parent_episode_id %in% episode_ids
episode_edges$child_episode_exists <- episode_edges$child_episode_id %in% episode_ids
episode_edges$parent_cellLine <- passaging$cellLine_clean[match(episode_edges$parent_episode_id, node_ids)]
episode_edges$child_cellLine <- passaging$cellLine_clean[match(episode_edges$child_episode_id, node_ids)]
episode_edges$parent_media <- passaging$media_clean[match(episode_edges$parent_episode_id, node_ids)]
episode_edges$child_media <- passaging$media_clean[match(episode_edges$child_episode_id, node_ids)]
episode_edges$via_harvest_date <- passaging$date_parsed_iso[match(episode_edges$via_harvest_id, node_ids)]
episode_edges$child_seeding_date <- passaging$date_parsed_iso[match(episode_edges$child_episode_id, node_ids)]
episode_edges$days_harvest_to_child_seeding <- as.numeric(difftime(passaging$date_parsed[match(episode_edges$child_episode_id, node_ids)],
                                                                    passaging$date_parsed[match(episode_edges$via_harvest_id, node_ids)],
                                                                    units = "days"))
episode_edges$days_between_episode_events <- episode_edges$days_harvest_to_child_seeding
episode_edges$days_between_episode_events[is.na(episode_edges$days_between_episode_events)] <-
  episode_edges$row_edge_days_between[is.na(episode_edges$days_between_episode_events)]
episode_edges$media_changed <- !is.na(episode_edges$parent_media) & !is.na(episode_edges$child_media) &
  episode_edges$parent_media != episode_edges$child_media
episode_edges$cellLine_changed <- !is.na(episode_edges$parent_cellLine) & !is.na(episode_edges$child_cellLine) &
  episode_edges$parent_cellLine != episode_edges$child_cellLine
episode_edges$is_multiparent_or_mixing <- episode_edges$child_episode_id %in% names(which(table(episode_edges$child_episode_id) > 1))
episode_edges$child_before_via_harvest <- !is.na(episode_edges$days_harvest_to_child_seeding) &
  episode_edges$days_harvest_to_child_seeding < 0
episode_edges$child_before_parent_episode_event <- !is.na(episode_edges$days_between_episode_events) &
  episode_edges$days_between_episode_events < 0
episode_edges$edge_qc_flags <- mapply(
  flag_join,
  ifelse(!episode_edges$parent_episode_exists, "missing_or_ambiguous_parent_episode", NA_character_),
  ifelse(!episode_edges$child_episode_exists, "missing_child_episode", NA_character_),
  ifelse(grepl("nonstandard_direct_seeding_to_seeding", episode_edges$edge_kind),
         "nonstandard_direct_seeding_to_seeding", NA_character_),
  ifelse(episode_edges$is_multiparent_or_mixing, "multiparent_or_mixing_child_episode", NA_character_),
  ifelse(episode_edges$child_before_via_harvest, "child_seeding_date_before_via_harvest_date", NA_character_),
  ifelse(episode_edges$child_before_parent_episode_event, "child_episode_date_before_parent_event_date", NA_character_),
  ifelse(episode_edges$cellLine_changed, "cell_line_changed", NA_character_),
  ifelse(episode_edges$media_changed, "media_changed", NA_character_),
  SIMPLIFY = TRUE, USE.NAMES = FALSE
)

valid_episode_edges <- episode_edges[episode_edges$parent_episode_exists & episode_edges$child_episode_exists &
                                      episode_edges$parent_episode_id != episode_edges$child_episode_id, ]
episode_metric_edges <- data.frame(
  parent_id = valid_episode_edges$parent_episode_id,
  child_id = valid_episode_edges$child_episode_id,
  stringsAsFactors = FALSE
)
episode_graph <- make_graph_metrics(episode_ids, episode_metric_edges)

episode_perspective <- vapply(episode_ids, function(eid) {
  member_ids <- nodes$id_clean[nodes$culture_episode_id == eid | nodes$id_clean == eid]
  sum(nodes$has_perspective[nodes$id_clean %in% member_ids], na.rm = TRUE)
}, integer(1))
episode_perspective_types <- vapply(episode_ids, function(eid) {
  member_ids <- nodes$id_clean[nodes$culture_episode_id == eid | nodes$id_clean == eid]
  collapse_unique(nodes$perspective_types[nodes$id_clean %in% member_ids])
}, character(1))
episode_assay_labels <- vapply(episode_ids, function(eid) {
  member_ids <- nodes$id_clean[nodes$culture_episode_id == eid | nodes$id_clean == eid]
  collapse_unique(nodes$inferred_assay_labels[nodes$id_clean %in% member_ids])
}, character(1))

episodes <- nodes[match(episode_ids, nodes$id_clean), ]
harvest_count <- vapply(episode_ids, function(eid) length(episode_harvests[[eid]]), integer(1))
first_harvest_date <- vapply(episode_ids, function(eid) {
  hidx <- episode_harvests[[eid]]
  if (is.null(hidx) || length(hidx) == 0 || all(is.na(passaging$date_parsed[hidx]))) return(NA_character_)
  fmt_time(min(passaging$date_parsed[hidx], na.rm = TRUE))
}, character(1))
last_harvest_date <- vapply(episode_ids, function(eid) {
  hidx <- episode_harvests[[eid]]
  if (is.null(hidx) || length(hidx) == 0 || all(is.na(passaging$date_parsed[hidx]))) return(NA_character_)
  fmt_time(max(passaging$date_parsed[hidx], na.rm = TRUE))
}, character(1))
terminal_harvest <- vapply(episode_ids, function(eid) {
  hidx <- episode_harvests[[eid]]
  if (is.null(hidx) || length(hidx) == 0) return(NA_character_)
  term <- hidx[passaging$is_terminal_harvest_candidate[hidx]]
  if (length(term) == 0) NA_character_ else passaging$id_clean[term[1]]
}, character(1))
episode_duration_days <- as.numeric(difftime(parse_iso_datetime(last_harvest_date),
                                             passaging$date_parsed[match(episode_ids, node_ids)], units = "days"))
next_child_counts <- vapply(episode_ids, function(eid) {
  ch <- valid_episode_edges$child_episode_id[valid_episode_edges$parent_episode_id == eid]
  vals <- passaging$cellCount_num[match(ch, node_ids)]
  vals <- vals[!is.na(vals)]
  if (length(vals) == 0) NA_character_ else paste(vals, collapse = "|")
}, character(1))
previous_sources <- vapply(episode_ids, function(eid) {
  p <- valid_episode_edges$parent_episode_id[valid_episode_edges$child_episode_id == eid]
  if (length(p) == 0) NA_character_ else paste(unique(p), collapse = "|")
}, character(1))

episodes_out <- data.frame(
  episode_id = episode_ids,
  cellLine = episodes$cellLine_clean,
  seeding_date = episodes$date_parsed_iso,
  seeding_protocol_id = episodes$protocol_id,
  seeding_media_id = episodes$media_clean,
  seeding_media_label = episodes$media_label,
  media_broad_category = episodes$media_broad_category,
  seeding_cellCount = episodes$cellCount_num,
  seeding_correctedCount = episodes$correctedCount_num,
  growthType = episodes$growthType_clean,
  passage_num = episodes$passage_num,
  harvest_observation_count = harvest_count,
  first_harvest_date = first_harvest_date,
  last_harvest_date = last_harvest_date,
  terminal_harvest_candidate = terminal_harvest,
  episode_duration_days = episode_duration_days,
  next_seeding_count_values = next_child_counts,
  previous_episode_source = previous_sources,
  episode_parent_count = episode_graph$parent_count,
  episode_child_count = episode_graph$child_count,
  episode_depth = episode_graph$depth,
  episode_component_id = paste0("episode_component_", episode_graph$component_id),
  episode_component_numeric_id = episode_graph$component_id,
  episode_component_representative_id = episode_graph$component_representative_id,
  episode_root_ancestor_ids = episode_graph$root_ancestor_ids,
  episode_is_root = episode_graph$is_root,
  episode_is_leaf = episode_graph$is_leaf,
  episode_is_branch_point = episode_graph$is_branch_point,
  episode_is_multiparent = episode_graph$is_multiparent,
  perspective_record_count_in_episode = episode_perspective,
  perspective_types_in_episode = episode_perspective_types,
  inferred_assay_labels_in_episode = episode_assay_labels,
  stringsAsFactors = FALSE
)
episodes_out$qc_flags <- mapply(
  flag_join,
  ifelse(is.na(episodes_out$seeding_date) & !is.na(clean_chr(episodes$date)), "malformed_seeding_date", NA_character_),
  ifelse(episodes_out$harvest_observation_count == 0, "no_harvest_observations", NA_character_),
  ifelse(episodes_out$episode_is_multiparent, "multiparent_or_mixing_episode", NA_character_),
  ifelse(!is.na(episodes_out$episode_duration_days) & episodes_out$episode_duration_days < 0, "negative_episode_duration", NA_character_),
  SIMPLIFY = TRUE, USE.NAMES = FALSE
)

node_output <- nodes[, c(
  "id_clean", "cellLine_clean", "event_clean", "growthType_clean", "passage_num",
  "protocol_id",
  "date", "date_parsed_iso", "parent1_clean", "parent2_clean",
  "media_clean", "media_label", "media_broad_category", "media_base_label",
  "media_energy_label", "media_antibiotic_label", "media_stressor_label", "oxygen_pct_num",
  "cellCount_num", "correctedCount_num", "areaOccupied_um2_num", "cellSize_um2_num",
  "culture_episode_id", "episode_assignment_status", "previous_episode_id",
  "previous_episode_status", "observation_number", "days_since_seeding",
  "is_terminal_harvest_candidate",
  "row_component_id", "row_component_numeric_id", "row_component_representative_id",
  "row_lineage_depth", "row_root_ancestor_ids",
  "row_parent_count", "row_child_count", "row_ancestor_count", "row_descendant_count",
  "row_is_root", "row_is_leaf", "row_is_branch_point", "row_is_multiparent",
  "has_perspective", "perspective_count", "perspective_types", "perspective_n_values",
  "perspective_n_min", "perspective_n_max", "inferred_assay_labels",
  "has_media", "media_resolved", "malformed_date", "has_invalid_parent_ref",
  "invalid_parent_refs", "row_in_cycle_or_unresolved_depth", "qc_flags"
)]
names(node_output)[names(node_output) == "id_clean"] <- "passage_id"
names(node_output)[names(node_output) == "cellLine_clean"] <- "cellLine"
names(node_output)[names(node_output) == "event_clean"] <- "event"
names(node_output)[names(node_output) == "growthType_clean"] <- "growthType"
names(node_output)[names(node_output) == "parent1_clean"] <- "passaged_from_id1"
names(node_output)[names(node_output) == "parent2_clean"] <- "passaged_from_id2"
names(node_output)[names(node_output) == "media_clean"] <- "media_id"

edge_output <- row_edges[, c(
  "edge_id", "parent_id", "child_id", "parent_slot", "edge_kind", "edge_kind_base",
  "parent_exists", "child_exists", "self_loop", "is_multiparent_edge",
  "parent_culture_episode_id", "child_culture_episode_id",
  "parent_cellLine", "child_cellLine", "parent_event", "child_event",
  "parent_media", "child_media", "parent_date", "child_date", "days_between_parent_child",
  "media_changed", "cellLine_changed", "child_before_parent", "edge_qc_flags"
)]

episode_edges_out <- episode_edges[, c(
  "episode_edge_id", "parent_episode_id", "child_episode_id", "via_harvest_id", "row_edge_id",
  "edge_kind", "parent_episode_exists", "child_episode_exists",
  "parent_cellLine", "child_cellLine", "parent_media", "child_media",
  "via_harvest_date", "child_seeding_date", "days_harvest_to_child_seeding",
  "days_between_episode_events", "media_changed", "cellLine_changed", "is_multiparent_or_mixing",
  "child_before_via_harvest", "child_before_parent_episode_event", "edge_qc_flags"
)]

perspective_origins <- unique(perspective$origin_clean[!is.na(perspective$origin_clean)])
unresolved_media_ids <- setdiff(unique(passaging$media_clean[!is.na(passaging$media_clean)]), media$id_clean)
edge_kind_counts <- table(row_edges$edge_kind_base)
get_count <- function(name) if (name %in% names(edge_kind_counts)) as.integer(edge_kind_counts[name]) else 0L

qc_summary <- data.frame(
  metric = c(
    "passaging_rows", "unique_passaging_nodes", "nodes_with_protocol_id", "media_rows", "perspective_rows",
    "perspective_unique_origins", "perspective_origins_missing_from_passaging",
    "row_edges_total", "row_edges_valid_parent_child", "row_observation_edges",
    "row_propagation_edges", "row_nonstandard_harvest_to_harvest_edges",
    "row_nonstandard_seeding_to_seeding_edges", "row_nonstandard_other_edges",
    "row_missing_parent_edges", "row_self_loop_edges", "row_multiparent_nodes",
    "row_directed_cycle_detected", "culture_episodes", "episode_edges",
    "episode_nonstandard_direct_seeding_to_seeding_edges",
    "episode_multiparent_or_mixing_nodes", "episode_roots", "episode_leaves",
    "episode_branch_points", "episode_directed_cycle_detected",
    "harvest_nodes_missing_or_nonstandard_episode_assignment",
    "episodes_without_harvest_observations", "malformed_passaging_dates",
    "nodes_with_missing_media", "nodes_with_unresolved_media",
    "media_ids_used_but_missing_from_media", "row_edges_child_before_parent_date",
    "episode_edges_child_before_via_harvest_date", "nodes_with_perspective",
    "episodes_with_perspective", "bulk_like_perspective_rows",
    "karyotype_like_perspective_rows", "single_cell_high_throughput_like_perspective_rows",
    "ambiguous_unknown_perspective_rows"
  ),
  value = c(
    nrow(passaging), length(unique(node_ids)), sum(!is.na(passaging$protocol_id)), nrow(media), nrow(perspective),
    length(perspective_origins), length(setdiff(perspective_origins, node_ids)),
    nrow(row_edges), nrow(valid_row_edges), get_count("observation_edge"),
    get_count("propagation_edge"), get_count("nonstandard_harvest_to_harvest"),
    get_count("nonstandard_seeding_to_seeding"), get_count("nonstandard_other"),
    sum(!row_edges$parent_exists), sum(row_edges$self_loop, na.rm = TRUE), sum(row_graph$is_multiparent),
    any(row_graph$has_cycle), nrow(episodes_out), nrow(episode_edges_out),
    sum(grepl("nonstandard_direct_seeding_to_seeding", episode_edges_out$edge_kind), na.rm = TRUE),
    sum(episodes_out$episode_is_multiparent, na.rm = TRUE), sum(episodes_out$episode_is_root, na.rm = TRUE),
    sum(episodes_out$episode_is_leaf, na.rm = TRUE), sum(episodes_out$episode_is_branch_point, na.rm = TRUE),
    any(episode_graph$has_cycle),
    sum(is_harvest & passaging$episode_assignment_status != "assigned_from_single_seeding_parent", na.rm = TRUE),
    sum(episodes_out$harvest_observation_count == 0, na.rm = TRUE),
    sum(nodes$malformed_date, na.rm = TRUE), sum(!nodes$has_media, na.rm = TRUE),
    sum(nodes$has_media & !nodes$media_resolved, na.rm = TRUE), length(unresolved_media_ids),
    sum(row_edges$child_before_parent, na.rm = TRUE),
    sum(episode_edges$child_before_via_harvest, na.rm = TRUE),
    sum(nodes$has_perspective, na.rm = TRUE), sum(episodes_out$perspective_record_count_in_episode > 0, na.rm = TRUE),
    sum(perspective$assay_type_inferred == "bulk-like", na.rm = TRUE),
    sum(perspective$assay_type_inferred == "karyotype-like", na.rm = TRUE),
    sum(perspective$assay_type_inferred == "single-cell/high-throughput-like", na.rm = TRUE),
    sum(perspective$assay_type_inferred == "ambiguous/unknown", na.rm = TRUE)
  ),
  stringsAsFactors = FALSE
)

write.csv(node_output, file.path(out_dir, "annotated_passaging_nodes.csv"), row.names = FALSE, na = "")
write.csv(edge_output, file.path(out_dir, "passaging_edges.csv"), row.names = FALSE, na = "")
write.csv(episodes_out, file.path(out_dir, "culture_episodes.csv"), row.names = FALSE, na = "")
write.csv(episode_edges_out, file.path(out_dir, "culture_episode_edges.csv"), row.names = FALSE, na = "")
write.csv(qc_summary, file.path(out_dir, "metadata_graph_qc_summary.csv"), row.names = FALSE, na = "")

message("Wrote outputs under: ", out_dir)
