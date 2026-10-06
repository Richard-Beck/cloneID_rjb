# Publishing encrypted research snapshots

The repository contains skills, documentation, packaging scripts, and the static download page source. Research snapshots stay outside
Git history: encrypted archives are GitHub Release attachments, and a manually dispatched Pages workflow copies them into its deployment
artifact. This document describes the publication process; it does not indicate that a snapshot has already been published.

The three downloads contain:

- `tables`: raw passaging, media, and LN tables, plus the supporting tables and available prepared database products needed by the skills.
- `notebooks`: the fully processed notebook collection, supporting extracted source packets, compression audit, and live instance/protocol
  Markdown database. Processing completeness does not imply that every interpretation has received manual review; see the encrypted audit.
- `imaging`: the recursive CellSegmentations manifest, image/segmentation/feature associations, sampled feature schemas, and scan diagnostics.
  This is an inventory; microscopy images and segmentation outputs themselves are not bundled.

## Prepare locally

Generate the source plan and recursive imaging manifest using the repository scripts. See the imaging documentation for RED and workstation
mount configuration. Packaging uses `tmp/checkpoint/source-plan.json` and `tmp/checkpoint/imaging/` by default.

```sh
python3 scripts/checkpoint_sources.py
python3 scripts/package_checkpoint.py
```

The packaging command prompts for a shared password twice. It creates `tmp/checkpoint/encrypted/`, containing three `.tar.gz.gpg` files
and a public `snapshot.json`. The password goes to GPG through a pipe; it is not put in a command argument or environment variable. GPG
uses password-based AES256 encryption. Share the password separately with the intended users.

For unattended packaging, `--password-file tmp/checkpoint/password.txt` reads an existing Git-ignored local file. Create that file securely
outside shell history, restrict its permissions, and remove it when no longer needed. Do not commit it or upload it to GitHub.

Every bundle is decrypted locally after encryption. The script checks both the full archive hash and the size/hash of every archived source
file before returning success. Plain temporary archives are removed when the command exits normally, including validation failures.
Existing published-output names are never overwritten; use `--output tmp/checkpoint/encrypted-<date>` for another snapshot.

## Dates and provenance

The public manifest records a packaging timestamp, each download's size and SHA256 checksum, and its source last-updated timestamp. The
passaging and notebook timestamps come from the latest apparent modification time of their raw underlying files, not the date of
packaging or semantic review. File modification timestamps may reflect copying or extraction; they are an observable freshness proxy.
The encrypted metadata retains source details and limitations so those dates can be audited.

The imaging timestamp is the latest regular-file modification time seen in CellSegmentations. The packaging command requires a complete
scan when it reads the generated imaging summary. Detailed paths, filenames, clone IDs, and source provenance remain inside the encrypted
archives. The public page displays download descriptions, dates, sizes, and checksums.

## Publish outside Git history

Commit the selected skills, docs, scripts, and page/workflow source first. Attach only the three encrypted archives and their public
`snapshot.json` to a GitHub Release targeting that checkpoint commit. Do not attach the source plan, plaintext notebook, imaging CSVs,
or password. Release attachments are stored separately from Git objects.

The Pages workflow must be present on the repository’s default branch before it can be dispatched. Integrate the reviewed checkpoint
into that branch before publication. After pushing the checkpoint commit, use the publication helper. Replace the example tag and commit SHA with the selected snapshot tag
and full pushed checkpoint commit SHA:

```sh
python3 scripts/publish_checkpoint.py --assets tmp/checkpoint/encrypted --tag snapshots-YYYYMMDD --target PUSHED_COMMIT_SHA
```

The helper validates the public manifest and archive checksums and refuses to replace an existing release. To preview the page locally:

```sh
python3 scripts/build_download_page.py --assets tmp/checkpoint/encrypted --output tmp/checkpoint/site-preview
```

Configure GitHub Pages to use GitHub Actions. Dispatch the repository's Pages publication workflow with the release tag to publish the
download page. The workflow retrieves that release's assets, verifies checksums, and includes them in its Pages artifact. Subsequent page
deployments can retrieve the same release again without putting encrypted research files into the repository.

For a repository where Pages has not been configured, enable its Actions deployment once, then dispatch publication:

```sh
gh api --method POST repos/Richard-Beck/cloneID_rjb/pages -f build_type=workflow
gh workflow run downloads-pages.yml -f release_tag=snapshots-YYYYMMDD
```

Do not reuse or replace an existing snapshot tag when updating data. Create a new snapshot release so older citations retain their dates
and checksums. Downloads are publicly accessible ciphertext; anyone holding the shared password can decrypt them.

## Download and decrypt

Download a bundle from the static page. Compare its SHA256 checksum with the page or `snapshot.json`, then decrypt and extract it in a
local working directory:

```sh
sha256sum cloneid-tables-<timestamp>.tar.gz.gpg
gpg --output tables.tar.gz --decrypt cloneid-tables-<timestamp>.tar.gz.gpg
tar -tzf tables.tar.gz
tar -xzf tables.tar.gz
```

GPG prompts for the shared password. Each archive preserves repository-relative paths and includes `snapshot-metadata.json` with source
refresh evidence and a complete file inventory. Extract into a separate directory first and inspect that metadata before restoring files
into an existing research checkout. These restored database and notebook files are local state and must stay uncommitted.

For the notebook bundle, relocate retrieval paths after extraction and before running skills. Pass the directory containing the notebook
bundle's `snapshot-metadata.json`:

```sh
python3 scripts/relocate_notebook_snapshot.py --root /path/to/extracted-notebooks
```

The helper verifies the original inventory hashes, updates `sources.md` and available JSON retrieval paths, and saves `.original` backups
of changed files. Notebook narrative, complete source-span text, and historical source provenance remain intact. Original metadata hashes
describe the published bytes, including the backups; they are not regenerated for relocated files. Use this extracted directory as the
notebook data root, or run relocation after copying the intact bundle into its final checkout location.
