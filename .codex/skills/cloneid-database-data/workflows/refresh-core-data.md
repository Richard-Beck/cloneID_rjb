# Refresh Core Database Snapshot

Run this workflow only after a user specifically requests a database download or refresh. Do not run it during routine querying, input
validation, cleaned-metadata rebuilds, or analysis merely because `core_data` might be stale. Never overwrite canonical files automatically.

## 1. Check credentials before doing anything else

Resolve the credential file in this order:

1. A path explicitly supplied by the user.
2. `CLONEID_DB_CREDENTIALS_FILE` when set.
3. `~/.config/cloneid/db.env`.

Confirm the selected path is a regular file without printing its contents. If no credential file exists, stop and instruct the user to create
`~/.config/cloneid` with mode `700`, then create `~/.config/cloneid/db.env` with mode `600` containing:

```text
CLONEID_DB_HOST='database-host'
CLONEID_DB_PORT='3306'
CLONEID_DB_USER='read-only-user'
CLONEID_DB_PASSWORD='database-password'
CLONEID_DB_NAME='CLONEID'
# CLONEID_DB_SSL_CA='/path/to/server-ca.pem'
```

Tell the user to use a database account limited to `SELECT` on `Passaging`, `Media`, `Perspective`, and `LiquidNitrogen`. Do not ask the user to paste
credentials into chat, do not display the file, and do not place it in the repository. Wait for the user to confirm that the file is ready
before continuing. The refresh script rejects credential files accessible by group or other users.

## 2. Download a staged bundle

From the repository root, run:

```bash
.codex/skills/cloneid-database-data/scripts/run_core_data_refresh.sh
```

Pass `--credentials-file PATH` when using a nondefault file. If the configured database name is missing or uncertain, rerun with
`--discover-database`; discovery reads only database metadata and requires exactly one accessible schema containing all four required tables.

The default destination is:

```text
tmp/core_data_refresh/<UTC timestamp>/
```

The script reads all Passaging, Media, and LiquidNitrogen columns. It exports Perspective as one row per `(whichPerspective, origin)`, with
`n` equal to `COUNT(*)`. All four reads occur in one transaction. The script never writes to `core_data`.

The raw CSVs under `core_data/` are local inputs and are intentionally excluded from Git. On a fresh clone, the refresh works without an
existing baseline: every downloaded row is reported as an addition. When local baseline CSVs exist, they are archived and compared as usual.

## 3. Validate and review

Let `RUN` be the completed timestamped directory. Run:

```bash
.codex/skills/cloneid-database-data/scripts/validate_core_inputs.py \
  --core-dir "$RUN/snapshot"
```

This validator covers the three downstream metadata inputs. The refresh itself verifies that LiquidNitrogen has a complete, unique
`(Rack, Row, BoxRow, BoxColumn)` key before writing the snapshot.

Review:

- `diff_summary.csv` for row, cell, and schema-change counts.
- `diffs/*_diff.csv` for detailed changes.
- `manifest.csv` for baseline and snapshot SHA-256 hashes.
- `schema.csv` and `RUN_METADATA` for provenance.
- `baseline/` for the exact pre-refresh canonical files.

When a newly added table has no canonical baseline, its manifest row has `baseline_present=FALSE`, its baseline hash is blank, and its rows
are reported as additions; the other canonical baselines are still archived normally.

Confirm no tracked files were modified. Report the bundle path, table counts, added/removed/modified counts, validation warnings, and unusual
date or schema changes. Different byte hashes with zero logical changes can result from deterministic sorting and CSV serialization.

## 4. Keep promotion separate

Do not promote the snapshot as part of this workflow. Replace local canonical `core_data` files only after a separate, explicit user request
and review. Retain the refresh bundle until the user accepts or rejects it. Never commit raw snapshots or temporary refresh bundles.
