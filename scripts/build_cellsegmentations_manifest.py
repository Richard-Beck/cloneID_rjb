#!/usr/bin/env python3
"""Inventory only a configured CellSegmentations tree without loading image pixels.

Symlinks are recorded but never followed. All recorded paths are relative to root.
File classification and basename associations are candidates, not scientific QC.
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
from pathlib import Path
import re
import stat
import time

VERSION = '1.0.0'
IMAGE_EXTENSIONS = {'.tif', '.tiff', '.png', '.jpg', '.jpeg', '.bmp', '.gif'}
TABLE_EXTENSIONS = {'.csv', '.tsv', '.txt', '.parquet', '.feather'}
FIELDS = ['relative_path', 'entry_type', 'extension', 'product_kind', 'classification_basis',
          'size_bytes', 'modified_at', 'deprecated_or_auxiliary', 'association_key']


def utc(timestamp):
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat()


def classify(relative):
    path = Path(relative)
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    ext = path.suffix.lower()
    if ext in TABLE_EXTENSIONS and 'detectionresults' in parts:
        return 'per_cell_features_candidate', 'DetectionResults directory and table extension'
    if ext in TABLE_EXTENSIONS and any(x in name for x in ('feature', 'embedding', 'object')):
        return 'per_cell_features_candidate', 'filename and table extension'
    if ext in IMAGE_EXTENSIONS and 'overlay' in name:
        return 'segmentation_overlay', 'overlay filename and image extension'
    if ext in IMAGE_EXTENSIONS and re.search(r'(?:^|[_-])(?:masks?|labels?)(?:[_-]|$)', path.stem.lower()):
        return 'segmentation_mask_candidate', 'mask/label filename and image extension'
    if 'confluency' in parts:
        return 'confluency_output', 'Confluency directory'
    if 'annotations' in parts or ext == '.qpdata':
        return 'annotation', 'Annotations directory or qpdata extension'
    if ext in IMAGE_EXTENSIONS:
        return 'image_candidate', 'image extension'
    if ext in TABLE_EXTENSIONS:
        return 'table', 'table extension'
    if ext in {'.zip', '.tar', '.gz', '.7z'}:
        return 'archive', 'archive extension; contents not inspected'
    return 'other', 'unrecognized extension'


def association_key(relative, kind):
    if kind not in {'image_candidate', 'segmentation_overlay', 'segmentation_mask_candidate', 'per_cell_features_candidate'}:
        return ''
    stem = Path(relative).stem
    # Strip only explicit conventional product suffixes, preserving all acquisition tokens.
    stem = re.sub(r'(?i)(?:_mask_overlay|_overlay|_masks?|_labels?|_features|_embeddings)$', '', stem)
    return stem


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.environ.get('CELLSEGMENTATIONS_ROOT'),
                        help='CellSegmentations mount (or set CELLSEGMENTATIONS_ROOT)')
    parser.add_argument('--output-dir', default='tmp/checkpoint/imaging')
    parser.add_argument('--max-seconds', type=float, default=480,
                        help='Bound scan time; incomplete scans exit 2 (default 480 seconds)')
    parser.add_argument('--header-samples-per-directory', type=int, default=3)
    args = parser.parse_args()
    if not args.root:
        parser.error('--root or CELLSEGMENTATIONS_ROOT is required; mounts differ between machines')
    root = Path(args.root).resolve(strict=True)
    if not root.is_dir():
        parser.error('root must be a directory')
    out = Path(args.output_dir).resolve()
    if out == root or root in out.parents:
        parser.error('output directory must be outside the inventoried tree')
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    started = utc(time.time())
    counts = collections.Counter()
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    header_counts = collections.Counter()
    headers, errors = [], []
    newest = None
    complete = True
    scanned_dirs = 0
    stack = [root]
    with (out / 'files.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        while stack:
            directory = stack.pop()
            if time.monotonic() - start > args.max_seconds:
                complete = False
                errors.append({'relative_path': str(directory.relative_to(root)), 'error': 'scan time budget exceeded'})
                break
            try:
                with os.scandir(directory) as entries:
                    scanned_dirs += 1
                    for entry in entries:
                        if time.monotonic() - start > args.max_seconds:
                            complete = False
                            errors.append({'relative_path': str(directory.relative_to(root)), 'error': 'scan time budget exceeded'})
                            break
                        rel = str(Path(entry.path).relative_to(root))
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError as exc:
                            errors.append({'relative_path': rel, 'error': str(exc)})
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            stack.append(Path(entry.path))
                            continue
                        entry_type = 'file' if stat.S_ISREG(info.st_mode) else ('symlink' if stat.S_ISLNK(info.st_mode) else 'special')
                        kind, basis = classify(rel)
                        key = association_key(rel, kind) if entry_type == 'file' else ''
                        if entry_type == 'file':
                            newest = max(newest or info.st_mtime, info.st_mtime)
                        counts[kind if entry_type == 'file' else entry_type] += 1
                        auxiliary = any('deprecated' in x.lower() or x in {'todelete', '~', 'Countess', 'MycoplasmaTest'} for x in Path(rel).parts)
                        writer.writerow(dict(zip(FIELDS, [rel, entry_type, Path(rel).suffix.lower(), kind, basis,
                                                         info.st_size, utc(info.st_mtime), str(auxiliary).lower(), key])))
                        if key:
                            groups[key][kind].append(rel)
                        # A bounded header sample documents formats, never assumes uniform schemas.
                        parent_key = str(Path(rel).parent)
                        if entry_type == 'file' and Path(rel).suffix.lower() in {'.csv', '.tsv'} and header_counts[parent_key] < args.header_samples_per_directory:
                            header_counts[parent_key] += 1
                            try:
                                with open(entry.path, 'rb') as sample:
                                    line = sample.readline(16384).decode('utf-8-sig', errors='replace').strip('\r\n')
                                delim = '\t' if '\t' in line else ','
                                headers.append({'relative_path': rel, 'delimiter': 'tab' if delim == '\t' else 'comma',
                                                'columns': next(csv.reader([line], delimiter=delim)),
                                                'header_truncated': len(line) >= 16384})
                            except (OSError, csv.Error) as exc:
                                errors.append({'relative_path': rel, 'error': str(exc)})
                    if not complete:
                        break
            except OSError as exc:
                errors.append({'relative_path': str(directory.relative_to(root)), 'error': str(exc)})
    association_counts = collections.Counter()
    with (out / 'associations.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['association_key', 'status', 'products_json'])
        writer.writeheader()
        for key, products in sorted(groups.items()):
            image_count = len(products.get('image_candidate', []))
            features = bool(products.get('per_cell_features_candidate'))
            masks = bool(products.get('segmentation_mask_candidate'))
            if image_count > 1 or any(len(paths) > 1 for paths in products.values()):
                status = 'ambiguous_duplicate_basename'
            elif image_count == 1 and features and masks:
                status = 'candidate_image_features_mask_set'
            elif image_count == 1 and features:
                status = 'candidate_image_features_pair'
            elif image_count == 1 and masks:
                status = 'candidate_image_mask_pair'
            else:
                status = 'unpaired_or_other_products'
            association_counts[status] += 1
            writer.writerow({'association_key': key, 'status': status, 'products_json': json.dumps(products, sort_keys=True)})
    with (out / 'errors.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['relative_path', 'error'])
        writer.writeheader()
        writer.writerows(errors)
    (out / 'header_samples.json').write_text(json.dumps(headers, indent=2, ensure_ascii=False) + '\n')
    summary = {'schema_version': VERSION, 'generated_at': started, 'completed_at': utc(time.time()),
               'source_last_updated': utc(newest) if newest is not None else None,
               'source_last_updated_basis': 'maximum observed regular-file modification time; not acquisition time',
               'complete_scan': complete and not errors, 'time_budget_completed': complete,
               'errors': len(errors), 'directories_scanned': scanned_dirs,
               'entry_counts': dict(sorted(counts.items())), 'association_counts': dict(sorted(association_counts.items())),
               'header_samples': len(headers), 'symlinks_followed': False,
               'limitations': ['Filename and directory classifications are candidates.',
                               'Associations use exact case-sensitive basenames after explicit suffix removal; duplicates are ambiguous.',
                               'No image pixels, feature rows, archive contents, or scientific QC were read.',
                               'Headers are sampled per directory; feature schemas can vary.',
                               'Source can change during inventory; timestamps do not establish snapshot consistency.']}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary['complete_scan'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
