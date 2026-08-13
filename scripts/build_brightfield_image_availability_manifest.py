#!/usr/bin/env python3

import argparse
import csv
from collections import defaultdict
from pathlib import Path


EXPECTED_TILES = ("bl", "br", "tl", "tr")
RAW_EXTENSIONS = {"tif", "tiff"}
DEFAULT_IMAGE_MANIFEST = Path(
    "/share/lab_crd/lab_crd/CLONEID/anaMorph/manifests/image_manifest.csv"
)
DEFAULT_LTEE_INPUT_DIR = Path("/share/lab_crd/lab_crd/CLONEID/data/LTEEs/input")


def collapse(values):
    clean = []
    seen = set()
    for value in values:
        if value is None:
            continue
        value = str(value)
        if value == "" or value in seen:
            continue
        seen.add(value)
        clean.append(value)
    return "|".join(clean)


def true_false(value):
    return "TRUE" if value else "FALSE"


def resolve_existing_path(manifest_path, filename, ltee_input_dir):
    candidates = []
    if manifest_path:
        path = Path(manifest_path)
        candidates.append(path)
        as_text = str(path)
        if "/data/LTEEs/" in as_text and "/data/LTEEs/input/" not in as_text:
            candidates.append(Path(as_text.replace("/data/LTEEs/", "/data/LTEEs/input/")))
    if filename:
        candidates.append(ltee_input_dir / filename)

    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return key
    return ""


def read_passaging(path):
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "id" not in rows[0]:
        raise ValueError(f"{path} must contain an id column")
    return rows


def read_manifest(path, passaging_ids, ltee_input_dir):
    by_passage_id = defaultdict(list)
    raw_tiff_rows = 0
    matched_raw_tiff_rows = 0
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("artifact_type") != "raw_image":
                continue
            if row.get("ext", "").lower() not in RAW_EXTENSIONS:
                continue
            raw_tiff_rows += 1
            passage_id = row.get("id", "")
            if passage_id not in passaging_ids:
                continue
            matched_raw_tiff_rows += 1
            row["_existing_path"] = resolve_existing_path(
                row.get("filepath", ""), row.get("filename", ""), ltee_input_dir
            )
            by_passage_id[passage_id].append(row)
    return by_passage_id, raw_tiff_rows, matched_raw_tiff_rows


def build_row(passaging_row, image_rows, row_index):
    rows_by_tile = defaultdict(list)
    for image_row in image_rows:
        rows_by_tile[image_row.get("field", "")].append(image_row)

    manifest_tiles = [tile for tile in EXPECTED_TILES if rows_by_tile.get(tile)]
    existing_tiles = [
        tile
        for tile in EXPECTED_TILES
        if any(row.get("_existing_path") for row in rows_by_tile.get(tile, []))
    ]
    manifest_missing = [tile for tile in EXPECTED_TILES if tile not in manifest_tiles]
    existing_missing = [tile for tile in EXPECTED_TILES if tile not in existing_tiles]

    out = {
        "passaging_row_index": row_index,
        "passage_id": passaging_row.get("id", ""),
        "cellLine": passaging_row.get("cellLine", ""),
        "event": passaging_row.get("event", ""),
        "passage": passaging_row.get("passage", ""),
        "date": passaging_row.get("date", ""),
        "media": passaging_row.get("media", ""),
        "growthType": passaging_row.get("growthType", ""),
        "condition_label": collapse(row.get("condition_label", "") for row in image_rows),
        "raw_brightfield_manifest_file_count": len(image_rows),
        "existing_brightfield_file_count": sum(
            1 for row in image_rows if row.get("_existing_path")
        ),
        "has_any_brightfield_manifest_entry": true_false(bool(image_rows)),
        "has_any_existing_brightfield_file": true_false(
            any(row.get("_existing_path") for row in image_rows)
        ),
        "has_complete_4_tile_manifest_set": true_false(
            len(manifest_tiles) == len(EXPECTED_TILES)
        ),
        "has_complete_existing_4_tile_set": true_false(
            len(existing_tiles) == len(EXPECTED_TILES)
        ),
        "manifest_available_tiles": collapse(manifest_tiles),
        "manifest_missing_tiles": collapse(manifest_missing),
        "existing_available_tiles": collapse(existing_tiles),
        "existing_missing_tiles": collapse(existing_missing),
    }

    for tile in EXPECTED_TILES:
        tile_rows = sorted(rows_by_tile.get(tile, []), key=lambda row: row.get("filename", ""))
        existing_paths = [row.get("_existing_path", "") for row in tile_rows]
        out[f"tile_{tile}_manifest_path"] = collapse(
            row.get("filepath", "") for row in tile_rows
        )
        out[f"tile_{tile}_existing_path"] = collapse(existing_paths)
        out[f"tile_{tile}_file_exists"] = true_false(any(existing_paths))

    return out


def write_manifest(passaging_rows, image_rows_by_id, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        build_row(passaging_row, image_rows_by_id.get(passaging_row["id"], []), index)
        for index, passaging_row in enumerate(passaging_rows, start=1)
    ]

    fieldnames = list(rows[0].keys()) if rows else []
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def summarize(rows, raw_tiff_rows, matched_raw_tiff_rows):
    matched_ids = sum(
        1 for row in rows if row["has_any_brightfield_manifest_entry"] == "TRUE"
    )
    complete_manifest = sum(
        1 for row in rows if row["has_complete_4_tile_manifest_set"] == "TRUE"
    )
    complete_existing = sum(
        1 for row in rows if row["has_complete_existing_4_tile_set"] == "TRUE"
    )
    no_image = len(rows) - matched_ids
    existing_files = sum(int(row["existing_brightfield_file_count"]) for row in rows)
    return {
        "passaging_rows": len(rows),
        "source_raw_tiff_rows": raw_tiff_rows,
        "matched_raw_tiff_rows": matched_raw_tiff_rows,
        "existing_matched_raw_tiff_files": existing_files,
        "passaging_ids_with_images": matched_ids,
        "passaging_ids_with_complete_4_tile_manifest_set": complete_manifest,
        "passaging_ids_with_complete_existing_4_tile_set": complete_existing,
        "passaging_ids_without_images": no_image,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build a passaging-row manifest of brightfield image availability."
    )
    parser.add_argument(
        "--passaging",
        type=Path,
        default=Path("core_data/passaging.csv"),
        help="Passaging CSV with an id column.",
    )
    parser.add_argument(
        "--image-manifest",
        type=Path,
        default=DEFAULT_IMAGE_MANIFEST,
        help="Image manifest from anaMorph.",
    )
    parser.add_argument(
        "--ltee-input-dir",
        type=Path,
        default=DEFAULT_LTEE_INPUT_DIR,
        help="Current directory containing raw LTEE input TIFFs.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/brightfield_image_availability_manifest.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args()

    passaging_rows = read_passaging(args.passaging)
    passaging_ids = {row["id"] for row in passaging_rows}
    image_rows_by_id, raw_tiff_rows, matched_raw_tiff_rows = read_manifest(
        args.image_manifest, passaging_ids, args.ltee_input_dir
    )
    rows = write_manifest(passaging_rows, image_rows_by_id, args.out)
    summary = summarize(rows, raw_tiff_rows, matched_raw_tiff_rows)

    print(f"wrote {args.out}")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
