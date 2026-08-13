#!/usr/bin/env python3
"""Preview or extract bounded paragraphs from one compressed notebook."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compressed-notebooks-dir", required=True, type=Path)
    parser.add_argument("--notebook-id", required=True)
    parser.add_argument("--paragraph-index", action="append", type=int, default=[])
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--match-all", action="store_true")
    parser.add_argument("--preview-chars", type=int, default=320)
    parser.add_argument("--max-paragraphs", type=int, default=20)
    parser.add_argument("--max-paragraph-chars", type=int, default=5000)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.paragraph_index and args.query:
        raise SystemExit("use --paragraph-index or --query, not both")
    path = args.compressed_notebooks_dir / args.notebook_id / "final_message.json"
    if not path.exists():
        raise SystemExit(f"unknown notebook: {args.notebook_id}")
    value = json.loads(path.read_text(encoding="utf-8"))
    paragraphs = value.get("compressed_text", "").split("\n\n")
    if args.paragraph_index:
        indexes = list(dict.fromkeys(args.paragraph_index))
        invalid = [index for index in indexes if index < 0 or index >= len(paragraphs)]
        if invalid:
            raise SystemExit(f"invalid paragraph indexes: {invalid}")
        mode = "selected_paragraphs"
    elif args.query:
        terms = [term.casefold() for term in args.query]
        indexes = []
        for index, paragraph in enumerate(paragraphs):
            hits = [term in paragraph.casefold() for term in terms]
            if all(hits) if args.match_all else any(hits):
                indexes.append(index)
        indexes = indexes[:args.max_paragraphs]
        mode = "query_matches"
    else:
        indexes = list(range(len(paragraphs)))
        mode = "paragraph_index"

    records = []
    for index in indexes:
        paragraph = paragraphs[index]
        limit = args.preview_chars if mode == "paragraph_index" else args.max_paragraph_chars
        records.append({
            "paragraph_index": index,
            "source_span_markers": sorted(set(re.findall(r"S\d{4}", paragraph))),
            "text": paragraph[:limit],
            "text_truncated": len(paragraph) > limit,
        })
    payload = {
        "schema_version": 1,
        "notebook_id": args.notebook_id,
        "source_path": os.path.abspath(os.fspath(path)),
        "mode": mode,
        "paragraph_count": len(paragraphs),
        "returned_count": len(records),
        "query": args.query,
        "match_all": args.match_all,
        "paragraphs": records,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
