#!/usr/bin/env python3
"""Run a bounded sequence of database-update turns with frozen states."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from markdown_database import parse_sources, queue_items, read_table, resolved_span_ids


def absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def pending_items(database: Path) -> list[dict]:
    return [item for item in queue_items(database) if item["status"] == "pending"]


def longest_never_resolved_span(database: Path, minimum_passaging_entries: int) -> dict | None:
    """Return the largest eligible canonical span absent from resolved queue history."""
    coherent = parse_sources(database).get("coherent_spans")
    if coherent is None:
        raise SystemExit("sources.md requires Coherent spans")
    summaries = {
        row["coherent_span_id"]: row for row in read_table(coherent / "coherent_spans.csv")
    }
    counts = {
        span_id: {"passaging_entry_count": 0, "episode_count": 0}
        for span_id in summaries
    }
    for row in read_table(coherent / "coherent_span_membership.csv"):
        span_id = row["coherent_span_id"]
        counts[span_id]["passaging_entry_count"] += int(float(row.get("passaging_entry_count") or 0))
        counts[span_id]["episode_count"] += 1
    resolved = resolved_span_ids(database)
    candidates = [
        {
            "span_id": span_id,
            **counts[span_id],
            "cell_lines": summaries[span_id].get("cell_lines", ""),
        }
        for span_id in summaries
        if span_id not in resolved
        and counts[span_id]["passaging_entry_count"] >= minimum_passaging_entries
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (-item["passaging_entry_count"], -item["episode_count"], item["span_id"]),
    )


def seed_longest_never_resolved_span(database: Path, minimum_passaging_entries: int) -> dict | None:
    candidate = longest_never_resolved_span(database, minimum_passaging_entries)
    if candidate is None:
        return None
    work_id = f"ingest_{candidate['span_id']}"
    reason = (
        "Ingest the longest never-resolved coherent span "
        f"({candidate['passaging_entry_count']:,} passaging-table entries across "
        f"{candidate['episode_count']:,} culture episodes)."
    )
    queue_path = database / "queue.md"
    current = queue_path.read_text(encoding="utf-8")
    separator = "" if current.endswith("\n") else "\n"
    queue_path.write_text(
        current + separator + f"| {work_id} | `{candidate['span_id']}` | {reason} | pending |\n",
        encoding="utf-8",
    )
    return {**candidate, "id": work_id, "reason": reason}


def freeze_database(source: Path, destination: Path) -> None:
    """Copy a database and make the snapshot read-only without touching symlink targets."""
    shutil.copytree(source, destination, symlinks=True)
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.is_symlink():
            continue
        path.chmod(0o550 if path.is_dir() else 0o440)
    destination.chmod(0o550)


def markdown_file_hashes(directory: Path) -> dict[Path, str]:
    if not directory.is_dir():
        return {}
    return {
        path.relative_to(directory): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.md"))
    }


def next_turn_number(runs_root: Path, versions_root: Path) -> int:
    numbers = [0]
    pattern = re.compile(r"turn_(\d+)(?:_(?:before|after))?")
    for root in (runs_root, versions_root):
        if not root.exists():
            continue
        for path in root.iterdir():
            match = pattern.fullmatch(path.name)
            if path.is_dir() and match:
                numbers.append(int(match.group(1)))
    return max(numbers) + 1


def turn_prompt(database: Path, work_id: str) -> str:
    return f"""Use the `ingest-lab-records` skill. Perform exactly one pending instance/protocol database-update turn.

Database: {database}
Work item: {work_id}

Read `sources.md`, `queue.md`, and the existing Markdown records. Prepare only the named pending item, read the relevant notebooks, update the
database in place, and resolve only that queue row. Queue only never-resolved candidates; update previously resolved spans without requeueing
them. Write the turn note and validate the database. Do not process a second queue item.
"""


def compliance_prompt(database: Path, skill_root: Path) -> str:
    return f"""Use the `ingest-lab-records` skill. Review the Markdown database at {database} and the skill reference
{skill_root / 'references' / 'instance-protocol-database-update.md'}, which explains how the database should be structured.

List the 3–5 highest-value updates to the current database that would increase compliance with those guidelines. For each proposed change,
explain why it helps, score the benefit from 1–10, state exactly what would need to be done, and score the work required from 1–10.

Do not modify sources.md, queue.md, instances/, protocols/, or turns/. Save the review as one or more Markdown files under
{database / 'compliance'}. Do not write anywhere else in the database.\n"""


def disposition_prompt(database: Path, compliance_review: Path, user_disposition: Path) -> str:
    return f"""Use the `ingest-lab-records` skill. Apply the explicit human decisions in the user-disposition document to the live Markdown
database at {database}.

Previous compliance review: {compliance_review}
User disposition: {user_disposition}

Follow the user disposition against the previous compliance review. Implement only recommendations explicitly approved by the user; do not
infer approval from a recommendation, and do not act on deferred or rejected recommendations. Preserve queue history and source
accountability, use the database-update guidelines, and make any required turn notes. Validate the database before finishing.\n"""


def execute_turn(
    args: argparse.Namespace,
    database: Path,
    project_root: Path,
    test_root: Path,
    pending: list[dict],
    seeded_item: dict | None,
    prompt_override: str | None,
) -> bool:
    expected_work_id = pending[0]["id"]
    initial_statuses = {item["id"]: item["status"] for item in queue_items(database)}
    runs_root = test_root / "turn_runs"
    versions_root = test_root / "database_versions"
    runs_root.mkdir(parents=True, exist_ok=True)
    versions_root.mkdir(parents=True, exist_ok=True)
    turn_number = next_turn_number(runs_root, versions_root)
    run_dir = runs_root / f"turn_{turn_number:03d}"
    before_version = versions_root / f"turn_{turn_number:03d}_before"
    after_version = versions_root / f"turn_{turn_number:03d}_after"
    for destination in (run_dir, before_version, after_version):
        if destination.exists():
            raise SystemExit(f"refusing to reuse artifact path: {destination}")
    run_dir.mkdir(parents=True)
    freeze_database(database, before_version)

    prompt = prompt_override or turn_prompt(database, expected_work_id)
    (run_dir / "prompt.txt").write_text(prompt.rstrip() + "\n", encoding="utf-8")
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    final_path = run_dir / "final_message.md"
    command = [
        args.codex_bin, "exec", "--ephemeral", "--model", args.model,
        "--config", f'model_reasoning_effort="{args.reasoning}"',
        "--config", 'approval_policy="never"',
        "--sandbox", "workspace-write", "--cd", os.fspath(project_root), "--color", "never", "--json",
        "--output-last-message", os.fspath(final_path), "-",
    ]
    metadata = {
        "turn_number": turn_number,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "reasoning": args.reasoning,
        "database": os.fspath(database),
        "expected_work_item_id": expected_work_id,
        "pending_work_item_ids_at_start": [item["id"] for item in pending],
        "seeded_work_item": seeded_item,
        "frozen_database_before": os.fspath(before_version),
        "command": command,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    with events_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(command, input=prompt, text=True, stdout=stdout, stderr=stderr, check=False)
    (run_dir / "codex_exit_code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")

    renderer = Path(__file__).with_name("render-events-text.py")
    subprocess.run(
        [sys.executable, os.fspath(renderer), os.fspath(events_path), "--output", os.fspath(run_dir / "events.txt")],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    freeze_database(database, after_version)

    transition_errors: list[str] = []
    try:
        final_statuses = {item["id"]: item["status"] for item in queue_items(database)}
        if final_statuses.get(expected_work_id) != "resolved":
            transition_errors.append(f"expected work item {expected_work_id!r} was not resolved")
        for work_id, initial_status in initial_statuses.items():
            if work_id != expected_work_id and initial_status == "pending" and final_statuses.get(work_id) != "pending":
                transition_errors.append(f"additional pending work item {work_id!r} was processed")
    except (OSError, AttributeError) as exc:
        transition_errors.append(f"cannot inspect final queue: {exc}")
    (run_dir / "turn_transition.txt").write_text(
        "turn transition valid\n" if not transition_errors else "\n".join(transition_errors) + "\n",
        encoding="utf-8",
    )
    transition_code = 0 if not transition_errors else 1
    (run_dir / "turn_transition_exit_code.txt").write_text(f"{transition_code}\n", encoding="utf-8")

    validator = Path(__file__).with_name("validate-instance-protocol-db.py")
    validation = subprocess.run(
        [sys.executable, os.fspath(validator), os.fspath(database)], text=True, capture_output=True, check=False,
    )
    (run_dir / "validation.txt").write_text(validation.stdout + validation.stderr, encoding="utf-8")
    (run_dir / "validation_exit_code.txt").write_text(f"{validation.returncode}\n", encoding="utf-8")
    metadata.update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "codex_exit_code": completed.returncode,
        "validation_exit_code": validation.returncode,
        "turn_transition_exit_code": transition_code,
        "frozen_database_after": os.fspath(after_version),
    })
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    return completed.returncode == 0 and validation.returncode == 0 and transition_code == 0


def execute_compliance_review(
    args: argparse.Namespace,
    database: Path,
    project_root: Path,
    test_root: Path,
) -> bool:
    """Run the final read-only-within-records compliance review and retain an audit trail."""
    runs_root = test_root / "compliance_review"
    versions_root = test_root / "database_versions"
    runs_root.mkdir(parents=True, exist_ok=True)
    versions_root.mkdir(parents=True, exist_ok=True)
    review_number = next_turn_number(runs_root, versions_root)
    run_dir = runs_root / f"turn_{review_number:03d}"
    before_version = versions_root / f"turn_{review_number:03d}_compliance_before"
    after_version = versions_root / f"turn_{review_number:03d}_compliance_after"
    for destination in (run_dir, before_version, after_version):
        if destination.exists():
            raise SystemExit(f"refusing to reuse artifact path: {destination}")
    run_dir.mkdir(parents=True)
    freeze_database(database, before_version)
    compliance_dir = database / "compliance"
    compliance_before = markdown_file_hashes(compliance_dir)

    skill_root = Path(__file__).resolve().parent.parent
    prompt = compliance_prompt(database, skill_root)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    final_path = run_dir / "final_message.md"
    command = [
        args.codex_bin, "exec", "--ephemeral", "--model", args.compliance_model,
        "--config", f'model_reasoning_effort="{args.compliance_reasoning}"',
        "--config", 'approval_policy="never"',
        "--sandbox", "workspace-write", "--cd", os.fspath(project_root), "--color", "never", "--json",
        "--output-last-message", os.fspath(final_path), "-",
    ]
    metadata = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": args.compliance_model,
        "reasoning": args.compliance_reasoning,
        "database": os.fspath(database),
        "frozen_database_before": os.fspath(before_version),
        "command": command,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    with events_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(command, input=prompt, text=True, stdout=stdout, stderr=stderr, check=False)

    renderer = Path(__file__).with_name("render-events-text.py")
    subprocess.run(
        [sys.executable, os.fspath(renderer), os.fspath(events_path), "--output", os.fspath(run_dir / "events.txt")],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    freeze_database(database, after_version)
    compliance_after = markdown_file_hashes(compliance_dir)
    changed_compliance_files = sorted(
        path for path, digest in compliance_after.items() if compliance_before.get(path) != digest
    )
    output_error = "" if changed_compliance_files else "no Markdown compliance review was created or changed"
    (run_dir / "output_check.txt").write_text(
        "compliance output present\n" if not output_error else output_error + "\n", encoding="utf-8"
    )

    validator = Path(__file__).with_name("validate-instance-protocol-db.py")
    validation = subprocess.run(
        [sys.executable, os.fspath(validator), os.fspath(database)], text=True, capture_output=True, check=False,
    )
    (run_dir / "validation.txt").write_text(validation.stdout + validation.stderr, encoding="utf-8")
    metadata.update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "codex_exit_code": completed.returncode,
        "validation_exit_code": validation.returncode,
        "frozen_database_after": os.fspath(after_version),
        "changed_compliance_files": [os.fspath(compliance_dir / path) for path in changed_compliance_files],
    })
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    return completed.returncode == 0 and validation.returncode == 0 and not output_error


def execute_disposition_turn(
    args: argparse.Namespace,
    database: Path,
    project_root: Path,
    test_root: Path,
    compliance_review: Path,
    user_disposition: Path,
) -> bool:
    """Apply explicit human dispositions to a prior compliance review before ingestion."""
    runs_root = test_root / "disposition_turn"
    versions_root = test_root / "database_versions"
    runs_root.mkdir(parents=True, exist_ok=True)
    versions_root.mkdir(parents=True, exist_ok=True)
    turn_number = next_turn_number(runs_root, versions_root)
    run_dir = runs_root / f"turn_{turn_number:03d}"
    before_version = versions_root / f"turn_{turn_number:03d}_disposition_before"
    after_version = versions_root / f"turn_{turn_number:03d}_disposition_after"
    for destination in (run_dir, before_version, after_version):
        if destination.exists():
            raise SystemExit(f"refusing to reuse artifact path: {destination}")
    run_dir.mkdir(parents=True)
    freeze_database(database, before_version)

    prompt = disposition_prompt(database, compliance_review, user_disposition)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    final_path = run_dir / "final_message.md"
    command = [
        args.codex_bin, "exec", "--ephemeral", "--model", args.disposition_model,
        "--config", f'model_reasoning_effort="{args.disposition_reasoning}"',
        "--config", 'approval_policy="never"',
        "--sandbox", "workspace-write", "--cd", os.fspath(project_root), "--color", "never", "--json",
        "--output-last-message", os.fspath(final_path), "-",
    ]
    metadata = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": args.disposition_model,
        "reasoning": args.disposition_reasoning,
        "database": os.fspath(database),
        "previous_compliance_review": os.fspath(compliance_review),
        "user_disposition": os.fspath(user_disposition),
        "frozen_database_before": os.fspath(before_version),
        "command": command,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    with events_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(command, input=prompt, text=True, stdout=stdout, stderr=stderr, check=False)
    (run_dir / "codex_exit_code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")

    renderer = Path(__file__).with_name("render-events-text.py")
    subprocess.run(
        [sys.executable, os.fspath(renderer), os.fspath(events_path), "--output", os.fspath(run_dir / "events.txt")],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    freeze_database(database, after_version)
    validator = Path(__file__).with_name("validate-instance-protocol-db.py")
    validation = subprocess.run(
        [sys.executable, os.fspath(validator), os.fspath(database)], text=True, capture_output=True, check=False,
    )
    (run_dir / "validation.txt").write_text(validation.stdout + validation.stderr, encoding="utf-8")
    (run_dir / "validation_exit_code.txt").write_text(f"{validation.returncode}\n", encoding="utf-8")
    metadata.update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "codex_exit_code": completed.returncode,
        "validation_exit_code": validation.returncode,
        "frozen_database_after": os.fspath(after_version),
    })
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    return completed.returncode == 0 and validation.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path)
    parser.add_argument("--prompt", type=Path, help="Prompt override for the first executed turn only")
    parser.add_argument(
        "--previous-compliance-review", type=Path,
        help="Previous compliance-review Markdown file to apply before ingestion; requires --user-disposition.",
    )
    parser.add_argument(
        "--user-disposition", type=Path,
        help="Human decision document for a previous compliance review; requires --previous-compliance-review.",
    )
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--reasoning", default="medium")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument(
        "--minimum-passaging-entries", type=int, default=4,
        help="Only seed an empty queue with spans having at least this many passaging-table entries (default: 4).",
    )
    parser.add_argument(
        "--skip-compliance-review", action="store_true",
        help="Do not launch the default final Sol/xhigh compliance-review turn.",
    )
    parser.add_argument("--compliance-model", default="gpt-5.6-sol")
    parser.add_argument("--compliance-reasoning", default="xhigh")
    parser.add_argument("--disposition-model", default="gpt-5.6-sol")
    parser.add_argument("--disposition-reasoning", default="xhigh")
    parser.add_argument(
        "--stop-when-queue-empty", action="store_true",
        help=(
            "After at least one turn, stop when the pending queue becomes empty; "
            "an initially empty queue still seeds the longest never-resolved span"
        ),
    )
    args = parser.parse_args()
    if args.max_turns < 1:
        raise SystemExit("--max-turns must be at least 1")
    if args.minimum_passaging_entries < 1:
        raise SystemExit("--minimum-passaging-entries must be at least 1")
    if bool(args.previous_compliance_review) != bool(args.user_disposition):
        raise SystemExit("--previous-compliance-review and --user-disposition must be supplied together")

    test_root = absolute(args.test_root)
    project_root = absolute(args.project_root)
    database = absolute(args.database) if args.database else test_root / "database"
    if not database.is_dir() or not (database / "queue.md").exists() or not (database / "sources.md").exists():
        raise SystemExit(f"database with sources.md and queue.md is required: {database}")
    compliance_review = absolute(args.previous_compliance_review) if args.previous_compliance_review else None
    user_disposition = absolute(args.user_disposition) if args.user_disposition else None
    for label, path in (("previous compliance review", compliance_review), ("user disposition", user_disposition)):
        if path is not None and not path.is_file():
            raise SystemExit(f"{label} must be a readable file: {path}")
    prompt_override = None
    if args.prompt:
        prompt_override = absolute(args.prompt).read_text(encoding="utf-8")

    if compliance_review is not None and user_disposition is not None:
        if not execute_disposition_turn(
            args, database, project_root, test_root, compliance_review, user_disposition
        ):
            print("Disposition turn failed.")
            raise SystemExit(1)
        print("Completed preliminary disposition turn.")

    completed_turns = 0
    stop_reason = "turn_limit"
    for _ in range(args.max_turns):
        pending = pending_items(database)
        seeded_item = None
        if not pending:
            if args.stop_when_queue_empty and completed_turns > 0:
                stop_reason = "queue_empty"
                break
            seeded_item = seed_longest_never_resolved_span(database, args.minimum_passaging_entries)
            if seeded_item is None:
                stop_reason = "no_eligible_unresolved_spans"
                break
            pending = pending_items(database)
        success = execute_turn(
            args, database, project_root, test_root, pending, seeded_item,
            prompt_override if completed_turns == 0 else None,
        )
        completed_turns += 1
        if not success:
            print(f"Stopped after failed turn {completed_turns}.")
            raise SystemExit(1)

    print(f"Completed {completed_turns} ingestion turn(s); stop reason: {stop_reason}.")
    if not args.skip_compliance_review:
        if not execute_compliance_review(args, database, project_root, test_root):
            print("Compliance review failed.")
            raise SystemExit(1)
        print("Completed final compliance-review turn.")


if __name__ == "__main__":
    main()
