#!/usr/bin/env python3
"""Show a terse Markdown catalog for progressive disclosure."""

from __future__ import annotations

import argparse
from pathlib import Path

from markdown_database import absolute, catalog_markdown


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--span-id", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = catalog_markdown(absolute(args.database), args.span_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
