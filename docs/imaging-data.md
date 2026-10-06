# Imaging and segmentation data

Use **CellSegmentations and all its subdirectories** as the supported source of imaging and segmentation data. It contains images,
segmentation outputs, and per-cell feature tables. Older inventory scripts that search other storage roots do not define this checkpoint's
available dataset.

## Configure the mount

On RED, CellSegmentations is at `/share/lab_crd/CellSegmentations`. It is also mounted on the workstation; use the mount path available there.
The RED path is not a portable default. Configure the root separately on each machine:

```bash
# RED
export CELLSEGMENTATIONS_ROOT=/share/lab_crd/CellSegmentations

# On the workstation, substitute its local mount path instead.
# export CELLSEGMENTATIONS_ROOT=/your/mount/CellSegmentations
```

The downloadable encrypted manifest contains paths relative to this root. Resolve a file as `CELLSEGMENTATIONS_ROOT / relative_path`.
The manifest inventories available files; the images and segmentation data themselves are not distributed with the repository or downloads.

## Build a fresh inventory

Python 3's standard library is sufficient:

```bash
python3 scripts/build_cellsegmentations_manifest.py --output-dir tmp/checkpoint/imaging
```

Alternatively, pass `--root /your/mount/CellSegmentations`. Output must be outside the inventoried tree. The scan includes deprecated and
auxiliary subdirectories, marks their files, and records symlinks without following them. Archives are listed without extracting their contents.
The default scan budget is eight minutes; exceeding it or encountering access errors produces an incomplete inventory and exit code 2.
If a scan needs more than ten minutes or other project compute thresholds, run it through SLURM rather than extending an interactive job.

The plaintext output stays local under `tmp/`; distribute it only through the password-encrypted snapshot packaging workflow.

## Read the inventory

- `files.csv`: relative path, entry type, extension, candidate product kind, classification basis, byte size, modification timestamp, auxiliary
  flag, and association key.
- `associations.csv`: products sharing an exact basename after stripping a small set of conventional suffixes such as `_masks` and `_overlay`.
  Candidate image/feature/mask sets are distinguished from duplicate-basename ambiguity and unpaired products. Names are case-sensitive;
  matching basenames do not establish scientific compatibility.
- `header_samples.json`: a bounded sample of CSV/TSV headers per directory, including the detected delimiter. Files ending in `.csv` may
  actually be tab-separated. DetectionResults samples contain per-cell positions and morphology features, and their schemas can differ.
- `summary.json`: scan completion, counts, timestamps, and limitations. `source_last_updated` is the latest observed regular-file modification
  time, not the acquisition date. A copied file or corrected output can change that date.
- `errors.csv`: skipped files/directories and scan-budget failures. Check `complete_scan` before treating absence from the manifest as evidence
  that a file is unavailable.

Image, mask, and per-cell feature classifications rely on directory names, filenames, and extensions. In particular, a table under
`DetectionResults` is a **per-cell features candidate**; only sampled headers have been inspected. No pixel data, full feature tables, object
counts, or model quality checks are read. Before analysis, verify the selected feature schema, image provenance, masks, units, and matching
acquisition in the actual files. Overlays are visualization products and do not by themselves establish that reusable label masks exist.
Files named as masks under `Confluency` are mask candidates, but may represent binary occupied regions rather than individually labelled
cells. Sampled Confluency tables describe island areas; sampled Annotations tables describe ROI summaries. These are distinct from the
per-cell DetectionResults tables.
