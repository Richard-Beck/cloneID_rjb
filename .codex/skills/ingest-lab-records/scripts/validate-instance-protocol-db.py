#!/usr/bin/env python3
"""Check that a Markdown knowledge base remains navigable and internally linked."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from markdown_database import NOTEBOOK_RE, SPAN_RE, absolute, parse_sources, queue_items, read_table, records, section


def linked_ids(text: str, heading: str) -> set[str]:
    return set(re.findall(r"`([^`]+)`", section(text, heading)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    root = absolute(args.database)
    errors: list[str] = []
    for required in (root / "sources.md", root / "queue.md", root / "instances", root / "protocols", root / "turns"):
        if not required.exists():
            errors.append(f"missing required path: {required}")
    if errors:
        print("\n".join(f"ERROR: {value}" for value in errors))
        raise SystemExit(1)
    if (root / "spans").exists():
        errors.append("spans/ must not exist; coherent spans remain external")
    json_files = sorted(path for path in root.rglob("*.json") if path.is_file())
    if json_files:
        errors.append("database contains JSON records: " + ", ".join(str(path.relative_to(root)) for path in json_files))

    try:
        sources = parse_sources(root)
    except OSError as exc:
        sources = {}
        errors.append(f"cannot read sources.md: {exc}")
    required_sources = {"coherent_spans", "notebook_summaries", "span_notebook_matches", "compressed_notebooks"}
    for key in sorted(required_sources):
        if key not in sources:
            errors.append(f"sources.md is missing {key}")
        elif not sources[key].exists():
            errors.append(f"source does not exist: {sources[key]}")
    canonical: set[str] = set()
    coherent = sources.get("coherent_spans")
    if coherent and (coherent / "coherent_spans.csv").exists():
        try:
            canonical = {row["coherent_span_id"] for row in read_table(coherent / "coherent_spans.csv")}
        except (OSError, KeyError) as exc:
            errors.append(f"cannot read canonical coherent spans: {exc}")

    queue = queue_items(root)
    resolved_spans = {
        span_id for item in queue if item["status"] == "resolved" for span_id in item["spans"]
    }
    pending_owners: dict[str, str] = {}
    seen_work: set[str] = set()
    for item in queue:
        if not item["id"]:
            errors.append("queue row has no ID")
        elif item["id"] in seen_work:
            errors.append(f"duplicate queue ID: {item['id']}")
        seen_work.add(item["id"])
        if item["status"] not in {"pending", "resolved"}:
            errors.append(f"{item['id'] or 'queue row'} has invalid status: {item['status']}")
        if not item["spans"]:
            errors.append(f"{item['id'] or 'queue row'} has no canonical spans")
        for span_id in item["spans"]:
            if canonical and span_id not in canonical:
                errors.append(f"queue references unknown span: {span_id}")
            if item["status"] == "pending":
                if span_id in resolved_spans:
                    errors.append(f"pending queue item {item['id']!r} requeues resolved span: {span_id}")
                owner = pending_owners.get(span_id)
                if owner and owner != item["id"]:
                    errors.append(f"span {span_id} is pending in both {owner!r} and {item['id']!r}")
                pending_owners[span_id] = item["id"]
        if item["status"] == "resolved":
            note = root / "turns" / f"{item['id']}.md"
            if not note.exists():
                errors.append(f"resolved queue item lacks turn note: {note}")
            elif not re.search(r"(?mi)^Status:\s*completed\s*$", note.read_text(encoding="utf-8")):
                errors.append(f"turn note is not completed: {note}")

    by_kind: dict[str, dict[str, dict]] = {}
    all_ids: set[str] = set()
    for kind in ("instances", "protocols"):
        by_kind[kind] = {}
        for item in records(root, kind):
            if not item["title"]:
                errors.append(f"{item['path']}: missing H1 title")
            if not item["id"]:
                errors.append(f"{item['path']}: missing ID")
                continue
            if item["id"] in all_ids:
                errors.append(f"duplicate record ID: {item['id']}")
            all_ids.add(item["id"])
            by_kind[kind][item["id"]] = item
    instance_ids = set(by_kind["instances"])
    protocol_ids = set(by_kind["protocols"])
    notebook_root = sources.get("compressed_notebooks")
    for item in by_kind["instances"].values():
        for span_id in set(SPAN_RE.findall(item["text"])):
            if canonical and span_id not in canonical:
                errors.append(f"{item['path']}: unknown canonical span {span_id}")
        for protocol_id in linked_ids(item["text"], "Protocols"):
            if protocol_id not in protocol_ids:
                errors.append(f"{item['path']}: unknown protocol {protocol_id}")
        for related_id in linked_ids(item["text"], "Related instances"):
            if related_id not in instance_ids:
                errors.append(f"{item['path']}: unknown related instance {related_id}")
    if notebook_root:
        for kind in ("instances", "protocols"):
            for item in by_kind[kind].values():
                for notebook_id in set(NOTEBOOK_RE.findall(item["text"])):
                    if not (notebook_root / notebook_id / "final_message.json").exists():
                        errors.append(f"{item['path']}: unknown compressed notebook {notebook_id}")

    if errors:
        print("\n".join(f"ERROR: {value}" for value in errors))
        raise SystemExit(1)
    print(f"valid Markdown database: {len(instance_ids)} instances, {len(protocol_ids)} protocols, {len(queue)} queue rows")


if __name__ == "__main__":
    main()
