#!/usr/bin/env python3
"""Inventory existing local database/notebook evidence without refreshing it.

The JSON output contains private paths and must remain local or encrypted.
Source dates describe filesystem modification times, not verified scientific edit dates.
"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def build_plan(root, validation_dir=None):
    def local_path(value):
        """Rebase recorded source-machine paths onto this repository when possible."""
        path = Path(value)
        if not path.is_absolute():
            return root / path
        for index, part in enumerate(path.parts):
            if part in ("lab_records", "data", "tmp", "core_data"):
                candidate = root.joinpath(*path.parts[index:])
                if candidate.exists():
                    return candidate
        return path

    def relative(path):
        return str(path.resolve().relative_to(root))

    def record(path):
        return {"path": relative(path), "bytes": path.stat().st_size,
                "mtime": timestamp(path.stat().st_mtime),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def run_validation(script, *arguments):
        result = subprocess.run([sys.executable, str(root / script), *map(str, arguments)],
                                cwd=root, text=True, capture_output=True)
        if result.returncode:
            raise ValueError(f"Validation failed: {script}\n{result.stdout}{result.stderr}")
        return {"passed": True, "output": result.stdout + result.stderr}

    def files_under(path):
        return sorted(p for p in path.rglob("*") if p.is_file())

    required = [root / "core_data" / (name + ".csv")
                for name in ("passaging", "media", "liquid_nitrogen", "perspective")]
    for path in required:
        if not path.is_file():
            raise ValueError(f"Missing canonical input: {relative(path)}")
    tables = required.copy()
    for name in ("annotated_passaging_nodes.csv", "passaging_edges.csv",
                 "culture_episodes.csv", "culture_episode_edges.csv",
                 "metadata_graph_qc_summary.csv"):
        path = root / "data" / name
        if path.is_file():
            tables.append(path)
    span_names = ("coherent_spans.csv", "coherent_span_membership.csv",
                  "coherent_span_edges.csv", "coherent_span_run_metadata.json")
    spans = [root / "data/coherent_spans" / name for name in span_names]
    missing_spans = [relative(p) for p in spans if not p.is_file()]
    tables.extend(p for p in spans if p.is_file())

    validations = {"core_inputs": run_validation(
        ".codex/skills/cloneid-database-data/scripts/validate_core_inputs.py",
        "--core-dir", root / "core_data")}
    # Existing graph builders do not persist raw input hashes. Verify the row ID
    # coverage against raw passaging and report the remaining provenance limit.
    nodes_path = root / "data/annotated_passaging_nodes.csv"
    if nodes_path.is_file():
        with required[0].open() as handle:
            raw_ids = {row["id"].strip() for row in csv.DictReader(handle)}
        with nodes_path.open() as handle:
            node_ids = {row["passage_id"].strip() for row in csv.DictReader(handle)}
        if raw_ids != node_ids:
            raise ValueError("Canonical graph node IDs differ from raw passaging IDs")
        validations["graph_raw_id_coverage"] = {"passed": True, "nodes": len(node_ids)}
    if not missing_spans and validation_dir is not None:
        run_validation(".codex/skills/cloneid-database-data/scripts/summarize_coherent_spans.py",
                       "--output-dir", validation_dir)
        matches = {p.name: p.read_bytes() == (validation_dir / p.name).read_bytes()
                   for p in spans}
        if not all(matches.values()):
            raise ValueError("Existing coherent spans differ from regeneration using current graphs")
        validations["coherent_spans_recomputed_from_current_graphs"] = {
            "passed": True, "byte_identical": matches}

    db = root / "lab_records/instance_protocol_db"
    source_text = (db / "sources.md").read_text()
    refs = dict(re.findall(r"^- ([^:]+): `([^`]+)`", source_text, re.MULTILINE))
    for label in ("Compressed notebooks", "Notebook summaries", "Coherent spans", "Span-notebook matches"):
        if label not in refs or not local_path(refs[label]).exists():
            raise ValueError(f"Missing evidence location in sources.md: {label}")
    compressed = local_path(refs["Compressed notebooks"])
    db_validation = run_validation(
        ".codex/skills/ingest-lab-records/scripts/validate-instance-protocol-db.py", db)
    notebook_files = sorted(db.rglob("*.md"))
    notebook_files.extend(compressed.glob("*/final_message.json"))
    notebook_files.append(local_path(refs["Notebook summaries"]))
    for label in ("Coherent spans", "Span-notebook matches"):
        notebook_files.extend(files_under(local_path(refs[label])))
    manifest = compressed.parent / "MANIFEST.md"
    if manifest.is_file():
        notebook_files.append(manifest)

    # Complete extracted packets preserve the source text underlying compressions.
    packets, raw_sources, changed_sources, run_roots = [], [], [], set()
    for result in sorted(compressed.glob("*/final_message.json")):
        compressed_result = json.loads(result.read_text())
        if not compressed_result.get("compressed_text"):
            raise ValueError(f"Empty compressed notebook: {relative(result)}")
        prompt = result.parent / "prompt.txt"
        match = re.search(r'"notebook_packet": "([^"]+)"', prompt.read_text())
        if not match:
            raise ValueError(f"No source packet in {relative(prompt)}")
        packet = local_path(match.group(1))
        data = json.loads(packet.read_text())
        provenance = data["source_provenance"]
        raw = local_path(provenance["source_html"])
        if not raw.is_file():
            raise ValueError(f"Missing raw notebook source: {raw}")
        actual_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
        source = record(raw)
        source["sha256"] = actual_hash
        source["packet_source_sha256"] = provenance["source_html_sha256"]
        raw_sources.append(source)
        if actual_hash != provenance["source_html_sha256"]:
            changed_sources.append(relative(raw))
        packets.append(packet)
        run_roots.add(packet.parent.parent.parent)
    if not packets:
        raise ValueError("No processed notebooks found")
    expected_count = json.loads(local_path(refs["Notebook summaries"]).read_text())["notebook_count"]
    if len(packets) != expected_count:
        raise ValueError(f"Only {len(packets)} processed notebooks present; summaries expect {expected_count}")
    notebook_files.extend(packets)
    audits = []
    for run_root in sorted(run_roots):
        for subdir in ("assessment_complete", "assessment"):
            summary = run_root / subdir / "summary.json"
            if summary.is_file():
                audits.append(json.loads(summary.read_text()))
                notebook_files.extend(files_under(summary.parent))
                break
        else:
            raise ValueError(f"Missing compression audit for {relative(run_root)}")

    latest_raw = max(raw_sources, key=lambda r: r["mtime"])
    passaging = record(required[0])
    omitted = [relative(p) for p in files_under(db) if p.suffix != ".md"]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_basis": "Filesystem mtime of canonical raw CSV / underlying notebook HTML; not a verified database or notebook edit timestamp.",
        "bundles": {
            "tables": {
                "description": "Passaging, media, liquid nitrogen, Perspective counts, and available cleaned metadata/span products",
                "files": sorted(set(relative(p) for p in tables)),
                "source_last_updated": passaging["mtime"],
                "passaging_source": passaging,
                "raw_sources": [record(p) for p in required],
                "derived_files": [record(p) for p in tables if p not in required],
                "validations": validations,
                "limitations": [
                    "Existing graph files lack recorded raw input hashes. Node-ID coverage is checked, but this alone cannot establish every derived field's freshness.",
                    "Coherent spans are regenerated in a temporary directory and compared byte-for-byte with canonical products when all graph/span inputs are available.",
                ],
                "missing_optional_span_products": missing_spans,
                "provenance": "Existing canonical local inputs; no database refresh or promotion was performed.",
                "omissions": ["Imaging availability products from legacy roots; research outputs"],
            },
            "notebooks": {
                "description": "Processed laboratory notebooks, complete extracted source spans, summaries, and live instance/protocol Markdown database",
                "source_project_root": str(root),
                "files": sorted(set(relative(p) for p in notebook_files)),
                "source_last_updated": latest_raw["mtime"],
                "raw_sources": sorted(raw_sources, key=lambda r: r["path"]),
                "processed_notebook_count": len(packets),
                "compression_audits": audits,
                "database_validation": db_validation,
                "raw_sources_changed_since_processing": changed_sources,
                "source_references": refs,
                "limitations": [
                    "Processed compressions are available for all inventoried notebooks but are not fully semantically audited; consult included audit reports.",
                    "The live instance/protocol database covers curated experimental instances, not every notebook experiment.",
                    "Absolute paths inside existing provenance records describe the source machine; use archive-relative paths after extraction.",
                ],
                "omissions": {
                    "raw_html": "Complete extracted source-span packets are included instead of original HTML presentation/assets.",
                    "execution_logs": "Compression agent event traces, prompts, and execution metadata are omitted.",
                    "non_markdown_db_attachments": omitted,
                },
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("tmp/checkpoint/source-plan.json"))
    args = parser.parse_args()
    plan = build_plan(args.project_root.resolve(), args.output.resolve().parent / "span-verification")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n")
    print(f"Wrote local source plan: {args.output}")
    for name, bundle in plan["bundles"].items():
        print(f"{name}: {len(bundle['files'])} files; raw source last updated {bundle['source_last_updated']}")


if __name__ == "__main__":
    main()
