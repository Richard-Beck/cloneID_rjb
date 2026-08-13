#!/usr/bin/env python3
"""Extract readable Markdown from LabArchives offline-export HTML pages."""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

ENTRY_PATTERN = re.compile(
    r'''dispatchSetEntry\(\s*["'](?P<entry_id>[^"']+)["']\s*,\s*decodeBase64AndParseJSON\(\s*["'](?P<payload>[A-Za-z0-9+/=]+)["']\s*\)\s*\)''',
    re.VERBOSE | re.DOTALL,
)

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre",
    "section", "table", "ul",
}


def normalize_space(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def inline_text(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    name = (node.name or "").lower()
    if name in {"script", "style", "noscript", "template"}:
        return ""
    if name == "br":
        return "\n"
    if name == "img":
        alt = normalize_space(node.get("alt", ""))
        src = node.get("src", "")
        label = alt or Path(src.split("?", 1)[0]).name or "image"
        return f"[Image: {label}]"
    if name == "a":
        label = normalize_space("".join(inline_text(c) for c in node.children))
        href = node.get("href", "").strip()
        if href and not href.lower().startswith(("javascript:", "#")):
            return f"{label} ({href})" if label and label != href else href
        return label
    if name in {"strong", "b"}:
        value = normalize_space("".join(inline_text(c) for c in node.children))
        return f"**{value}**" if value else ""
    if name in {"em", "i"}:
        value = normalize_space("".join(inline_text(c) for c in node.children))
        return f"*{value}*" if value else ""
    if name in {"sub", "sup"}:
        value = normalize_space("".join(inline_text(c) for c in node.children))
        return f"_{value}" if name == "sub" else f"^{value}"
    if name in {"code", "kbd", "samp"}:
        value = normalize_space("".join(node.stripped_strings))
        return f"`{value}`" if value else ""
    return "".join(inline_text(c) for c in node.children)


def table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False) or tr.find_all(["th", "td"])
        row = [
            normalize_space("".join(inline_text(c) for c in cell.children))
            .replace("\n", "<br>")
            .replace("|", r"\|")
            for cell in cells
        ]
        if row:
            rows.append(row)
    if not rows:
        return normalize_space(table.get_text("\n", strip=True))
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(lines)


def render_list(list_tag: Tag, depth: int = 0) -> str:
    lines: list[str] = []
    ordered = list_tag.name.lower() == "ol"
    counter = 1
    for li in list_tag.find_all("li", recursive=False):
        parts: list[str] = []
        nested: list[Tag] = []
        for child in li.children:
            if isinstance(child, Tag) and child.name and child.name.lower() in {"ul", "ol"}:
                nested.append(child)
            else:
                parts.append(inline_text(child))
        value = normalize_space("".join(parts))
        marker = f"{counter}." if ordered else "-"
        lines.append(f"{'  ' * depth}{marker} {value}".rstrip())
        counter += 1
        for sublist in nested:
            lines.append(render_list(sublist, depth + 1))
    return "\n".join(line for line in lines if line.strip())


def rich_html_to_markdown(fragment: str) -> str:
    # LabArchives prepends editor metadata comments such as RTE_FROALA/RTE_FROALARTE.
    fragment = re.sub(r"<!--RTE_[\s\S]*?-->", "", fragment, flags=re.I)
    soup = BeautifulSoup(fragment, "html.parser")
    for comment in soup.find_all(string=lambda value: isinstance(value, __import__("bs4").Comment)):
        comment.extract()
    for unwanted in soup.find_all(["script", "style", "noscript", "template"]):
        unwanted.decompose()
    chunks: list[str] = []

    def render_block(tag: Tag) -> None:
        name = (tag.name or "").lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            value = normalize_space("".join(inline_text(c) for c in tag.children))
            if value:
                chunks.append(f"{'#' * int(name[1])} {value}")
        elif name in {"ul", "ol"}:
            value = render_list(tag)
            if value:
                chunks.append(value)
        elif name == "table":
            value = table_to_markdown(tag)
            if value:
                chunks.append(value)
        elif name == "blockquote":
            value = normalize_space("".join(inline_text(c) for c in tag.children))
            if value:
                chunks.append("\n".join(f"> {line}" for line in value.splitlines()))
        elif name == "pre":
            value = tag.get_text("\n", strip=False).strip()
            if value:
                chunks.append(f"```\n{value}\n```")
        elif name == "hr":
            chunks.append("---")
        elif name in {"p", "figcaption"}:
            value = normalize_space("".join(inline_text(c) for c in tag.children))
            if value:
                chunks.append(value)
        elif name == "figure":
            for image in tag.find_all("img"):
                value = inline_text(image)
                if value:
                    chunks.append(value)
            caption = tag.find("figcaption")
            if caption:
                render_block(caption)
        else:
            direct_blocks = [
                c for c in tag.children
                if isinstance(c, Tag) and (c.name or "").lower() in BLOCK_TAGS
            ]
            if direct_blocks:
                pending: list[str] = []
                for child in tag.children:
                    if isinstance(child, Tag) and (child.name or "").lower() in BLOCK_TAGS:
                        value = normalize_space("".join(pending))
                        if value:
                            chunks.append(value)
                        pending = []
                        render_block(child)
                    else:
                        pending.append(inline_text(child))
                value = normalize_space("".join(pending))
                if value:
                    chunks.append(value)
            else:
                value = normalize_space("".join(inline_text(c) for c in tag.children))
                if value:
                    chunks.append(value)

    root = soup.body or soup
    pending: list[str] = []
    for child in root.children:
        if isinstance(child, Tag) and (child.name or "").lower() in BLOCK_TAGS:
            value = normalize_space("".join(pending))
            if value:
                chunks.append(value)
            pending = []
            render_block(child)
        else:
            pending.append(inline_text(child))
    value = normalize_space("".join(pending))
    if value:
        chunks.append(value)

    cleaned: list[str] = []
    for chunk in chunks:
        chunk = normalize_space(chunk)
        if chunk and (not cleaned or chunk != cleaned[-1]):
            cleaned.append(chunk)
    return "\n\n".join(cleaned).strip()


def decode_entries(raw_html: str) -> list[dict]:
    entries: list[dict] = []
    for match in ENTRY_PATTERN.finditer(raw_html):
        try:
            decoded = base64.b64decode(match.group("payload"), validate=True)
            item = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"Warning: could not decode entry {match.group('entry_id')}: {exc}", file=sys.stderr)
            continue
        item["_entry_id"] = match.group("entry_id")
        entries.append(item)
    return entries


def page_title(soup: BeautifulSoup, source: Path) -> str:
    heading = soup.select_one(".la-static-page-heading")
    if heading:
        text = normalize_space(heading.get_text(" ", strip=True))
        text = re.sub(r"\s+PAGE LOCKED.*$", "", text, flags=re.I)
        if text:
            return text
    if soup.title and soup.title.string:
        text = normalize_space(soup.title.string)
        text = re.sub(r"\s*-\s*LabArchives.*$", "", text, flags=re.I)
        if text:
            return text
    return source.stem


def extract_page(path: Path, include_metadata: bool = False) -> str:
    raw_html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw_html, "html.parser")
    entries = decode_entries(raw_html)
    output: list[str] = [f"# {page_title(soup, path)}"]

    if not entries:
        fallback = rich_html_to_markdown(str(soup.body or soup))
        if fallback:
            output.append(fallback)
        return "\n\n".join(output).strip() + "\n"

    for entry in entries:
        entry_type = entry.get("type")
        data = entry.get("data", "")
        if not isinstance(data, str) or not data.strip():
            continue
        if entry_type == 4:
            value = normalize_space(BeautifulSoup(data, "html.parser").get_text(" ", strip=True))
            if value:
                output.append(f"## {value}")
        elif entry_type in {1, 5}:
            value = rich_html_to_markdown(data)
            if value:
                output.append(value)
        elif entry_type == 2:
            label = normalize_space(BeautifulSoup(data, "html.parser").get_text(" ", strip=True))
            output.append(f"[Attachment{': ' + label if label else ''}]")
        else:
            value = rich_html_to_markdown(data)
            if value:
                output.append(f"[Entry type {entry_type}]\n\n{value}")

        if include_metadata:
            metadata = []
            if entry.get("lastModifiedBy"):
                metadata.append(f"modified by {entry['lastModifiedBy']}")
            if entry.get("updatedAt"):
                metadata.append(f"updated {entry['updatedAt']}")
            if metadata:
                output.append(f"_Entry {entry['_entry_id']}; " + "; ".join(metadata) + "._")

    text = "\n\n".join(part.strip() for part in output if part.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def find_html_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".html", ".htm"})


def safe_relative(path: Path, root: Path) -> Path:
    return Path(path.name) if root.is_file() else path.relative_to(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump LabArchives offline-export HTML pages to Markdown.")
    parser.add_argument("input", type=Path, help="HTML file or export directory")
    parser.add_argument("-o", "--output", type=Path, help="Output file for one HTML, or directory for many")
    parser.add_argument("--combine", type=Path, help="Combine all extracted pages into one Markdown file")
    parser.add_argument("--metadata", action="store_true", help="Include available entry author/date metadata")
    args = parser.parse_args()

    source = args.input.resolve()
    if not source.exists():
        parser.error(f"Input does not exist: {source}")
    files = find_html_files(source)
    if not files:
        parser.error(f"No HTML files found under: {source}")
    extracted = [(path, extract_page(path, args.metadata)) for path in files]

    if args.combine:
        args.combine.parent.mkdir(parents=True, exist_ok=True)
        args.combine.write_text("\n\n---\n\n".join(text.rstrip() for _, text in extracted) + "\n", encoding="utf-8")
        print(f"Wrote {args.combine} ({len(extracted)} pages)")
        return 0

    if len(extracted) == 1 and (args.output is None or args.output.suffix):
        destination = args.output or extracted[0][0].with_suffix(".md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(extracted[0][1], encoding="utf-8")
        print(f"Wrote {destination}")
        return 0

    output_dir = args.output or Path("labarchives_text")
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, text in extracted:
        destination = output_dir / safe_relative(path, source).with_suffix(".md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(f"Wrote {len(extracted)} pages under {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
