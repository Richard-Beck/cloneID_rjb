#!/usr/bin/env python3
"""Compute deterministic episode-graph distances between coherent culture spans.

For distinct spans A and B, distance(A, B) is the minimum number of episode
graph edges in a path from any episode in A to any episode in B. Directed mode
follows parent-to-child edges; undirected mode permits traversal in either
direction. Unclassified episodes (for example, missing-media episodes) remain
available as intermediate graph nodes.

For each requested mode the script writes a dense distance matrix and a sparse
table of reachable ordered span pairs. The sparse table includes one
deterministically selected shortest path and path-level QC information.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_EPISODES = Path("data/culture_episodes.csv")
DEFAULT_EDGES = Path("data/culture_episode_edges.csv")
DEFAULT_MEMBERSHIP = Path("data/coherent_spans/coherent_span_membership.csv")
DEFAULT_OUTPUT_DIR = Path("data/coherent_span_distances")
MODES = ("directed", "undirected")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    parser.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    parser.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=MODES,
        default=list(MODES),
        help="Traversal modes to produce (default: directed undirected).",
    )
    return parser.parse_args()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_number(value: object) -> Optional[float]:
    text = clean(value)
    if not text:
        return None
    try:
        value_float = float(text)
    except ValueError:
        return None
    return value_float if math.isfinite(value_float) else None


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "T", "1", "YES", "Y"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def require_columns(path: Path, rows: list[dict[str, str]], columns: Iterable[str]) -> None:
    if not rows:
        raise ValueError(f"{path} contains no data rows")
    missing = sorted(set(columns) - set(rows[0]))
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def collapse_consecutive(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not result or value != result[-1]:
            result.append(value)
    return result


def reconstruct_path(
    endpoint: str,
    predecessor: dict[str, tuple[str, int, str]],
) -> tuple[list[str], list[int], list[str]]:
    nodes = [endpoint]
    edge_indices: list[int] = []
    directions: list[str] = []
    current = endpoint
    while current in predecessor:
        previous, edge_index, direction = predecessor[current]
        nodes.append(previous)
        edge_indices.append(edge_index)
        directions.append(direction)
        current = previous
    nodes.reverse()
    edge_indices.reverse()
    directions.reverse()
    return nodes, edge_indices, directions


def build_adjacency(
    episode_ids: set[str],
    edges: list[dict[str, str]],
    mode: str,
) -> tuple[dict[str, list[tuple[str, int, str]]], list[int]]:
    adjacency: dict[str, list[tuple[str, int, str]]] = {
        episode_id: [] for episode_id in episode_ids
    }
    valid_edge_indices: list[int] = []
    for edge_index, edge in enumerate(edges):
        parent = clean(edge["parent_episode_id"])
        child = clean(edge["child_episode_id"])
        if parent not in episode_ids or child not in episode_ids:
            continue
        valid_edge_indices.append(edge_index)
        adjacency[parent].append((child, edge_index, "forward"))
        if mode == "undirected":
            adjacency[child].append((parent, edge_index, "reverse"))
    for episode_id in adjacency:
        adjacency[episode_id].sort(
            key=lambda item: (
                item[0],
                clean(edges[item[1]]["episode_edge_id"]),
                item[2],
            )
        )
    return adjacency, valid_edge_indices


def calculate_mode(
    mode: str,
    output_dir: Path,
    spans: list[str],
    members_by_span: dict[str, list[str]],
    span_by_episode: dict[str, str],
    episode_by_id: dict[str, dict[str, str]],
    edges: list[dict[str, str]],
) -> dict[str, object]:
    started = time.perf_counter()
    adjacency, valid_edge_indices = build_adjacency(set(episode_by_id), edges, mode)
    matrix_rows: list[dict[str, object]] = []
    sparse_rows: list[dict[str, object]] = []
    distance_histogram: dict[int, int] = defaultdict(int)

    for source_span in spans:
        source_members = sorted(members_by_span[source_span])
        distance = {episode_id: 0 for episode_id in source_members}
        predecessor: dict[str, tuple[str, int, str]] = {}
        queue = deque(source_members)

        while queue:
            current = queue.popleft()
            for neighbor, edge_index, direction in adjacency[current]:
                if neighbor in distance:
                    continue
                distance[neighbor] = distance[current] + 1
                predecessor[neighbor] = (current, edge_index, direction)
                queue.append(neighbor)

        best_target: dict[str, tuple[int, str]] = {}
        for episode_id, episode_distance in distance.items():
            target_span = span_by_episode.get(episode_id)
            if target_span is None or target_span == source_span:
                continue
            candidate = (episode_distance, episode_id)
            if target_span not in best_target or candidate < best_target[target_span]:
                best_target[target_span] = candidate

        matrix_row: dict[str, object] = {"source_span_id": source_span}
        for target_span in spans:
            if target_span == source_span:
                matrix_row[target_span] = 0
            elif target_span in best_target:
                matrix_row[target_span] = best_target[target_span][0]
            else:
                matrix_row[target_span] = "NA"
        matrix_rows.append(matrix_row)

        for target_span in spans:
            if target_span not in best_target:
                continue
            edge_distance, endpoint = best_target[target_span]
            path_nodes, path_edge_indices, step_directions = reconstruct_path(
                endpoint, predecessor
            )
            if len(path_edge_indices) != edge_distance:
                raise AssertionError("reconstructed path length differs from BFS distance")
            if span_by_episode.get(path_nodes[0]) != source_span:
                raise AssertionError("shortest path does not begin in the source span")
            if span_by_episode.get(path_nodes[-1]) != target_span:
                raise AssertionError("shortest path does not end in the target span")

            path_edges = [edges[index] for index in path_edge_indices]
            path_span_labels = [
                span_by_episode.get(episode_id, "UNCLASSIFIED")
                for episode_id in path_nodes
            ]
            path_media_ids = [
                clean(episode_by_id[episode_id]["seeding_media_id"]) or "NA"
                for episode_id in path_nodes
            ]
            internal_nodes = path_nodes[1:-1]
            nonstandard_edge_count = sum(
                clean(edge["edge_kind"]).split("|")[0] != "propagation_edge"
                for edge in path_edges
            )
            negative_gap_count = sum(
                (value := parse_number(edge["days_harvest_to_child_seeding"]))
                is not None
                and value < 0
                for edge in path_edges
            )
            distance_histogram[edge_distance] += 1
            sparse_rows.append(
                {
                    "source_span_id": source_span,
                    "target_span_id": target_span,
                    "min_edge_distance": edge_distance,
                    "min_intermediate_episode_count": max(edge_distance - 1, 0),
                    "min_path_node_count": edge_distance + 1,
                    "source_boundary_episode_id": path_nodes[0],
                    "target_boundary_episode_id": path_nodes[-1],
                    "path_episode_ids": ">".join(path_nodes),
                    "path_episode_span_ids": ">".join(path_span_labels),
                    "span_transition_path": ">".join(
                        collapse_consecutive(path_span_labels)
                    ),
                    "path_media_ids": ">".join(path_media_ids),
                    "path_step_directions": ">".join(step_directions),
                    "reverse_edge_traversal_count": sum(
                        direction == "reverse" for direction in step_directions
                    ),
                    "unclassified_intermediate_episode_count": sum(
                        episode_id not in span_by_episode for episode_id in internal_nodes
                    ),
                    "nonstandard_edge_count": nonstandard_edge_count,
                    "multiparent_or_mixing_edge_count": sum(
                        truthy(edge["is_multiparent_or_mixing"])
                        for edge in path_edges
                    ),
                    "edge_qc_flag_count": sum(
                        bool(clean(edge["edge_qc_flags"])) for edge in path_edges
                    ),
                    "negative_timestamp_gap_edge_count": negative_gap_count,
                }
            )

    matrix_path = output_dir / f"{mode}_span_distance_matrix.csv"
    sparse_path = output_dir / f"{mode}_reachable_span_pairs.csv"
    write_csv(matrix_path, matrix_rows)
    write_csv(sparse_path, sparse_rows)

    expected_cells = len(spans) * (len(spans) - 1)
    if len(sparse_rows) != sum(distance_histogram.values()):
        raise AssertionError("reachable-pair count differs from distance histogram")
    if any(int(row["min_edge_distance"]) < 1 for row in sparse_rows):
        raise AssertionError("a distinct reachable span pair has distance below one")

    return {
        "mode": mode,
        "definition": (
            "minimum episode-edge count from any source-span episode to any "
            "target-span episode"
        ),
        "direction_policy": (
            "parent-to-child only"
            if mode == "directed"
            else "parent-child edges traversable in either direction"
        ),
        "span_count": len(spans),
        "matrix_cell_count_including_diagonal": len(spans) ** 2,
        "possible_ordered_pairs_excluding_diagonal": expected_cells,
        "reachable_ordered_pairs": len(sparse_rows),
        "unreachable_ordered_pairs": expected_cells - len(sparse_rows),
        "reachable_fraction": len(sparse_rows) / expected_cells if expected_cells else 0,
        "maximum_edge_distance": max(distance_histogram, default=0),
        "distance_histogram": {
            str(key): distance_histogram[key] for key in sorted(distance_histogram)
        },
        "valid_episode_edge_count": len(valid_edge_indices),
        "runtime_seconds": time.perf_counter() - started,
        "dense_matrix": str(matrix_path),
        "sparse_reachable_pairs": str(sparse_path),
    }


def main() -> None:
    args = parse_args()
    episodes = read_csv(args.episodes)
    edges = read_csv(args.edges)
    membership = read_csv(args.membership)
    require_columns(
        args.episodes,
        episodes,
        ("episode_id", "seeding_media_id"),
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
        args.membership,
        membership,
        ("coherent_span_id", "episode_id", "media_id"),
    )

    episode_by_id: dict[str, dict[str, str]] = {}
    for episode in episodes:
        episode_id = clean(episode["episode_id"])
        if not episode_id:
            raise ValueError("blank episode_id in episode table")
        if episode_id in episode_by_id:
            raise ValueError(f"duplicate episode_id: {episode_id}")
        episode_by_id[episode_id] = episode

    members_by_span: dict[str, list[str]] = defaultdict(list)
    span_by_episode: dict[str, str] = {}
    media_by_span: dict[str, set[str]] = defaultdict(set)
    for member in membership:
        span_id = clean(member["coherent_span_id"])
        episode_id = clean(member["episode_id"])
        if not span_id or not episode_id:
            raise ValueError("blank coherent_span_id or episode_id in membership table")
        if episode_id not in episode_by_id:
            raise ValueError(f"membership episode absent from episode table: {episode_id}")
        if episode_id in span_by_episode:
            raise ValueError(f"episode belongs to multiple spans: {episode_id}")
        span_by_episode[episode_id] = span_id
        members_by_span[span_id].append(episode_id)
        media_by_span[span_id].add(clean(member["media_id"]))
    for span_id, media_ids in media_by_span.items():
        if len(media_ids) != 1 or "" in media_ids:
            raise ValueError(f"span does not have exactly one known media ID: {span_id}")

    spans = sorted(members_by_span)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    mode_results = [
        calculate_mode(
            mode,
            args.output_dir,
            spans,
            members_by_span,
            span_by_episode,
            episode_by_id,
            edges,
        )
        for mode in dict.fromkeys(args.modes)
    ]
    metadata = {
        "distance_units": "episode graph edges",
        "unreachable_dense_value": "NA",
        "diagonal_dense_value": 0,
        "endpoint_policy": (
            "source and target spans are sets; choose the minimum over all endpoint "
            "episode pairs"
        ),
        "intermediate_node_policy": (
            "all episodes with valid graph endpoints may be traversed, including "
            "episodes absent from coherent-span membership"
        ),
        "tie_breaking": (
            "lexicographically sorted source episodes, neighbors, and target episodes"
        ),
        "input_files": {
            "episodes": str(args.episodes),
            "edges": str(args.edges),
            "membership": str(args.membership),
        },
        "counts": {
            "episode_nodes": len(episode_by_id),
            "span_member_episodes": len(span_by_episode),
            "unclassified_episode_nodes": len(episode_by_id) - len(span_by_episode),
            "coherent_spans": len(spans),
            "input_episode_edges": len(edges),
        },
        "mode_results": mode_results,
        "validation": {
            "each_member_episode_has_exactly_one_span": True,
            "each_span_has_exactly_one_known_media_id": True,
            "all_witness_lengths_match_reported_distances": True,
        },
    }
    with (args.output_dir / "span_distance_run_metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")

    descriptions = ", ".join(
        f"{result['mode']}={result['reachable_ordered_pairs']} reachable pairs"
        for result in mode_results
    )
    print(f"Wrote span distances for {len(spans)} spans: {descriptions}")


if __name__ == "__main__":
    main()
