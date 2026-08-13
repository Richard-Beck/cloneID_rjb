#!/usr/bin/env python3
"""Small shared readers for the Markdown instance/protocol knowledge base."""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any


SPAN_RE = re.compile(r"media_\d+__span_\d+")
NOTEBOOK_RE = re.compile(r"NB-\d+")
SOURCE_LABELS = {
    "coherent spans": "coherent_spans",
    "notebook summaries": "notebook_summaries",
    "span-notebook matches": "span_notebook_matches",
    "compressed notebooks": "compressed_notebooks",
}


def absolute(path: Path) -> Path:
    """Make a path absolute without resolving snapshot symlinks."""
    return Path(os.path.abspath(os.fspath(path)))


def rooted(database: Path, value: str) -> Path:
    path = Path(value)
    return absolute(path if path.is_absolute() else database / path)


def read_table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        delimiter = "\t" if path.suffix == ".tsv" else ","
        return list(csv.DictReader(handle, delimiter=delimiter))


def parse_sources(database: Path) -> dict[str, Path]:
    path = database / "sources.md"
    values: dict[str, Path] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"-\s+([^:]+):\s+`([^`]+)`\s*$", line)
        if match and match.group(1).strip().casefold() in SOURCE_LABELS:
            key = SOURCE_LABELS[match.group(1).strip().casefold()]
            values[key] = rooted(database, match.group(2))
    return values


def parse_markdown_table(path: Path) -> list[dict[str, str]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    cells = lambda line: [cell.strip() for cell in line.strip("|").split("|")]
    headers = [value.casefold() for value in cells(lines[0])]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        values = cells(line)
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def queue_items(database: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in parse_markdown_table(database / "queue.md"):
        items.append({
            "id": clean_cell(row.get("id", "")),
            "spans": list(dict.fromkeys(SPAN_RE.findall(row.get("spans", "")))),
            "reason": clean_cell(row.get("reason", "")),
            "status": clean_cell(row.get("status", "")).casefold(),
        })
    return items


def resolved_span_ids(database: Path) -> set[str]:
    return {
        span_id
        for item in queue_items(database)
        if item["status"] == "resolved"
        for span_id in item["spans"]
    }


def pending_span_ids(database: Path) -> set[str]:
    return {
        span_id
        for item in queue_items(database)
        if item["status"] == "pending"
        for span_id in item["spans"]
    }


def classify_span_ids(database: Path, span_ids: list[str] | set[str]) -> dict[str, str]:
    """Classify candidates against the complete queue history."""
    resolved = resolved_span_ids(database)
    pending = pending_span_ids(database)
    return {
        span_id: "resolved" if span_id in resolved else "pending" if span_id in pending else "unseen"
        for span_id in span_ids
    }


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)", text
    )
    return match.group(1).strip() if match else ""


def record(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    title = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    record_id = re.search(r"(?m)^ID:\s*`([^`]+)`\s*$", text)
    status = re.search(r"(?mi)^Status:\s*([^\n]+)$", text)
    return {
        "path": path,
        "text": text,
        "title": title.group(1).strip() if title else "",
        "id": record_id.group(1).strip() if record_id else "",
        "status": status.group(1).strip() if status else "",
    }


def records(database: Path, kind: str) -> list[dict[str, Any]]:
    directory = database / kind
    return [record(path) for path in sorted(directory.glob("*.md"))]


def catalog_markdown(database: Path, focus_spans: list[str] | None = None) -> str:
    focus = set(focus_spans or [])
    lines = ["# Existing database", ""]
    for kind, heading in (("instances", "Instances"), ("protocols", "Protocols")):
        lines.extend([f"## {heading}", ""])
        found = records(database, kind)
        if not found:
            lines.extend(["None.", ""])
            continue
        for item in found:
            summary_heading = "Purpose"
            summary = section(item["text"], summary_heading).replace("\n", " ")
            spans = sorted(set(SPAN_RE.findall(item["text"])))
            overlap = sorted(focus & set(spans))
            details = [f"status: {item['status'] or 'unspecified'}"]
            if spans:
                details.append(f"spans: {len(spans)}")
            if overlap:
                details.append("input overlap: " + ", ".join(f"`{value}`" for value in overlap))
            lines.append(f"- `{item['id'] or item['path'].stem}` — {item['title'] or 'Untitled'} ({'; '.join(details)})")
            if summary:
                lines.append(f"  {summary[:400]}")
            lines.append(f"  File: `{absolute(item['path'])}`")
        lines.append("")
    lines.append("Open full records when their purpose, span overlap, or relationship makes them relevant.")
    return "\n".join(lines).rstrip() + "\n"


def load_summaries(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value.get("notebook_summaries", value if isinstance(value, list) else [])


def split_ids(value: str) -> list[str]:
    return [part for part in value.split(";") if part]
