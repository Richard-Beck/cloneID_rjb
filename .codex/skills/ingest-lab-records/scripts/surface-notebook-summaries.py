#!/usr/bin/env python3
"""Surface all short notebook summaries or medium summaries for selected notebooks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("summaries", type=Path)
    parser.add_argument("--notebook-id", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = json.loads(args.summaries.read_text(encoding="utf-8"))
    records = source.get("notebook_summaries") if isinstance(source, dict) else None
    if not isinstance(records, list):
        raise SystemExit("summaries file must contain notebook_summaries array")
    by_id = {item.get("notebook_id"): item for item in records if isinstance(item, dict)}
    if len(by_id) != len(records) or None in by_id:
        raise SystemExit("notebook IDs must be present and unique")

    if args.notebook_id:
        unknown = sorted(set(args.notebook_id) - set(by_id))
        if unknown:
            raise SystemExit(f"unknown notebook IDs: {', '.join(unknown)}")
        selected = [by_id[value] for value in dict.fromkeys(args.notebook_id)]
        payload = {
            "schema_version": 1,
            "view": "selected_medium_detailed_summaries",
            "notebook_count": len(selected),
            "notebooks": [
                {
                    "notebook_id": item["notebook_id"],
                    "notebook_name": item["notebook_name"],
                    "short_summary": item["short_summary"],
                    "medium_detailed_summary": item["medium_detailed_summary"],
                }
                for item in selected
            ],
        }
    else:
        ordered = sorted(records, key=lambda item: item["notebook_id"])
        payload = {
            "schema_version": 1,
            "view": "all_short_summaries",
            "notebook_count": len(ordered),
            "notebooks": [
                {
                    "notebook_id": item["notebook_id"],
                    "notebook_name": item["notebook_name"],
                    "short_summary": item["short_summary"],
                }
                for item in ordered
            ],
        }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
