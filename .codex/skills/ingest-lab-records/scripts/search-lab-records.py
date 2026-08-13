#!/usr/bin/env python3
"""Search literals and date ranges across compressed notebooks and CSV records."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any


DATE_PATTERNS = [
    re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b"),
]


def lexical_absolute(path: Path) -> str:
    return os.path.abspath(os.fspath(path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--queries-file", type=Path)
    parser.add_argument("--compressed-notebooks-dir", type=Path)
    parser.add_argument("--csv", action="append", type=Path, default=[])
    parser.add_argument("--date-start")
    parser.add_argument("--date-end")
    parser.add_argument("--match-all", action="store_true")
    parser.add_argument("--notebook-id", action="append", default=[])
    parser.add_argument("--max-notebooks", type=int, default=8)
    parser.add_argument("--max-matches-per-notebook", type=int, default=3)
    parser.add_argument("--max-notebook-matches", type=int, default=24)
    parser.add_argument("--max-csv-matches", type=int, default=200)
    parser.add_argument("--max-excerpt-chars", type=int, default=1600)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def iso_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def dates_in_text(text: str) -> list[date]:
    result: list[date] = []
    for index, pattern in enumerate(DATE_PATTERNS):
        for match in pattern.finditer(text):
            values = [int(value) for value in match.groups()]
            year, month, day = values if index == 0 else (values[2], values[0], values[1])
            try:
                result.append(date(year, month, day))
            except ValueError:
                pass
    return result


def matches(text: str, queries: list[str], match_all: bool, start: date | None, end: date | None) -> bool:
    folded = text.casefold()
    query_hits = [query.casefold() in folded for query in queries]
    if queries and (not all(query_hits) if match_all else not any(query_hits)):
        return False
    if start or end:
        found_dates = dates_in_text(text)
        if not found_dates:
            return False
        if not any((not start or value >= start) and (not end or value <= end) for value in found_dates):
            return False
    return True


def query_matches(text: str, queries: list[str], match_all: bool) -> bool:
    if not queries:
        return True
    folded = text.casefold()
    hits = [query.casefold() in folded for query in queries]
    return all(hits) if match_all else any(hits)


def notebook_matches(
    root: Path, queries: list[str], match_all: bool, start: date | None, end: date | None,
    max_notebooks: int, max_per_notebook: int, limit: int, excerpt_chars: int,
    notebook_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    candidates: list[dict[str, Any]] = []
    requested = {value.casefold() for value in notebook_ids}
    for path in sorted(root.glob("*/final_message.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        text = value.get("compressed_text", "")
        notebook_id = value.get("notebook_id") or path.parent.name
        if requested and notebook_id.casefold() not in requested and path.parent.name.casefold() not in requested:
            continue
        notebook_dates = dates_in_text(text)
        date_overlap = not (start or end) or any(
            (not start or value >= start) and (not end or value <= end) for value in notebook_dates
        )
        if not date_overlap:
            continue
        paragraph_matches: list[dict[str, Any]] = []
        term_occurrences = 0
        distinct_terms: set[str] = set()
        for index, paragraph in enumerate(text.split("\n\n")):
            if queries and not query_matches(paragraph, queries, match_all):
                continue
            if not queries and not matches(paragraph, [], match_all, start, end):
                continue
            folded = paragraph.casefold()
            for query in queries:
                count = folded.count(query.casefold())
                if count:
                    distinct_terms.add(query.casefold())
                    term_occurrences += count
            paragraph_matches.append({
                "notebook_id": notebook_id,
                "path": lexical_absolute(path),
                "paragraph_index": index,
                "source_span_markers": sorted(set(re.findall(r"S\d{4}", paragraph))),
                "excerpt": paragraph[:excerpt_chars],
                "excerpt_truncated": len(paragraph) > excerpt_chars,
            })
        if paragraph_matches:
            score = 100 * len(distinct_terms) + 10 * min(term_occurrences, 20) + min(len(paragraph_matches), 9)
            if queries and len(distinct_terms) == len({query.casefold() for query in queries}):
                score += 100
            if start or end:
                score += 50
            candidates.append({
                "notebook_id": notebook_id,
                "path": lexical_absolute(path),
                "relevance_score": score,
                "distinct_query_terms": sorted(distinct_terms),
                "term_occurrences": term_occurrences,
                "matching_paragraph_count": len(paragraph_matches),
                "matches": paragraph_matches,
            })
    candidates.sort(key=lambda item: (-item["relevance_score"], -item["matching_paragraph_count"], item["notebook_id"]))
    selected = candidates if requested else candidates[:max_notebooks]
    results: list[dict[str, Any]] = []
    truncated = len(candidates) > len(selected)
    for candidate in selected:
        chosen = candidate["matches"][:max_per_notebook]
        truncated = truncated or len(candidate["matches"]) > len(chosen)
        for match in chosen:
            if len(results) >= limit:
                return results, [{key: value for key, value in item.items() if key != "matches"} for item in candidates], True
            results.append(match)
    ranking = [{key: value for key, value in item.items() if key != "matches"} for item in candidates]
    return results, ranking, truncated


def csv_matches(
    paths: list[Path], queries: list[str], match_all: bool, start: date | None, end: date | None, limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                text = "\t".join(value or "" for value in row.values())
                if not matches(text, queries, match_all, start, end):
                    continue
                if len(results) >= limit:
                    return results, True
                results.append({"path": lexical_absolute(path), "row_number": row_number, "row": row})
    return results, False


def main() -> None:
    args = parse_args()
    queries = list(args.query)
    if args.queries_file:
        queries.extend(line.strip() for line in args.queries_file.read_text(encoding="utf-8").splitlines() if line.strip())
    start, end = iso_date(args.date_start), iso_date(args.date_end)
    if not queries and not (start or end):
        raise SystemExit("supply --query/--queries-file or a date range")
    if not args.compressed_notebooks_dir and not args.csv:
        raise SystemExit("supply --compressed-notebooks-dir and/or --csv")

    notebooks: list[dict[str, Any]] = []
    notebooks_truncated = False
    if args.compressed_notebooks_dir:
        notebooks, notebook_ranking, notebooks_truncated = notebook_matches(
            args.compressed_notebooks_dir, queries, args.match_all, start, end,
            args.max_notebooks, args.max_matches_per_notebook,
            args.max_notebook_matches, args.max_excerpt_chars, args.notebook_id,
        )
    else:
        notebook_ranking = []
    rows, rows_truncated = csv_matches(args.csv, queries, args.match_all, start, end, args.max_csv_matches)
    payload = {
        "query": {"terms": queries, "match_all": args.match_all, "date_start": args.date_start, "date_end": args.date_end,
                  "notebook_ids": args.notebook_id},
        "interpretation": "Notebook ranking and excerpts are discovery hints, not evidence of relevance or irrelevance; inspect selected compressed notebooks directly.",
        "notebook_ranking": notebook_ranking,
        "matching_notebook_files": sorted({item["path"] for item in notebooks}),
        "notebook_matches": notebooks,
        "notebook_matches_truncated": notebooks_truncated,
        "csv_matches": rows,
        "csv_matches_truncated": rows_truncated,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
