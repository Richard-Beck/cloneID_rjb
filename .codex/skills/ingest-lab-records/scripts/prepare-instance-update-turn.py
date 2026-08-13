#!/usr/bin/env python3
"""Prepare a compact retrieval bootstrap for one pending database turn."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from markdown_database import (
    SPAN_RE,
    absolute,
    load_summaries,
    parse_sources,
    pending_span_ids,
    queue_items,
    read_table,
    records,
    resolved_span_ids,
    split_ids,
)


DATE_MATCH_LIMIT = 12
CELL_MATCH_LIMIT = 5


def compact(value: str | None, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", value or "").strip().replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def short_date(value: str | None) -> str:
    return (value or "")[:10]


def representative_episode_ids(rows: list[dict[str, str]], limit: int = 3) -> list[str]:
    ordered = sorted(rows, key=lambda row: (row.get("seeding_date", ""), row.get("episode_id", "")))
    values = list(dict.fromkeys(row.get("episode_id", "") for row in ordered if row.get("episode_id")))
    if len(values) <= limit:
        return values
    indices = sorted({0, len(values) // 2, len(values) - 1})
    return [values[index] for index in indices]


def passaging_entry_count(rows: list[dict[str, str]]) -> int:
    total = 0
    for row in rows:
        try:
            total += int(float(row.get("passaging_entry_count") or 0))
        except ValueError:
            continue
    return total


def aggregate_matches(
    span_ids: list[str], matches: dict[str, dict[str, str]], titles: dict[str, str]
) -> tuple[list[dict[str, object]], dict[str, int]]:
    aggregated: dict[str, dict[str, object]] = {}
    for span_id in span_ids:
        row = matches.get(span_id, {})
        groups = {
            "exact": set(split_ids(row.get("passage_id_notebook_ids", ""))),
            "date": set(split_ids(row.get("date_range_notebook_ids", ""))),
            "cell": set(split_ids(row.get("cell_line_notebook_ids", ""))),
        }
        for notebook_id in set().union(*groups.values()):
            item = aggregated.setdefault(
                notebook_id,
                {"notebook_id": notebook_id, "exact": 0, "date": 0, "cell": 0, "spans": set()},
            )
            for kind, values in groups.items():
                item[kind] = int(item[kind]) + int(notebook_id in values)
            item["spans"].add(span_id)

    ranked: list[dict[str, object]] = []
    tier_counts = {"exact": 0, "date": 0, "cell": 0}
    for item in aggregated.values():
        tier = "exact" if item["exact"] else "date" if item["date"] else "cell"
        tier_counts[tier] += 1
        item["tier"] = tier
        item["title"] = titles.get(str(item["notebook_id"]), "")
        item["span_count"] = len(item["spans"])
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            {"exact": 0, "date": 1, "cell": 2}[str(item["tier"])],
            -int(item["exact"]),
            -int(item["date"]),
            -int(item["cell"]),
            -int(item["span_count"]),
            str(item["notebook_id"]),
        )
    )
    exact = [item for item in ranked if item["tier"] == "exact"]
    dates = [item for item in ranked if item["tier"] == "date"]
    cells = [item for item in ranked if item["tier"] == "cell"]
    shown = exact + dates[:DATE_MATCH_LIMIT]
    if not shown:
        shown = cells[:CELL_MATCH_LIMIT]
    return shown, tier_counts


def base_episode_id(value: str) -> str:
    return re.sub(r"_(?:seed|harvest).*$", "", value, flags=re.IGNORECASE)


def composite_episode_id(value: str) -> str:
    base = base_episode_id(value)
    return re.sub(r"_A\d+.*$", "", base, flags=re.IGNORECASE)


def passage_wildcard(value: str) -> str | None:
    base = base_episode_id(value)
    match = re.search(r"_A\d+", base, flags=re.IGNORECASE)
    if not match:
        return None
    return re.escape(base[: match.start()]) + r"_A[0-9]+" + re.escape(base[match.end() :])


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def direct_database_overlaps(database: Path, span_ids: list[str]) -> tuple[list[dict], int, int]:
    focus = set(span_ids)
    instance_records = records(database, "instances")
    protocol_records = records(database, "protocols")
    overlaps = []
    for item in instance_records:
        matched = sorted(focus & set(SPAN_RE.findall(item["text"])))
        if matched:
            overlaps.append({**item, "matched": matched})
    return overlaps, len(instance_records), len(protocol_records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--work-item")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    database = absolute(args.database)
    sources = parse_sources(database)
    required = {"coherent_spans", "notebook_summaries", "span_notebook_matches", "compressed_notebooks"}
    missing_sources = sorted(required - set(sources))
    if missing_sources:
        raise SystemExit("sources.md is missing: " + ", ".join(missing_sources))
    pending = [item for item in queue_items(database) if item["status"] == "pending"]
    if args.work_item:
        pending = [item for item in pending if item["id"] == args.work_item]
    else:
        pending = pending[:1]
    if len(pending) != 1:
        raise SystemExit("no unique matching pending work item")
    item = pending[0]
    if not item["spans"]:
        raise SystemExit("pending work item has no spans")

    coherent = sources["coherent_spans"]
    spans = {row["coherent_span_id"]: row for row in read_table(coherent / "coherent_spans.csv")}
    members: dict[str, list[dict[str, str]]] = {}
    for row in read_table(coherent / "coherent_span_membership.csv"):
        members.setdefault(row["coherent_span_id"], []).append(row)
    missing = sorted(set(item["spans"]) - set(spans))
    if missing:
        raise SystemExit("unknown coherent spans: " + ", ".join(missing))

    match_file = sources["span_notebook_matches"] / "span_notebook_matches.tsv"
    matches = {row["coherent_span_id"]: row for row in read_table(match_file)}
    titles = {
        summary.get("notebook_id", ""): summary.get("notebook_name") or "Untitled"
        for summary in load_summaries(sources["notebook_summaries"])
    }
    output = absolute(args.output) if args.output else database / "turns" / f"{item['id']}.context.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Turn context: {item['id']}",
        "",
        "This compact document is a retrieval bootstrap, not factual evidence. Use it to decide what to open; cite canonical span data or compressed notebook paragraphs in database records.",
        "",
        "## Work item",
        "",
        f"- Input spans: {len(item['spans'])}",
        f"- Reason: {item['reason']}",
        f"- Queue history: {len(resolved_span_ids(database))} resolved span IDs; {len(pending_span_ids(database))} currently pending span IDs.",
        "- Queue only never-resolved candidates. Do not duplicate pending candidates or requeue resolved spans.",
        "",
        "## Input spans",
        "",
        "| Span | Dates | Episodes | Passaging rows | Cell line | Medium/conditions | Representative episode IDs |",
        "|---|---|---:|---:|---|---|---|",
    ]
    all_representatives: list[str] = []
    for span_id in item["spans"]:
        row = spans[span_id]
        span_members = members.get(span_id, [])
        representatives = representative_episode_ids(span_members)
        all_representatives.extend(representatives)
        dates = f"{short_date(row.get('span_start_date'))}–{short_date(row.get('span_end_date'))}"
        lines.append(
            f"| `{span_id}` | {dates} | {row.get('episode_count') or len(span_members)} | "
            f"{passaging_entry_count(span_members)} | {compact(row.get('cell_lines'), 35)} | "
            f"{compact(row.get('media_labels'), 100)} | {compact('; '.join(representatives), 150)} |"
        )

    shown_matches, tier_counts = aggregate_matches(item["spans"], matches, titles)
    lines.extend([
        "",
        "## Aggregated notebook leads",
        "",
        "Counts are numbers of input spans matching each notebook. Exact passage-ID matches are strong retrieval leads; date overlap is broad; cell-line-only matching is weak.",
        "",
    ])
    if shown_matches:
        lines.extend([
            "| Notebook | Title | Best evidence | Exact ID | Date | Cell line | Any-match spans |",
            "|---|---|---|---:|---:|---:|---:|",
        ])
        for match in shown_matches:
            lines.append(
                f"| {match['notebook_id']} | {compact(str(match['title']), 65)} | {match['tier']} | "
                f"{match['exact']} | {match['date']} | {match['cell']} | {match['span_count']} |"
            )
    else:
        lines.append("No deterministic notebook matches.")
    shown_date = sum(match["tier"] == "date" for match in shown_matches)
    shown_cell = sum(match["tier"] == "cell" for match in shown_matches)
    suppressed_date = tier_counts["date"] - shown_date
    suppressed_cell = tier_counts["cell"] - shown_cell
    if suppressed_date or suppressed_cell:
        lines.extend([
            "",
            f"Suppressed weaker leads: {suppressed_date} additional date-only notebooks and {suppressed_cell} cell-line-only notebooks. Inspect the matching TSV if broader retrieval is justified.",
        ])

    overlaps, instance_count, protocol_count = direct_database_overlaps(database, item["spans"])
    lines.extend([
        "",
        "## Existing database",
        "",
        f"The database currently contains {instance_count} instances and {protocol_count} protocols. Search it before creating records.",
        "",
        "Instances directly overlapping the input spans:",
        "",
    ])
    if overlaps:
        for overlap in overlaps:
            lines.append(
                f"- `{overlap['id'] or overlap['path'].stem}` — {overlap['title'] or 'Untitled'}; "
                f"overlaps {len(overlap['matched'])} input span(s); file: `{absolute(overlap['path'])}`"
            )
    else:
        lines.append("- None. This does not establish that a new record is needed; search by informative lineage, objective, and method terms.")

    script_dir = absolute(Path(__file__).parent)
    python = absolute(Path(sys.executable))
    sample = next(
        (value for value in all_representatives if re.search(r"_A\d+", value, flags=re.IGNORECASE)),
        all_representatives[0] if all_representatives else "FULL_EPISODE_ID",
    )
    base = base_episode_id(sample)
    composite = composite_episode_id(sample)
    wildcard = passage_wildcard(sample)
    compressed = sources["compressed_notebooks"]
    lines.extend([
        "",
        "## Progressive retrieval",
        "",
        "Start with the full identifier as a fixed string. If it is absent, remove only a suffix whose meaning you understand, then try an informative composite substring. Broaden one meaningful component at a time. Avoid isolated passage labels such as `A10`, cell-line-only searches, or OR expressions joining unrelated broad fragments.",
        "",
    ])
    retrieval_steps = [
        f"Exact ID: `rg -n -F -- {shell_single_quote(sample)} {shell_single_quote(str(compressed))}`"
    ]
    if base != sample:
        retrieval_steps.append(
            f"Remove the seed/harvest suffix: `rg -n -F -- {shell_single_quote(base)} {shell_single_quote(str(compressed))}`"
        )
    if composite != base and len(composite) >= 6:
        retrieval_steps.append(
            f"Retain the informative lineage composite: `rg -n -F -- {shell_single_quote(composite)} {shell_single_quote(str(compressed))}`"
        )
    if wildcard:
        retrieval_steps.append(
            f"If passage-wide retrieval is justified, wildcard that component with an `rg` regular expression: `rg -n -- {shell_single_quote(wildcard)} {shell_single_quote(str(compressed))}`"
        )
    lines.extend(f"{index}. {step}" for index, step in enumerate(retrieval_steps, start=1))
    lines.extend([
        "",
        "In `rg` regular expressions, `|` means logical OR and `.*` or a constrained expression such as `[0-9]+` supplies wildcard behavior. A shell-style bare `*` is not the appropriate wildcard inside an `rg` pattern. Prefer `-F` until intentional regex broadening is needed.",
        "",
        "Other useful retrieval commands:",
        "",
        f"- Inspect all deterministic mappings: `rg -n -F -- {shell_single_quote(item['spans'][0])} {shell_single_quote(str(match_file))}`",
        f"- Search existing instances and protocols: `rg -n -i -- 'INFORMATIVE_LINEAGE_OR_METHOD' {shell_single_quote(str(database / 'instances'))} {shell_single_quote(str(database / 'protocols'))}`",
        f"- Read a selected notebook: `{python} {script_dir / 'extract-notebook-evidence.py'} --compressed-notebooks-dir {compressed} --notebook-id NB-000`",
        f"- Discover related spans: `{python} {script_dir / 'search-coherent-spans.py'} --coherent-spans-dir {coherent} --target-span {item['spans'][0]} --database {database}`",
        "",
        "## Source paths",
        "",
        f"- Canonical coherent spans: `{coherent}`",
        f"- Notebook summaries: `{sources['notebook_summaries']}`",
        f"- Matching results: `{sources['span_notebook_matches']}`",
        f"- Compressed notebooks: `{compressed}`",
        "",
        "## Required turn outcome",
        "",
        "Retrieve relevant evidence; identify both generating/maintenance work and downstream sampling/assay work; update every supported instance and protocol; attach clearly participating spans; queue only never-resolved candidates; resolve this row; and write its concise turn note.",
    ])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
