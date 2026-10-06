#!/usr/bin/env python3
"""Upload verified encrypted downloads as a new GitHub release (never Git blobs)."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from build_download_page import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--target', required=True, help='Already pushed checkpoint commit SHA')
    parser.add_argument('--repo', default='Richard-Beck/cloneID_rjb')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='cloneid-page-check-') as check:
        build(args.assets, Path(check))
    data = json.loads((args.assets / 'snapshot.json').read_text())
    files = [str(args.assets / 'snapshot.json')] + [str(args.assets / b['filename']) for b in data['bundles']]
    # Never replace existing assets or silently attach them to an unrelated commit.
    exists = subprocess.run(['gh', 'release', 'view', args.tag, '--repo', args.repo], capture_output=True)
    if exists.returncode == 0:
        parser.error('Release already exists; choose a new tag')
    notes = 'Password-encrypted collaborator snapshots. Source dates are apparent raw-file modification times. See snapshot.json and the download page for dates and SHA-256 checksums.'
    subprocess.run(['gh', 'release', 'create', args.tag, *files, '--repo', args.repo,
                    '--target', args.target, '--title', 'Research snapshots ' + args.tag,
                    '--notes', notes, '--latest=false'], check=True)
    print('Uploaded encrypted assets. Publish the page with:')
    print('gh workflow run downloads-pages.yml --repo ' + args.repo + ' -f release_tag=' + args.tag)


if __name__ == '__main__':
    main()
