#!/usr/bin/env python3

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


EXPECTED_TILES = ("bl", "br", "tl", "tr")
IMAGE_STEM_RE = re.compile(r"^(?P<passage_id>.+)_10x_ph_(?P<tile>bl|br|tl|tr)$")

DEFAULT_LEGACY_ROOT = Path("/share/lab_crd/lab_crd/CLONEID/data/LTEEs/output")
DEFAULT_ANAMORPH_ROOT = Path("/share/lab_crd/lab_crd/CLONEID/anaMorph")


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


def parse_image_stem(path, suffix):
    name = path.name
    if suffix and not name.endswith(suffix):
        return None
    stem = name[: -len(suffix)] if suffix else path.stem
    match = IMAGE_STEM_RE.match(stem)
    if not match:
        return None
    return match.group("passage_id"), match.group("tile")


def count_csv_data_rows(path):
    try:
        with path.open(newline="") as handle:
            row_count = sum(1 for _ in handle)
    except OSError:
        return ""
    return max(row_count - 1, 0)


def read_passaging(path):
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "id" not in rows[0]:
        raise ValueError(f"{path} must contain an id column")
    return rows


def read_legacy_features(legacy_root, passaging_ids):
    detection_dir = legacy_root / "DetectionResults"
    mask_dir = legacy_root / "Masks"
    image_dir = legacy_root / "Images"

    records = defaultdict(dict)
    source_file_count = 0
    matched_file_count = 0
    matched_object_count = 0

    for path in sorted(detection_dir.glob("*.csv")):
        parsed = parse_image_stem(path, ".csv")
        if parsed is None:
            continue
        source_file_count += 1
        passage_id, tile = parsed
        if passage_id not in passaging_ids:
            continue
        matched_file_count += 1
        object_count = count_csv_data_rows(path)
        if isinstance(object_count, int):
            matched_object_count += object_count
        stem = path.stem
        mask_path = mask_dir / f"{stem}_masks.tif"
        overlay_path = image_dir / f"{stem}_mask_overlay.tif"
        records[passage_id][tile] = {
            "detection_csv": str(path),
            "mask_path": str(mask_path) if mask_path.exists() else "",
            "overlay_path": str(overlay_path) if overlay_path.exists() else "",
            "object_count": object_count,
        }

    summary = {
        "legacy_source_detection_csvs": source_file_count,
        "legacy_matched_detection_csvs": matched_file_count,
        "legacy_matched_object_rows": matched_object_count,
    }
    return records, summary


def absolute_anamorph_path(anamorph_root, relpath):
    if not relpath:
        return ""
    path = Path(relpath)
    if path.is_absolute():
        return str(path)
    return str(anamorph_root / relpath)


def read_anamorph_segmentation(anamorph_root, passaging_ids):
    manifest_path = anamorph_root / "data/all_images/manifests/segmentation_images.csv"
    records = defaultdict(dict)
    source_rows = 0
    matched_rows = 0
    matched_objects = 0
    matched_embeddings = 0

    with manifest_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            source_rows += 1
            passage_id = row.get("id", "")
            tile = row.get("field", "")
            if passage_id not in passaging_ids or tile not in EXPECTED_TILES:
                continue
            matched_rows += 1
            object_count = int(row.get("object_count") or 0)
            embedding_count = int(row.get("embedding_count") or 0)
            matched_objects += object_count
            matched_embeddings += embedding_count
            records[passage_id][tile] = {
                "filename": row.get("filename", ""),
                "mask_path": absolute_anamorph_path(anamorph_root, row.get("mask_relpath", "")),
                "object_embedding_csv": absolute_anamorph_path(
                    anamorph_root, row.get("embedding_relpath", "")
                ),
                "object_count": object_count,
                "embedding_count": embedding_count,
                "embedding_dim": row.get("embedding_dim", ""),
                "crop_height": row.get("crop_height", ""),
                "crop_width": row.get("crop_width", ""),
                "run_id": row.get("run_id", ""),
                "timestamp_utc": row.get("timestamp_utc", ""),
            }

    summary = {
        "anamorph_segmentation_rows": source_rows,
        "anamorph_matched_segmentation_rows": matched_rows,
        "anamorph_matched_object_count": matched_objects,
        "anamorph_matched_object_embedding_count": matched_embeddings,
    }
    return records, summary


def read_anamorph_raw_image_embeddings(anamorph_root, passaging_ids):
    manifest_path = anamorph_root / "data/all_images/manifests/raw_image_embeddings.csv"
    records = defaultdict(set)
    source_rows = 0
    matched_rows = 0

    with manifest_path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        id_idx = header.index("id")
        field_idx = header.index("field")
        for row in reader:
            source_rows += 1
            passage_id = row[id_idx]
            tile = row[field_idx]
            if passage_id not in passaging_ids or tile not in EXPECTED_TILES:
                continue
            matched_rows += 1
            records[passage_id].add(tile)

    summary = {
        "anamorph_raw_image_embedding_rows": source_rows,
        "anamorph_matched_raw_image_embedding_rows": matched_rows,
    }
    return records, summary


def available_tiles(tile_records):
    return [tile for tile in EXPECTED_TILES if tile in tile_records]


def missing_tiles(tile_records):
    present = set(available_tiles(tile_records))
    return [tile for tile in EXPECTED_TILES if tile not in present]


def build_row(
    passaging_row,
    row_index,
    legacy_records,
    anamorph_records,
    anamorph_raw_embedding_tiles,
    anamorph_raw_embedding_manifest,
):
    passage_id = passaging_row["id"]
    legacy_tiles = legacy_records.get(passage_id, {})
    anamorph_tiles = anamorph_records.get(passage_id, {})
    raw_embedding_tiles = anamorph_raw_embedding_tiles.get(passage_id, set())

    legacy_available = available_tiles(legacy_tiles)
    anamorph_available = available_tiles(anamorph_tiles)
    raw_embedding_available = [tile for tile in EXPECTED_TILES if tile in raw_embedding_tiles]

    out = {
        "passaging_row_index": row_index,
        "passage_id": passage_id,
        "cellLine": passaging_row.get("cellLine", ""),
        "event": passaging_row.get("event", ""),
        "passage": passaging_row.get("passage", ""),
        "date": passaging_row.get("date", ""),
        "media": passaging_row.get("media", ""),
        "growthType": passaging_row.get("growthType", ""),
        "preferred_initial_feature_source": "legacy_detection_results"
        if legacy_available
        else ("anamorph_cellpose_resnet" if anamorph_available else ""),
        "has_any_feature_source": true_false(bool(legacy_available or anamorph_available)),
        "has_both_feature_sources": true_false(bool(legacy_available and anamorph_available)),
        "legacy_feature_family": "classical_morphology_intensity",
        "legacy_feature_columns": "Centroid X um|Centroid Y um|Area um2|perimeter um|roundness|ROI|aspect_ratio|extent|solidity|equi_diameter|Major_Axis|Minor_Axis|Orientation|min_val|max_val|mean_val",
        "legacy_detection_csv_count": len(legacy_available),
        "legacy_object_count": sum(
            int(legacy_tiles[tile]["object_count"]) for tile in legacy_available
        ),
        "legacy_has_any_detection_csv": true_false(bool(legacy_available)),
        "legacy_has_complete_4_tile_set": true_false(
            len(legacy_available) == len(EXPECTED_TILES)
        ),
        "legacy_available_tiles": collapse(legacy_available),
        "legacy_missing_tiles": collapse(missing_tiles(legacy_tiles)),
        "anamorph_feature_family": "cellpose_objects_resnet18_embeddings",
        "anamorph_segmentation_count": len(anamorph_available),
        "anamorph_object_count": sum(
            int(anamorph_tiles[tile]["object_count"]) for tile in anamorph_available
        ),
        "anamorph_object_embedding_count": sum(
            int(anamorph_tiles[tile]["embedding_count"]) for tile in anamorph_available
        ),
        "anamorph_has_any_segmentation": true_false(bool(anamorph_available)),
        "anamorph_has_complete_4_tile_segmentation_set": true_false(
            len(anamorph_available) == len(EXPECTED_TILES)
        ),
        "anamorph_available_tiles": collapse(anamorph_available),
        "anamorph_missing_tiles": collapse(missing_tiles(anamorph_tiles)),
        "anamorph_raw_image_embedding_manifest": str(anamorph_raw_embedding_manifest),
        "anamorph_raw_image_embedding_count": len(raw_embedding_available),
        "anamorph_has_any_raw_image_embedding": true_false(bool(raw_embedding_available)),
        "anamorph_has_complete_4_tile_raw_image_embedding_set": true_false(
            len(raw_embedding_available) == len(EXPECTED_TILES)
        ),
        "anamorph_raw_image_embedding_available_tiles": collapse(raw_embedding_available),
    }

    for tile in EXPECTED_TILES:
        legacy = legacy_tiles.get(tile, {})
        out[f"legacy_{tile}_detection_csv"] = legacy.get("detection_csv", "")
        out[f"legacy_{tile}_mask_path"] = legacy.get("mask_path", "")
        out[f"legacy_{tile}_overlay_path"] = legacy.get("overlay_path", "")
        out[f"legacy_{tile}_object_count"] = legacy.get("object_count", "")

    for tile in EXPECTED_TILES:
        anamorph = anamorph_tiles.get(tile, {})
        out[f"anamorph_{tile}_mask_path"] = anamorph.get("mask_path", "")
        out[f"anamorph_{tile}_object_embedding_csv"] = anamorph.get(
            "object_embedding_csv", ""
        )
        out[f"anamorph_{tile}_object_count"] = anamorph.get("object_count", "")
        out[f"anamorph_{tile}_object_embedding_count"] = anamorph.get(
            "embedding_count", ""
        )
        out[f"anamorph_{tile}_raw_image_embedding_available"] = true_false(
            tile in raw_embedding_tiles
        )

    return out


def write_manifest(
    passaging_rows,
    legacy_records,
    anamorph_records,
    anamorph_raw_embedding_tiles,
    anamorph_raw_embedding_manifest,
    out_path,
):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        build_row(
            passaging_row,
            row_index,
            legacy_records,
            anamorph_records,
            anamorph_raw_embedding_tiles,
            anamorph_raw_embedding_manifest,
        )
        for row_index, passaging_row in enumerate(passaging_rows, start=1)
    ]
    fieldnames = list(rows[0].keys()) if rows else []
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def summarize(rows, source_summaries):
    summary = {
        "passaging_rows": len(rows),
        "passaging_ids_with_any_feature_source": sum(
            row["has_any_feature_source"] == "TRUE" for row in rows
        ),
        "passaging_ids_with_both_feature_sources": sum(
            row["has_both_feature_sources"] == "TRUE" for row in rows
        ),
        "passaging_ids_with_legacy_features": sum(
            row["legacy_has_any_detection_csv"] == "TRUE" for row in rows
        ),
        "passaging_ids_with_complete_legacy_4_tile_set": sum(
            row["legacy_has_complete_4_tile_set"] == "TRUE" for row in rows
        ),
        "legacy_object_rows": sum(int(row["legacy_object_count"]) for row in rows),
        "passaging_ids_with_anamorph_segmentation": sum(
            row["anamorph_has_any_segmentation"] == "TRUE" for row in rows
        ),
        "passaging_ids_with_complete_anamorph_4_tile_set": sum(
            row["anamorph_has_complete_4_tile_segmentation_set"] == "TRUE"
            for row in rows
        ),
        "anamorph_objects": sum(int(row["anamorph_object_count"]) for row in rows),
        "anamorph_object_embeddings": sum(
            int(row["anamorph_object_embedding_count"]) for row in rows
        ),
        "passaging_ids_with_anamorph_raw_image_embeddings": sum(
            row["anamorph_has_any_raw_image_embedding"] == "TRUE" for row in rows
        ),
        "passaging_ids_with_complete_anamorph_raw_image_embedding_4_tile_set": sum(
            row["anamorph_has_complete_4_tile_raw_image_embedding_set"] == "TRUE"
            for row in rows
        ),
    }
    summary.update(source_summaries)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Build a passaging-row manifest of existing brightfield feature sets."
    )
    parser.add_argument(
        "--passaging",
        type=Path,
        default=Path("core_data/passaging.csv"),
        help="Passaging CSV with an id column.",
    )
    parser.add_argument(
        "--legacy-root",
        type=Path,
        default=DEFAULT_LEGACY_ROOT,
        help="LTEE output root containing DetectionResults, Masks, and Images.",
    )
    parser.add_argument(
        "--anamorph-root",
        type=Path,
        default=DEFAULT_ANAMORPH_ROOT,
        help="anaMorph repository root containing data/all_images outputs.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/brightfield_feature_availability_manifest.csv"),
        help="Output CSV path.",
    )
    args = parser.parse_args()

    passaging_rows = read_passaging(args.passaging)
    passaging_ids = {row["id"] for row in passaging_rows}

    legacy_records, legacy_summary = read_legacy_features(args.legacy_root, passaging_ids)
    anamorph_records, anamorph_summary = read_anamorph_segmentation(
        args.anamorph_root, passaging_ids
    )
    raw_embedding_manifest = (
        args.anamorph_root / "data/all_images/manifests/raw_image_embeddings.csv"
    )
    raw_embedding_tiles, raw_embedding_summary = read_anamorph_raw_image_embeddings(
        args.anamorph_root, passaging_ids
    )

    rows = write_manifest(
        passaging_rows,
        legacy_records,
        anamorph_records,
        raw_embedding_tiles,
        raw_embedding_manifest,
        args.out,
    )
    summary = summarize(
        rows,
        {
            **legacy_summary,
            **anamorph_summary,
            **raw_embedding_summary,
        },
    )

    print(f"wrote {args.out}")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
