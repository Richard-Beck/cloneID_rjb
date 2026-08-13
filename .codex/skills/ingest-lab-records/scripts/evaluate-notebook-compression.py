#!/usr/bin/env python3
"""Evaluate notebook compression ratios and auditable lexical retention."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


DATE_RE = re.compile(
    r"\b(?:"
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{1,2}[-/]\d{1,2}[-/](?:\d{2}|\d{4})"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)
URL_RE = re.compile(r"(?:https?://|doi:\s*)[^\s)\]}>*]+", re.IGNORECASE)
MEDIA_RE = re.compile(r"\bmedia\s+(?:#\s*)?\d+[A-Za-z]?(?![-_.A-Za-z0-9])", re.IGNORECASE)
UNDERSCORE_ID_RE = re.compile(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9.-]+)+\b")
HYPHEN_ID_RE = re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b")
FILE_ID_RE = re.compile(r"\b[^\s/\\]+\.(?:png|jpe?g|tiff?|csv|xlsx?|fcs|cif|pdf)\b", re.IGNORECASE)
QUANTITY_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[x×]\s*10\s*\^?\s*[+-]?\d+|[eE][+-]?\d+)?)"
    r"\s*"
    r"(?:%|°C|[CF]\b|cells?\b|million\b|billion\b|mL\b|ml\b|uL\b|ul\b|µL\b|nL\b|L\b|"
    r"mM\b|uM\b|µM\b|nM\b|pM\b|M\b|ng\b|ug\b|µg\b|mg\b|kg\b|g\b|"
    r"rpm\b|xg\b|g-force\b|sec(?:ond)?s?\b|min(?:ute)?s?\b|h(?:r|our)?s?\b|days?\b|weeks?\b|"
    r"mm\b|cm\b|um\b|µm\b|nm\b|mm2\b|cm2\b|um2\b|µm2\b|fold\b|X\b)",
    re.IGNORECASE,
)
MAX_ACCOUNTING_SPANS = 20
ASSESSMENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--assessment-name", default="assessment")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def metrics(text: str) -> dict[str, int]:
    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "words": len(re.findall(r"\S+", text)),
        "non_whitespace_characters": len(re.sub(r"\s", "", text)),
    }


def normalize_lexeme(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def exact_terms(pattern: re.Pattern[str], text: str) -> set[str]:
    return {normalize_lexeme(match.group(0)) for match in pattern.finditer(text)}


def urls(text: str) -> set[str]:
    return {value.rstrip(".,;:!?*'\"") for value in exact_terms(URL_RE, text)}


def quantities(text: str) -> set[str]:
    values = set()
    unit_aliases = (
        (r"seconds?$", "sec"),
        (r"minutes?$", "min"),
        (r"(?:hours?|hrs?)$", "h"),
        (r"days?$", "day"),
        (r"weeks?$", "week"),
        (r"cells?$", "cell"),
    )
    for value in exact_terms(QUANTITY_RE, text):
        normalized = value.lower().replace("µ", "u").replace("μ", "u").replace("×", "x")
        normalized = re.sub(r",(?=\d{3}(?:\D|$))", "", normalized)
        normalized = re.sub(r"\s+", "", normalized)
        for pattern, replacement in unit_aliases:
            normalized = re.sub(pattern, replacement, normalized)
        values.add(normalized)
    return values


def identifiers(text: str) -> set[str]:
    values = set()
    for pattern in (MEDIA_RE, UNDERSCORE_ID_RE, HYPHEN_ID_RE, FILE_ID_RE):
        for value in exact_terms(pattern, text):
            if any(character.isalpha() for character in value) and any(character.isdigit() for character in value):
                values.add(value)
    return values


def source_text(packet: dict[str, Any]) -> str:
    return "\n\n".join(segment["text"] for segment in packet["source_segments"])


def coverage(source_values: Iterable[str], compressed_values: Iterable[str]) -> dict[str, Any]:
    source_set = set(source_values)
    compressed_set = set(compressed_values)
    missing = sorted(source_set - compressed_set)
    retained = len(source_set) - len(missing)
    return {
        "source_unique": len(source_set),
        "retained_exact": retained,
        "coverage": 1.0 if not source_set else retained / len(source_set),
        "missing": missing,
    }


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "notebook_id",
        "status",
        "source_characters",
        "compressed_characters",
        "character_ratio",
        "character_reduction",
        "source_words",
        "compressed_words",
        "word_ratio",
        "word_reduction",
        "source_spans",
        "accounting_records",
        "max_source_spans_per_record",
        "broad_accounting_records",
        "accounted_spans",
        "missing_spans",
        "duplicate_spans",
        "unknown_spans",
        "date_coverage",
        "identifier_coverage",
        "quantity_coverage",
        "url_coverage",
        "protected_exact_coverage",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    packet_dir = run_dir / "inputs" / "notebooks"
    if not packet_dir.is_dir():
        raise SystemExit(f"notebook packet directory is missing: {packet_dir}")
    if not ASSESSMENT_NAME_RE.fullmatch(args.assessment_name):
        raise SystemExit("--assessment-name must be filesystem-safe")

    assessment_dir = run_dir / args.assessment_name
    assessment_dir.mkdir(exist_ok=False)
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for packet_path in sorted(packet_dir.glob("*.json")):
        packet = load_json(packet_path)
        notebook_id = packet["notebook_id"]
        result_path = run_dir / "tasks" / notebook_id / "final_message.json"
        base_row: dict[str, Any] = {"notebook_id": notebook_id}
        if not result_path.is_file():
            base_row["status"] = "missing_result"
            rows.append(base_row)
            details.append({"notebook_id": notebook_id, "status": "missing_result"})
            continue
        try:
            result = load_json(result_path)
        except (json.JSONDecodeError, OSError) as exc:
            base_row["status"] = "invalid_result"
            rows.append(base_row)
            details.append({"notebook_id": notebook_id, "status": "invalid_result", "error": str(exc)})
            continue

        compressed = result.get("compressed_text")
        if not isinstance(compressed, str) or not compressed:
            base_row["status"] = "invalid_result"
            rows.append(base_row)
            details.append({"notebook_id": notebook_id, "status": "invalid_result", "error": "compressed_text missing"})
            continue

        source = source_text(packet)
        source_metrics = metrics(source)
        compressed_metrics = metrics(compressed)
        expected_spans = {segment["source_span"] for segment in packet["source_segments"]}
        accounted: list[str] = []
        accounting = result.get("source_accounting", [])
        accounting = accounting if isinstance(accounting, list) else []
        accounting_span_counts: list[int] = []
        broad_accounting_records: list[dict[str, int]] = []
        for record_index, record in enumerate(accounting, start=1):
            if isinstance(record, dict) and isinstance(record.get("source_spans"), list):
                record_spans = [value for value in record["source_spans"] if isinstance(value, str)]
                accounted.extend(record_spans)
                accounting_span_counts.append(len(record_spans))
                if len(record_spans) > MAX_ACCOUNTING_SPANS:
                    broad_accounting_records.append({"record": record_index, "span_count": len(record_spans)})
        counts = Counter(accounted)
        accounted_set = set(accounted)
        missing_spans = sorted(expected_spans - accounted_set)
        duplicate_spans = sorted(value for value, count in counts.items() if count > 1 and value in expected_spans)
        unknown_spans = sorted(accounted_set - expected_spans)

        source_terms = {
            "dates": exact_terms(DATE_RE, source),
            "identifiers": identifiers(source),
            "quantities": quantities(source),
            "urls": urls(source),
        }
        compressed_terms = {
            "dates": exact_terms(DATE_RE, compressed),
            "identifiers": identifiers(compressed),
            "quantities": quantities(compressed),
            "urls": urls(compressed),
        }
        term_coverage = {
            name: coverage(source_terms[name], compressed_terms[name])
            for name in source_terms
        }
        protected_source = set().union(*source_terms.values())
        protected_compressed = set().union(*compressed_terms.values())
        protected_coverage = coverage(protected_source, protected_compressed)

        character_ratio = compressed_metrics["characters"] / source_metrics["characters"]
        word_ratio = compressed_metrics["words"] / source_metrics["words"]
        span_audit_pass = not (missing_spans or duplicate_spans or unknown_spans or broad_accounting_records)
        protected_audit_pass = all(not value["missing"] for value in term_coverage.values())
        if span_audit_pass and protected_audit_pass:
            status = "passed_automated"
        elif not span_audit_pass and not protected_audit_pass:
            status = "failed_span_and_protected_audit"
        elif not span_audit_pass:
            status = "failed_span_audit"
        else:
            status = "failed_protected_audit"
        base_row.update(
            {
                "status": status,
                "source_characters": source_metrics["characters"],
                "compressed_characters": compressed_metrics["characters"],
                "character_ratio": round(character_ratio, 6),
                "character_reduction": round(1 - character_ratio, 6),
                "source_words": source_metrics["words"],
                "compressed_words": compressed_metrics["words"],
                "word_ratio": round(word_ratio, 6),
                "word_reduction": round(1 - word_ratio, 6),
                "source_spans": len(expected_spans),
                "accounting_records": len(accounting),
                "max_source_spans_per_record": max(accounting_span_counts, default=0),
                "broad_accounting_records": len(broad_accounting_records),
                "accounted_spans": len(accounted_set & expected_spans),
                "missing_spans": len(missing_spans),
                "duplicate_spans": len(duplicate_spans),
                "unknown_spans": len(unknown_spans),
                "date_coverage": round(term_coverage["dates"]["coverage"], 6),
                "identifier_coverage": round(term_coverage["identifiers"]["coverage"], 6),
                "quantity_coverage": round(term_coverage["quantities"]["coverage"], 6),
                "url_coverage": round(term_coverage["urls"]["coverage"], 6),
                "protected_exact_coverage": round(protected_coverage["coverage"], 6),
            }
        )
        rows.append(base_row)
        details.append(
            {
                "notebook_id": notebook_id,
                "status": status,
                "source_metrics": source_metrics,
                "compressed_metrics": compressed_metrics,
                "span_audit": {
                    "expected": len(expected_spans),
                    "accounted_unique": len(accounted_set & expected_spans),
                    "missing": missing_spans,
                    "duplicates": duplicate_spans,
                    "unknown": unknown_spans,
                    "broad_records": broad_accounting_records,
                    "maximum_allowed_spans_per_record": MAX_ACCOUNTING_SPANS,
                },
                "protected_information": term_coverage,
                "protected_information_combined": protected_coverage,
                "worker_quality_notes": result.get("quality_notes", []),
            }
        )

    valid_rows = [row for row in rows if "source_characters" in row]
    total_source_characters = sum(int(row["source_characters"]) for row in valid_rows)
    total_compressed_characters = sum(int(row["compressed_characters"]) for row in valid_rows)
    total_source_words = sum(int(row["source_words"]) for row in valid_rows)
    total_compressed_words = sum(int(row["compressed_words"]) for row in valid_rows)
    summary = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "notebooks_expected": len(rows),
        "notebooks_with_valid_results": len(valid_rows),
        "notebooks_passing_span_audit": sum(
            not (row.get("missing_spans") or row.get("duplicate_spans") or row.get("unknown_spans")
                 or row.get("broad_accounting_records"))
            for row in valid_rows
        ),
        "notebooks_passing_protected_audit": sum(row.get("protected_exact_coverage") == 1.0 for row in valid_rows),
        "notebooks_passing_automated_audit": sum(row.get("status") == "passed_automated" for row in valid_rows),
        "total_source_characters": total_source_characters,
        "total_compressed_characters": total_compressed_characters,
        "aggregate_character_ratio": (
            total_compressed_characters / total_source_characters if total_source_characters else None
        ),
        "aggregate_character_reduction": (
            1 - total_compressed_characters / total_source_characters if total_source_characters else None
        ),
        "total_source_words": total_source_words,
        "total_compressed_words": total_compressed_words,
        "aggregate_word_ratio": total_compressed_words / total_source_words if total_source_words else None,
        "aggregate_word_reduction": 1 - total_compressed_words / total_source_words if total_source_words else None,
        "manual_semantic_review_required": True,
    }

    write_tsv(assessment_dir / "notebook_metrics.tsv", rows)
    (assessment_dir / "retention_details.json").write_text(
        json.dumps(details, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (assessment_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if len(valid_rows) == len(rows) and all(
        row.get("status") == "passed_automated" for row in rows
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
