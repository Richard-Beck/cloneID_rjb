#!/usr/bin/env python3
"""Deterministically shortlist coherent spans from canonical exports."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from markdown_database import absolute, classify_span_ids


LINEAGE_RE = re.compile(
    r"^(?P<family>.+?)_(?P<ploidy>2N|4N)_(?P<arm>C|O1|O2)_A(?P<passage>\d+)(?P<suffix>.*)$",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coherent-spans-dir", required=True, type=Path)
    parser.add_argument("--target-span")
    parser.add_argument("--episode-id", action="append", default=[])
    parser.add_argument("--lineage-token", action="append", default=[])
    parser.add_argument("--episode-regex")
    parser.add_argument("--cell-line")
    parser.add_argument("--media-id", action="append", default=[])
    parser.add_argument("--date-start")
    parser.add_argument("--date-end")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def lineage_parts(episode_id: str) -> dict[str, Any] | None:
    match = LINEAGE_RE.match(episode_id)
    if not match:
        return None
    value: dict[str, Any] = {key: val for key, val in match.groupdict().items()}
    value["passage"] = int(value["passage"])
    value["family"] = value["family"].upper()
    value["ploidy"] = value["ploidy"].upper()
    value["arm"] = value["arm"].upper()
    suffix = value["suffix"]
    suffix = re.sub(r"_(?:seed|harvest).*$", "", suffix, flags=re.IGNORECASE).strip("_-").upper()
    value["suffix"] = suffix or None
    return value


def main() -> None:
    args = parse_args()
    root = args.coherent_spans_dir
    spans = {row["coherent_span_id"]: row for row in read_csv(root / "coherent_spans.csv")}
    members_by_span: dict[str, list[dict[str, str]]] = {}
    for row in read_csv(root / "coherent_span_membership.csv"):
        members_by_span.setdefault(row["coherent_span_id"], []).append(row)

    target_members = members_by_span.get(args.target_span, []) if args.target_span else []
    if args.target_span and args.target_span not in spans:
        raise SystemExit(f"unknown target span: {args.target_span}")
    target_parts = [part for row in target_members if (part := lineage_parts(row["episode_id"]))]
    target_families = {part["family"] for part in target_parts}
    target_lineages = {(part["family"], part["ploidy"], part["arm"]) for part in target_parts}
    exact_ids = {value.casefold() for value in args.episode_id}
    tokens = [value.casefold() for value in args.lineage_token]
    pattern = re.compile(args.episode_regex, re.IGNORECASE) if args.episode_regex else None
    start = parse_date(args.date_start)
    end = parse_date(args.date_end)
    media_ids = set(args.media_id)

    results = []
    for span_id, span in spans.items():
        members = members_by_span.get(span_id, [])
        episode_ids = [row["episode_id"] for row in members]
        parts = [part for value in episode_ids if (part := lineage_parts(value))]
        reasons: list[str] = []
        score = 0

        if span_id == args.target_span:
            reasons.append("target_span")
            score += 100
        if exact_ids and any(value.casefold() in exact_ids for value in episode_ids):
            reasons.append("exact_episode_id")
            score += 50
        if tokens and any(token in value.casefold() for token in tokens for value in episode_ids):
            reasons.append("lineage_token")
            score += 30
        if pattern and any(pattern.search(value) for value in episode_ids):
            reasons.append("episode_regex")
            score += 30
        if target_parts:
            lineages = {(part["family"], part["ploidy"], part["arm"], part["suffix"]) for part in parts}
            base_lineages = {(part["family"], part["ploidy"], part["arm"]) for part in parts}
            target_exact = {(part["family"], part["ploidy"], part["arm"], part["suffix"]) for part in target_parts}
            families = {part["family"] for part in parts}
            if lineages & target_exact:
                reasons.append("same_decomposed_lineage")
                score += 25
            elif base_lineages & target_lineages:
                reasons.append("related_derivative_suffix")
                score += 14
            elif families & target_families:
                reasons.append("coordinated_lineage_family")
                score += 15
        if args.cell_line and span.get("cell_lines", "").casefold() == args.cell_line.casefold():
            reasons.append("cell_line")
            score += 5
        elif args.cell_line:
            continue
        if media_ids and span.get("media_id") in media_ids:
            reasons.append("media_id")
            score += 5
        elif media_ids:
            continue

        span_start = parse_date(span.get("span_start_date"))
        span_end = parse_date(span.get("span_end_date"))
        if start or end:
            if span_start is None or span_end is None:
                continue
            if start and span_end < start:
                continue
            if end and span_start > end:
                continue
            reasons.append("date_overlap")
            score += 5

        has_selector = bool(
            args.target_span or exact_ids or tokens or pattern or args.cell_line or media_ids or start or end
        )
        if has_selector and not reasons:
            continue
        if not has_selector:
            raise SystemExit("supply at least one search selector")

        results.append({
            "coherent_span_id": span_id,
            "score": score,
            "reasons": reasons,
            "media_id": span.get("media_id"),
            "cell_lines": span.get("cell_lines"),
            "span_start_date": span.get("span_start_date"),
            "span_end_date": span.get("span_end_date"),
            "episode_count": int(span.get("episode_count") or 0),
            "episode_ids": episode_ids,
            "decomposed_lineages": sorted({
                f"{part['family']}|{part['ploidy']}|{part['arm']}|{part['suffix'] or 'PRIMARY'}" for part in parts
            }),
            "derivative_suffixes": sorted({part["suffix"] for part in parts if part["suffix"]}),
        })

    results.sort(key=lambda item: (-item["score"], item["span_start_date"] or "", item["coherent_span_id"]))
    if args.database:
        states = classify_span_ids(absolute(args.database), {item["coherent_span_id"] for item in results})
        for item in results:
            item["queue_state"] = states[item["coherent_span_id"]]
            item["followup_eligible"] = item["queue_state"] == "unseen"
    payload = {
        "query": {
            "target_span": args.target_span,
            "episode_ids": args.episode_id,
            "lineage_tokens": args.lineage_token,
            "episode_regex": args.episode_regex,
            "cell_line": args.cell_line,
            "media_ids": args.media_id,
            "date_start": args.date_start,
            "date_end": args.date_end,
            "database": str(absolute(args.database)) if args.database else None,
        },
        "result_count": len(results),
        "truncated": False,
        "results": results,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
