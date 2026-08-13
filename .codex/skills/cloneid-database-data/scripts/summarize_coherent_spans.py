#!/usr/bin/env python3
"""Summarize maximal connected spans of culture episodes with one media ID.

A coherent span is a maximal weakly connected component in the culture-episode
graph after retaining only episodes with a known seeding media ID and edges whose
endpoints have the same seeding media ID. Edges are also removed when the child
seed occurs more than a configurable number of days after its immediate parent
harvest (7 days by default). Graph direction is retained in the audit tables but
ignored when finding components.

The script uses only the Python standard library. It writes:

* coherent_spans.csv: one row per coherent span;
* coherent_span_membership.csv: one row per included episode;
* coherent_span_edges.csv: one row per edge internal to a span; and
* coherent_span_run_metadata.json: inputs, definitions, and validation counts.

"Density" cannot be literal without vessel area or volume. Accordingly, the
primary quantity summaries use preferred counts (correctedCount when valid,
otherwise cellCount). Terminal cells/um2 is also reported when terminal area is
available; no equivalent seeding denominator exists in the canonical tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_EPISODES = Path("data/culture_episodes.csv")
DEFAULT_EDGES = Path("data/culture_episode_edges.csv")
DEFAULT_NODES = Path("data/annotated_passaging_nodes.csv")
DEFAULT_OUTPUT_DIR = Path("data/coherent_spans")
DEFAULT_MAX_PARENT_GAP_DAYS = 7.0
QUANTILE_PROBABILITIES = (0.0, 0.25, 0.5, 0.75, 1.0)
QUANTILE_NAMES = ("min", "q25", "median", "q75", "max")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    parser.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--max-parent-gap-days",
        type=float,
        default=DEFAULT_MAX_PARENT_GAP_DAYS,
        help=(
            "Split spans by removing an episode edge when the child seed occurs "
            "more than this many days after its immediate parent harvest "
            f"(default: {DEFAULT_MAX_PARENT_GAP_DAYS:g})."
        ),
    )
    parser.add_argument(
        "--missing-media-mode",
        choices=("exclude", "singleton"),
        default="exclude",
        help=(
            "Exclude episodes with missing media (default), or emit each as its "
            "own singleton. Missing media episodes are never connected together."
        ),
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def require_columns(path: Path, rows: list[dict[str, str]], columns: Iterable[str]) -> None:
    if not rows:
        raise ValueError(f"{path} contains no data rows")
    missing = sorted(set(columns) - set(rows[0]))
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_number(value: object) -> Optional[float]:
    text = clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def nonnegative_number(value: object) -> Optional[float]:
    number = parse_number(value)
    return number if number is not None and number >= 0 else None


def positive_number(value: object) -> Optional[float]:
    number = parse_number(value)
    return number if number is not None and number > 0 else None


def preferred_count(corrected: object, raw: object) -> tuple[Optional[float], str]:
    corrected_value = nonnegative_number(corrected)
    if corrected_value is not None:
        return corrected_value, "correctedCount"
    raw_value = nonnegative_number(raw)
    if raw_value is not None:
        return raw_value, "cellCount"
    return None, ""


def parse_date(value: object) -> Optional[datetime]:
    text = clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_date(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    if value.hour == value.minute == value.second == value.microsecond == 0:
        return value.date().isoformat()
    return value.isoformat().replace("+00:00", "Z")


def format_number(value: object) -> object:
    if value is None:
        return ""
    number = float(value)
    if number == 0:
        return 0
    return f"{number:.12g}"


def quantile_type7(sorted_values: list[float], probability: float) -> float:
    """R type-7 / NumPy-style linearly interpolated sample quantile."""
    if not sorted_values:
        raise ValueError("cannot calculate a quantile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def distribution_fields(
    prefix: str,
    values: Iterable[Optional[float]],
    total_expected: int,
    negative_count: int = 0,
) -> dict[str, object]:
    valid = sorted(float(value) for value in values if value is not None and math.isfinite(value))
    fields: dict[str, object] = {
        f"{prefix}_n_valid": len(valid),
        f"{prefix}_n_missing_or_invalid": total_expected - len(valid) - negative_count,
        f"{prefix}_n_negative_excluded": negative_count,
    }
    for name, probability in zip(QUANTILE_NAMES, QUANTILE_PROBABILITIES):
        fields[f"{prefix}_{name}"] = (
            format_number(quantile_type7(valid, probability)) if valid else ""
        )
    return fields


def safe_identifier(value: str) -> str:
    identifier = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return identifier or "unknown"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "T", "1", "YES", "Y"}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if not math.isfinite(args.max_parent_gap_days) or args.max_parent_gap_days < 0:
        raise ValueError("--max-parent-gap-days must be a finite nonnegative number")

    episodes = read_csv(args.episodes)
    edges = read_csv(args.edges)
    nodes = read_csv(args.nodes)

    require_columns(
        args.episodes,
        episodes,
        (
            "episode_id",
            "cellLine",
            "seeding_date",
            "seeding_media_id",
            "seeding_media_label",
            "media_broad_category",
            "seeding_cellCount",
            "seeding_correctedCount",
            "harvest_observation_count",
            "last_harvest_date",
            "terminal_harvest_candidate",
            "episode_duration_days",
            "episode_is_branch_point",
            "episode_is_multiparent",
            "qc_flags",
        ),
    )
    require_columns(
        args.edges,
        edges,
        (
            "episode_edge_id",
            "parent_episode_id",
            "child_episode_id",
            "edge_kind",
            "days_harvest_to_child_seeding",
            "is_multiparent_or_mixing",
            "edge_qc_flags",
        ),
    )
    require_columns(
        args.nodes,
        nodes,
        (
            "passage_id",
            "event",
            "culture_episode_id",
            "cellCount_num",
            "correctedCount_num",
            "areaOccupied_um2_num",
        ),
    )

    episode_by_id: dict[str, dict[str, str]] = {}
    for episode in episodes:
        episode_id = clean(episode["episode_id"])
        if not episode_id:
            raise ValueError("culture_episodes.csv contains a blank episode_id")
        if episode_id in episode_by_id:
            raise ValueError(f"duplicate episode_id: {episode_id}")
        episode_by_id[episode_id] = episode

    entry_count: Counter[str] = Counter()
    node_by_id: dict[str, dict[str, str]] = {}
    for node in nodes:
        passage_id = clean(node["passage_id"])
        if passage_id:
            if passage_id in node_by_id:
                raise ValueError(f"duplicate passage_id: {passage_id}")
            node_by_id[passage_id] = node
        episode_id = clean(node["culture_episode_id"])
        if episode_id in episode_by_id and clean(node["event"]) in {"seeding", "harvest"}:
            entry_count[episode_id] += 1

    known_media_ids = {
        episode_id
        for episode_id, episode in episode_by_id.items()
        if clean(episode["seeding_media_id"])
    }
    included_ids = set(known_media_ids)
    if args.missing_media_mode == "singleton":
        included_ids.update(episode_by_id)

    adjacency: dict[str, set[str]] = {episode_id: set() for episode_id in included_ids}
    eligible_edges: list[dict[str, str]] = []
    same_media_edges = 0
    temporal_gap_edges_excluded = 0
    unknown_gap_edges_retained = 0
    for edge in edges:
        parent_id = clean(edge["parent_episode_id"])
        child_id = clean(edge["child_episode_id"])
        if parent_id not in known_media_ids or child_id not in known_media_ids:
            continue
        parent_media = clean(episode_by_id[parent_id]["seeding_media_id"])
        child_media = clean(episode_by_id[child_id]["seeding_media_id"])
        if parent_media != child_media:
            continue
        same_media_edges += 1
        parent_gap_days = parse_number(edge["days_harvest_to_child_seeding"])
        if parent_gap_days is not None and parent_gap_days > args.max_parent_gap_days:
            temporal_gap_edges_excluded += 1
            continue
        if parent_gap_days is None:
            unknown_gap_edges_retained += 1
        adjacency[parent_id].add(child_id)
        adjacency[child_id].add(parent_id)
        eligible_edges.append(edge)

    components: list[set[str]] = []
    unseen = set(included_ids)
    while unseen:
        start = min(unseen)
        component: set[str] = set()
        queue = deque([start])
        unseen.remove(start)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        components.append(component)

    def component_sort_key(component: set[str]) -> tuple[str, datetime, str]:
        representative = min(component)
        media_id = clean(episode_by_id[representative]["seeding_media_id"])
        dates = [
            parse_date(episode_by_id[episode_id]["seeding_date"])
            for episode_id in component
        ]
        valid_dates = [date for date in dates if date is not None]
        earliest = min(valid_dates) if valid_dates else datetime.max.replace(tzinfo=timezone.utc)
        return media_id, earliest, representative

    components.sort(key=component_sort_key)
    media_span_counter: Counter[str] = Counter()
    span_by_episode: dict[str, str] = {}
    for component in components:
        representative = min(component)
        media_id = clean(episode_by_id[representative]["seeding_media_id"])
        counter_key = media_id or "__missing__"
        media_span_counter[counter_key] += 1
        span_id = (
            f"media_{safe_identifier(media_id)}__span_{media_span_counter[counter_key]:04d}"
            if media_id
            else f"missing_media__episode_{safe_identifier(representative)}"
        )
        for episode_id in component:
            span_by_episode[episode_id] = span_id

    edges_by_span: dict[str, list[dict[str, str]]] = defaultdict(list)
    for edge in eligible_edges:
        parent_id = clean(edge["parent_episode_id"])
        child_id = clean(edge["child_episode_id"])
        parent_span = span_by_episode[parent_id]
        child_span = span_by_episode[child_id]
        if parent_span != child_span:
            raise AssertionError("eligible same-media edge crosses coherent spans")
        edges_by_span[parent_span].append(edge)

    members_by_span: dict[str, list[str]] = defaultdict(list)
    for episode_id, span_id in span_by_episode.items():
        members_by_span[span_id].append(episode_id)

    summary_rows: list[dict[str, object]] = []
    membership_rows: list[dict[str, object]] = []
    edge_rows: list[dict[str, object]] = []

    for component in components:
        episode_ids = sorted(component)
        span_id = span_by_episode[episode_ids[0]]
        span_edges = edges_by_span.get(span_id, [])
        span_episodes = [episode_by_id[episode_id] for episode_id in episode_ids]
        protocol_ids = sorted({
            clean(row.get("seeding_protocol_id", ""))
            for row in span_episodes
            if clean(row.get("seeding_protocol_id", ""))
        })
        media_ids = sorted({clean(row["seeding_media_id"]) for row in span_episodes})
        if len(media_ids) != 1:
            raise AssertionError(f"{span_id} contains multiple media IDs: {media_ids}")
        media_id = media_ids[0]

        indegree: Counter[str] = Counter()
        outdegree: Counter[str] = Counter()
        for edge in span_edges:
            outdegree[clean(edge["parent_episode_id"])] += 1
            indegree[clean(edge["child_episode_id"])] += 1

        episode_metrics: dict[str, dict[str, object]] = {}
        for episode_id in episode_ids:
            episode = episode_by_id[episode_id]
            terminal_id = clean(episode["terminal_harvest_candidate"])
            terminal = node_by_id.get(terminal_id)
            terminal_count, terminal_count_source = (
                preferred_count(terminal["correctedCount_num"], terminal["cellCount_num"])
                if terminal is not None
                else (None, "")
            )
            terminal_area = (
                positive_number(terminal["areaOccupied_um2_num"])
                if terminal is not None
                else None
            )
            terminal_cells_per_um2 = (
                terminal_count / terminal_area
                if terminal_count is not None and terminal_area is not None
                else None
            )
            seeding_count, seeding_count_source = preferred_count(
                episode["seeding_correctedCount"], episode["seeding_cellCount"]
            )
            duration_raw = parse_number(episode["episode_duration_days"])
            episode_metrics[episode_id] = {
                "passaging_entry_count": float(entry_count[episode_id]),
                "seeding_count": seeding_count,
                "seeding_count_source": seeding_count_source,
                "terminal_count": terminal_count,
                "terminal_count_source": terminal_count_source,
                "terminal_area_um2": terminal_area,
                "terminal_cells_per_um2": terminal_cells_per_um2,
                "duration_raw": duration_raw,
                "duration": duration_raw if duration_raw is not None and duration_raw >= 0 else None,
            }

        start_dates = [parse_date(row["seeding_date"]) for row in span_episodes]
        end_dates = [
            parse_date(row["last_harvest_date"]) or parse_date(row["seeding_date"])
            for row in span_episodes
        ]
        valid_starts = [date for date in start_dates if date is not None]
        valid_ends = [date for date in end_dates if date is not None]
        span_start = min(valid_starts) if valid_starts else None
        span_end = max(valid_ends) if valid_ends else None
        span_duration = (
            (span_end - span_start).total_seconds() / 86400
            if span_start is not None and span_end is not None and span_end >= span_start
            else None
        )

        gap_raw = [parse_number(edge["days_harvest_to_child_seeding"]) for edge in span_edges]
        # Timestamps may not be tightly anchored to measurement events. Retain
        # signed observations rather than assuming precise same-day ordering;
        # negativity is descriptive, not automatically invalid.
        valid_gaps = [value for value in gap_raw if value is not None]
        negative_gaps = sum(value is not None and value < 0 for value in gap_raw)
        durations_raw = [episode_metrics[x]["duration_raw"] for x in episode_ids]
        negative_durations = sum(
            value is not None and float(value) < 0 for value in durations_raw
        )

        media_labels = sorted({clean(row["seeding_media_label"]) for row in span_episodes if clean(row["seeding_media_label"])})
        media_categories = sorted({clean(row["media_broad_category"]) for row in span_episodes if clean(row["media_broad_category"])})
        cell_lines = sorted({clean(row["cellLine"]) for row in span_episodes if clean(row["cellLine"])})
        qc_episode_count = sum(bool(clean(row["qc_flags"])) for row in span_episodes)
        qc_edge_count = sum(bool(clean(edge["edge_qc_flags"])) for edge in span_edges)
        nonstandard_edge_count = sum(clean(edge["edge_kind"]) != "propagation_edge" for edge in span_edges)

        summary: dict[str, object] = {
            "coherent_span_id": span_id,
            "media_id": media_id,
            "seeding_protocol_ids": "|".join(protocol_ids),
            "seeding_protocol_count": len(protocol_ids),
            "media_labels": "|".join(media_labels),
            "media_broad_categories": "|".join(media_categories),
            "cell_lines": "|".join(cell_lines),
            "cell_line_count": len(cell_lines),
            "episode_count": len(episode_ids),
            "internal_edge_count": len(span_edges),
            "root_count_within_span": sum(indegree[x] == 0 for x in episode_ids),
            "leaf_count_within_span": sum(outdegree[x] == 0 for x in episode_ids),
            "branch_point_count_within_span": sum(outdegree[x] > 1 for x in episode_ids),
            "merge_point_count_within_span": sum(indegree[x] > 1 for x in episode_ids),
            "nonstandard_edge_count": nonstandard_edge_count,
            "multiparent_or_mixing_edge_count": sum(
                truthy(edge["is_multiparent_or_mixing"]) for edge in span_edges
            ),
            "episode_qc_flag_count": qc_episode_count,
            "edge_qc_flag_count": qc_edge_count,
            "span_start_date": format_date(span_start),
            "span_end_date": format_date(span_end),
            "span_calendar_duration_days": format_number(span_duration),
        }
        summary.update(
            distribution_fields(
                "passaging_entries_per_episode",
                [episode_metrics[x]["passaging_entry_count"] for x in episode_ids],
                len(episode_ids),
            )
        )
        summary.update(
            distribution_fields(
                "episode_duration_days",
                [episode_metrics[x]["duration"] for x in episode_ids],
                len(episode_ids),
                negative_durations,
            )
        )
        summary.update(
            distribution_fields(
                "inter_episode_gap_days",
                valid_gaps,
                len(span_edges),
            )
        )
        summary["inter_episode_gap_days_n_negative_observed"] = negative_gaps
        summary.update(
            distribution_fields(
                "seeding_preferred_count",
                [episode_metrics[x]["seeding_count"] for x in episode_ids],
                len(episode_ids),
            )
        )
        summary.update(
            distribution_fields(
                "terminal_harvest_preferred_count",
                [episode_metrics[x]["terminal_count"] for x in episode_ids],
                len(episode_ids),
            )
        )
        summary.update(
            distribution_fields(
                "terminal_harvest_area_um2",
                [episode_metrics[x]["terminal_area_um2"] for x in episode_ids],
                len(episode_ids),
            )
        )
        summary.update(
            distribution_fields(
                "terminal_harvest_cells_per_um2",
                [episode_metrics[x]["terminal_cells_per_um2"] for x in episode_ids],
                len(episode_ids),
            )
        )
        summary_rows.append(summary)

        for episode_id in episode_ids:
            episode = episode_by_id[episode_id]
            metrics = episode_metrics[episode_id]
            membership_rows.append(
                {
                    "coherent_span_id": span_id,
                    "episode_id": episode_id,
                    "seeding_protocol_id": clean(
                        episode.get("seeding_protocol_id", "")
                    ),
                    "media_id": media_id,
                    "cellLine": clean(episode["cellLine"]),
                    "seeding_date": clean(episode["seeding_date"]),
                    "last_harvest_date": clean(episode["last_harvest_date"]),
                    "episode_duration_days": format_number(metrics["duration_raw"]),
                    "passaging_entry_count": int(metrics["passaging_entry_count"]),
                    "harvest_observation_count_reported": clean(episode["harvest_observation_count"]),
                    "seeding_preferred_count": format_number(metrics["seeding_count"]),
                    "seeding_preferred_count_source": metrics["seeding_count_source"],
                    "terminal_harvest_candidate": clean(episode["terminal_harvest_candidate"]),
                    "terminal_harvest_preferred_count": format_number(metrics["terminal_count"]),
                    "terminal_harvest_preferred_count_source": metrics["terminal_count_source"],
                    "terminal_harvest_area_um2": format_number(metrics["terminal_area_um2"]),
                    "terminal_harvest_cells_per_um2": format_number(metrics["terminal_cells_per_um2"]),
                    "internal_parent_count": indegree[episode_id],
                    "internal_child_count": outdegree[episode_id],
                    "episode_qc_flags": clean(episode["qc_flags"]),
                }
            )

        for edge in sorted(
            span_edges,
            key=lambda row: (
                clean(row["parent_episode_id"]),
                clean(row["child_episode_id"]),
                clean(row["episode_edge_id"]),
            ),
        ):
            gap = parse_number(edge["days_harvest_to_child_seeding"])
            edge_rows.append(
                {
                    "coherent_span_id": span_id,
                    "episode_edge_id": clean(edge["episode_edge_id"]),
                    "parent_episode_id": clean(edge["parent_episode_id"]),
                    "child_episode_id": clean(edge["child_episode_id"]),
                    "media_id": media_id,
                    "edge_kind": clean(edge["edge_kind"]),
                    "days_harvest_to_child_seeding": format_number(gap),
                    "negative_gap": "TRUE" if gap is not None and gap < 0 else "FALSE",
                    "is_multiparent_or_mixing": clean(edge["is_multiparent_or_mixing"]),
                    "edge_qc_flags": clean(edge["edge_qc_flags"]),
                }
            )

    summary_rows.sort(key=lambda row: clean(row["coherent_span_id"]))
    membership_rows.sort(key=lambda row: (clean(row["coherent_span_id"]), clean(row["episode_id"])))
    edge_rows.sort(
        key=lambda row: (
            clean(row["coherent_span_id"]),
            clean(row["parent_episode_id"]),
            clean(row["child_episode_id"]),
        )
    )

    if len(membership_rows) != len(included_ids):
        raise AssertionError("not every included episode was assigned exactly once")
    if len({clean(row["episode_id"]) for row in membership_rows}) != len(membership_rows):
        raise AssertionError("an episode was assigned to more than one coherent span")
    if len(edge_rows) != len(eligible_edges):
        raise AssertionError("not every eligible edge was assigned exactly once")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "coherent_spans.csv", summary_rows)
    write_csv(args.output_dir / "coherent_span_membership.csv", membership_rows)
    # There should normally be eligible edges, but keep the script well-defined for
    # tiny test inputs containing only singleton spans.
    if edge_rows:
        write_csv(args.output_dir / "coherent_span_edges.csv", edge_rows)
    else:
        with (args.output_dir / "coherent_span_edges.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            csv.writer(handle).writerow(
                [
                    "coherent_span_id",
                    "episode_edge_id",
                    "parent_episode_id",
                    "child_episode_id",
                    "media_id",
                    "edge_kind",
                    "days_harvest_to_child_seeding",
                    "negative_gap",
                    "is_multiparent_or_mixing",
                    "edge_qc_flags",
                ]
            )

    metadata = {
        "definition": (
            "A maximal weakly connected component after retaining episodes with a "
            "known seeding media ID and episode edges whose endpoints share that ID, "
            "then removing edges where the child seed occurs more than the configured "
            "maximum number of days after its immediate parent harvest."
        ),
        "graph_direction_for_components": "ignored (weak connectivity)",
        "max_parent_gap_days": args.max_parent_gap_days,
        "temporal_edge_policy": (
            "Remove an otherwise eligible same-media edge only when its parseable "
            "days_harvest_to_child_seeding value is strictly greater than "
            "max_parent_gap_days. Boundary, negative, and missing/unparseable values "
            "are retained."
        ),
        "missing_media_mode": args.missing_media_mode,
        "quantile_method": "R type 7 linear interpolation",
        "negative_duration_policy": "excluded from duration quantiles and counted",
        "inter_episode_gap_policy": (
            "All parseable signed values are retained in quantiles. Negative values "
            "are counted separately and are not automatically treated as invalid. "
            "Recorded days are used unless records clearly conflict, but precise "
            "same-day ordering is not assumed."
        ),
        "preferred_count_policy": (
            "nonnegative correctedCount when available, otherwise nonnegative cellCount"
        ),
        "density_limitation": (
            "No vessel area/volume is available for seeding. Preferred counts are "
            "reported; terminal cells/um2 is derived only when terminal area exists."
        ),
        "span_duration_definition": (
            "earliest episode seeding date through latest episode last-harvest date"
        ),
        "input_files": {
            "episodes": str(args.episodes),
            "edges": str(args.edges),
            "nodes": str(args.nodes),
        },
        "counts": {
            "input_episodes": len(episodes),
            "known_media_episodes": len(known_media_ids),
            "missing_media_episodes": len(episodes) - len(known_media_ids),
            "included_episodes": len(included_ids),
            "excluded_episodes": len(episodes) - len(included_ids),
            "coherent_spans": len(summary_rows),
            "same_media_edges_before_temporal_filter": same_media_edges,
            "temporal_gap_edges_excluded": temporal_gap_edges_excluded,
            "unknown_gap_edges_retained": unknown_gap_edges_retained,
            "internal_same_media_edges": len(edge_rows),
            "singleton_spans": sum(int(row["episode_count"]) == 1 for row in summary_rows),
        },
        "validation": {
            "each_included_episode_assigned_once": True,
            "each_internal_edge_assigned_once": True,
            "every_span_has_exactly_one_media_id": True,
        },
    }
    with (args.output_dir / "coherent_span_run_metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(
        f"Wrote {len(summary_rows)} coherent spans covering {len(membership_rows)} "
        f"episodes to {args.output_dir}"
    )


if __name__ == "__main__":
    main()
