#!/usr/bin/env python3
"""Render one JSON task into a narrow Codex prompt template."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PLACEHOLDER_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--task-json", required=True)
    parser.add_argument("--task-index", required=True, type=int)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--task-output-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task = json.loads(args.task_json)
    if not isinstance(task, dict):
        raise SystemExit("--task-json must decode to an object")

    rendered = args.template.read_text(encoding="utf-8")
    values = {
        "{{TASK_JSON}}": json.dumps(task, indent=2, sort_keys=True),
        "{{TASK_INDEX}}": str(args.task_index),
        "{{PROJECT_ROOT}}": str(args.project_root.resolve()),
        "{{TASK_OUTPUT_DIR}}": str(args.task_output_dir.resolve()),
    }
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)

    unresolved = sorted(set(PLACEHOLDER_RE.findall(rendered)))
    if unresolved:
        raise SystemExit(f"unresolved prompt placeholders: {', '.join(unresolved)}")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite rendered prompt: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()

