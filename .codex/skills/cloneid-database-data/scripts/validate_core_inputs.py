#!/usr/bin/env python3
"""Validate cloneID core input presence, schemas, keys, and basic references."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


EXPECTED_FIELDS = {
    "passaging.csv": [
        "id", "cellLine", "event", "passaged_from_id1", "passaged_from_id2",
        "growthType", "passage", "cellCount", "date", "address", "comment",
        "media", "feeding1", "feeding2", "feeding3", "feeding4", "Countess",
        "feeding5", "feeding6", "feeding7", "feeding8", "feeding9", "flask",
        "feeding17", "correctedCount", "areaOccupied_um2", "cellSize_um2",
        "owner", "lastModified", "transactionId",
        "BeforeCorrection_From_Passage_Media", "lastModifiedDate",
    ],
    "media.csv": [
        "id", "base1", "base1_pct", "base2", "base2_pct", "FBS", "FBS_pct",
        "EnergySource2", "EnergySource2_pct", "EnergySource", "EnergySource_nM",
        "HEPES", "HEPES_mM", "Salt", "Salt_nM", "antibiotic",
        "antibiotic_pct", "growthFactors", "antibiotic2", "antibiotic2_pct",
        "antimycotic", "antimycotic_pct", "Stressor", "Stressor_concentration",
        "Stressor_unit", "comment", "antibiotic3", "antibiotic4",
        "antibiotic3_pct", "antibiotic4_pct", "oxygen_pct", "export4pub",
    ],
    "perspective.csv": ["whichPerspective", "origin", "n"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-dir", type=Path, default=Path("core_data"))
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path for a machine-readable validation report.",
    )
    return parser.parse_args()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def is_finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(clean(value)))
    except (TypeError, ValueError):
        return False


def read_and_check_schema(
    path: Path,
    expected_fields: list[str],
    errors: list[str],
) -> list[dict[str, str]]:
    if not path.is_file():
        errors.append(f"missing input file: {path}")
        return []

    with path.open(newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.reader(handle))
    if not raw_rows:
        errors.append(f"empty input file: {path}")
        return []
    header = raw_rows[0]
    if header != expected_fields:
        missing = [field for field in expected_fields if field not in header]
        extra = [field for field in header if field not in expected_fields]
        if missing:
            errors.append(f"{path}: missing fields: {', '.join(missing)}")
        if extra:
            errors.append(f"{path}: unexpected fields: {', '.join(extra)}")
        if not missing and not extra:
            errors.append(f"{path}: fields are not in the expected order")
        return []
    malformed_widths = [
        line_number
        for line_number, row in enumerate(raw_rows[1:], start=2)
        if len(row) != len(header)
    ]
    if malformed_widths:
        preview = ", ".join(map(str, malformed_widths[:10]))
        errors.append(f"{path}: row width differs from header at lines {preview}")
        return []
    if len(raw_rows) == 1:
        errors.append(f"{path}: header exists but there are no data rows")
        return []
    return [dict(zip(header, row)) for row in raw_rows[1:]]


def duplicate_values(rows: list[dict[str, str]], field: str) -> list[str]:
    counts = Counter(clean(row[field]) for row in rows if clean(row[field]))
    return sorted(value for value, count in counts.items() if count > 1)


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    warnings: list[str] = []
    tables = {
        filename: read_and_check_schema(
            args.core_dir / filename, fields, errors
        )
        for filename, fields in EXPECTED_FIELDS.items()
    }

    passaging = tables["passaging.csv"]
    media = tables["media.csv"]
    perspective = tables["perspective.csv"]

    if passaging:
        blank_ids = sum(not clean(row["id"]) for row in passaging)
        duplicates = duplicate_values(passaging, "id")
        if blank_ids:
            errors.append(f"passaging.csv: {blank_ids} blank id values")
        if duplicates:
            errors.append(
                f"passaging.csv: {len(duplicates)} duplicate id values; "
                f"examples: {', '.join(duplicates[:10])}"
            )
        blank_cell_lines = sum(not clean(row["cellLine"]) for row in passaging)
        if blank_cell_lines:
            errors.append(f"passaging.csv: {blank_cell_lines} blank cellLine values")
        blank_events = sum(not clean(row["event"]) for row in passaging)
        unknown_events = sorted(
            {
                clean(row["event"])
                for row in passaging
                if clean(row["event"]) not in {"", "seeding", "harvest"}
            }
        )
        if blank_events:
            warnings.append(f"passaging.csv: {blank_events} blank event values")
        if unknown_events:
            warnings.append(
                "passaging.csv: unexpected nonblank event values: "
                + ", ".join(unknown_events)
            )
        malformed_dates = sum(
            not re.match(r"^\d{4}-\d{2}-\d{2}T", clean(row["date"]))
            for row in passaging
        )
        if malformed_dates:
            warnings.append(
                f"passaging.csv: {malformed_dates} dates lack an ISO date prefix"
            )

    if media:
        blank_ids = sum(not clean(row["id"]) for row in media)
        duplicates = duplicate_values(media, "id")
        if blank_ids:
            errors.append(f"media.csv: {blank_ids} blank id values")
        if duplicates:
            errors.append(
                f"media.csv: {len(duplicates)} duplicate id values; "
                f"examples: {', '.join(duplicates[:10])}"
            )
        blank_bases = sum(not clean(row["base1"]) for row in media)
        if blank_bases:
            warnings.append(f"media.csv: {blank_bases} blank base1 values")

    if perspective:
        for field in ("whichPerspective", "origin", "n"):
            blank_count = sum(not clean(row[field]) for row in perspective)
            if blank_count:
                errors.append(f"perspective.csv: {blank_count} blank {field} values")
        nonnumeric_n = sum(
            bool(clean(row["n"])) and not is_finite_number(row["n"])
            for row in perspective
        )
        if nonnumeric_n:
            errors.append(f"perspective.csv: {nonnumeric_n} nonnumeric n values")

    if passaging and media:
        media_ids = {clean(row["id"]) for row in media if clean(row["id"])}
        unresolved_media = sorted(
            {
                clean(row["media"])
                for row in passaging
                if clean(row["media"]) and clean(row["media"]) not in media_ids
            }
        )
        if unresolved_media:
            warnings.append(
                f"passaging.csv: {len(unresolved_media)} referenced media IDs are absent "
                f"from media.csv; examples: {', '.join(unresolved_media[:10])}"
            )

    if passaging:
        passaging_ids = {clean(row["id"]) for row in passaging if clean(row["id"])}
        unresolved_parents = sorted(
            {
                clean(row[field])
                for row in passaging
                for field in ("passaged_from_id1", "passaged_from_id2")
                if clean(row[field]) and clean(row[field]) not in passaging_ids
            }
        )
        if unresolved_parents:
            warnings.append(
                f"passaging.csv: {len(unresolved_parents)} parent labels do not resolve "
                f"to record IDs; examples: {', '.join(unresolved_parents[:10])}"
            )
        if perspective:
            unmatched_origins = sorted(
                {
                    clean(row["origin"])
                    for row in perspective
                    if clean(row["origin"]) not in passaging_ids
                }
            )
            if unmatched_origins:
                warnings.append(
                    f"perspective.csv: {len(unmatched_origins)} origins do not resolve "
                    f"to passaging IDs; examples: {', '.join(unmatched_origins[:10])}"
                )

    report = {
        "status": "FAIL" if errors else "PASS",
        "core_dir": str(args.core_dir),
        "row_counts": {filename: len(rows) for filename, rows in tables.items()},
        "errors": errors,
        "warnings": warnings,
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        with args.json_output.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")

    print(f"Core input validation: {report['status']}")
    for filename, row_count in report["row_counts"].items():
        print(f"  {filename}: {row_count} rows")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
