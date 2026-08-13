#!/usr/bin/env python3
"""Render Codex JSONL events as a readable, 160-column text trace."""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any


WIDTH = 160


def wrapped(value: str, prefix: str = "") -> str:
    lines: list[str] = []
    for raw_line in value.splitlines() or [""]:
        if not raw_line:
            lines.append(prefix.rstrip())
            continue
        lines.extend(textwrap.wrap(
            raw_line, width=WIDTH, initial_indent=prefix, subsequent_indent=prefix,
            replace_whitespace=False, drop_whitespace=False, break_long_words=True, break_on_hyphens=False,
        ) or [prefix])
    return "\n".join(lines)


def render(event: dict[str, Any]) -> str:
    event_type = event.get("type", "unknown")
    item = event.get("item")
    if not isinstance(item, dict):
        remainder = {key: value for key, value in event.items() if key != "type"}
        return f"[{event_type}]" + ("\n" + wrapped(json.dumps(remainder, ensure_ascii=False), "  ") if remainder else "")
    item_type = item.get("type", "unknown")
    header = f"[{event_type}] {item_type} {item.get('id', '')}".rstrip()
    blocks = [header]
    if item_type == "agent_message":
        blocks.append(wrapped(str(item.get("text", "")), "  "))
    elif item_type == "command_execution":
        blocks.append(wrapped(str(item.get("command", "")), "  COMMAND: "))
        if item.get("aggregated_output"):
            blocks.append("  OUTPUT:")
            blocks.append(wrapped(str(item["aggregated_output"]), "    "))
        blocks.append(f"  status={item.get('status')} exit_code={item.get('exit_code')}")
    else:
        blocks.append(wrapped(json.dumps(item, ensure_ascii=False, indent=2), "  "))
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.events.with_suffix(".txt")
    rendered: list[str] = []
    for line_number, line in enumerate(args.events.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rendered.append(render(json.loads(line)))
        except json.JSONDecodeError:
            rendered.append(f"[invalid JSON line {line_number}]\n{wrapped(line, '  ')}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(rendered) + ("\n" if rendered else ""), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
