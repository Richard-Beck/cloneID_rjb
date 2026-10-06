#!/usr/bin/env python3
"""Relocate an extracted notebook snapshot's retrieval paths, keeping source text intact."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def contained_file(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ValueError(f"Unsafe inventory path: {name}")
    path = root.joinpath(*relative.parts)
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"Symlink in snapshot: {name}")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Missing or escaping snapshot file: {name}")
    return path


def relocate(root):
    metadata_path = contained_file(root, "snapshot-metadata.json")
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("id") != "notebooks":
        raise ValueError("Expected the extracted notebooks bundle")
    original = metadata["source"].get("source_project_root")
    if not original or not Path(original).is_absolute() or original == "/":
        raise ValueError("Notebook snapshot lacks a valid source_project_root")
    original = original.rstrip("/")
    files = [(contained_file(root, row["path"]), row) for row in metadata["inventory"]]
    record_path = root / "notebook-relocation.json"
    if record_path.is_symlink():
        raise ValueError("Symlink at relocation record path")
    if record_path.exists():
        record = json.loads(contained_file(root, record_path.name).read_text())
        if record.get("destination_root") == str(root):
            print("Notebook snapshot is already relocated to this root")
            return
        raise ValueError("Snapshot already relocated elsewhere; extract a fresh copy")
    for path, row in files:
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Original inventory hash mismatch: {row['path']}")

    def rebase(value):
        if isinstance(value, str) and value.startswith(original + "/"):
            candidate = root / value[len(original) + 1:]
            if candidate.exists() and candidate.resolve().is_relative_to(root):
                return str(candidate)
        return value

    # Preserve notebook narrative/source text and historical source provenance.
    path_keys = {"path", "notebook_path", "source_manifest", "run_dir", "output_dir",
                 "source_html", "html_text_extractor", "episodes", "edges", "nodes"}

    def update_json(value, key=None):
        if key in {"source_provenance", "source_segments", "compressed_text", "source_accounting"}:
            return value
        if isinstance(value, dict):
            updated = {k: update_json(v, k) for k, v in value.items()}
            if "notebook_path" in value and "notebook_id" in value:
                reference = metadata["source"]["source_references"].get("Compressed notebooks", "")
                candidate = rebase(reference)
                result = Path(candidate) / value["notebook_id"] / "final_message.json"
                if result.is_file() and result.resolve().is_relative_to(root):
                    updated["notebook_path"] = str(result)
            return updated
        if isinstance(value, list):
            return [update_json(item, key) for item in value]
        return rebase(value) if key in path_keys else value

    changes = []
    for path, row in files:
        original_bytes = path.read_bytes()
        replacement = original_bytes
        if path.name == "sources.md":
            text = original_bytes.decode()
            for reference in metadata["source"].get("source_references", {}).values():
                text = text.replace("`" + reference + "`", "`" + rebase(reference) + "`")
            replacement = text.encode()
        elif path.suffix == ".json":
            data = json.loads(original_bytes)
            updated = update_json(data)
            if updated != data:
                replacement = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode()
        if replacement != original_bytes:
            backup = path.with_name(path.name + ".original")
            if backup.exists() or backup.is_symlink():
                raise ValueError(f"Original backup already exists: {backup}")
            changes.append((path, backup, replacement, row["path"]))
    # Prepare every edit before writing. The untouched metadata and .original
    # backups retain the published inventory hashes for original-byte validation.
    for path, backup, replacement, name in changes:
        backup.write_bytes(path.read_bytes())
        path.write_bytes(replacement)
    record_path.write_text(json.dumps({"source_project_root": original,
                                      "destination_root": str(root),
                                      "changed_files": [name for _, _, _, name in changes],
                                      "inventory_hashes": "Refer to original bytes / .original backups"}, indent=2) + "\n")
    print(f"Relocated {len(changes)} files; original metadata and source text retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Root of the separately extracted notebooks bundle")
    args = parser.parse_args()
    relocate(args.root.resolve())


if __name__ == "__main__":
    main()
