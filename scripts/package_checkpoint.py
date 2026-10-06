#!/usr/bin/env python3
"""Package local research snapshots with a shared password, outside Git."""
import argparse
import getpass
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def local_file(root, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'Expected a repository-relative path: {name}')
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Path leaves repository: {name}')
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Expected a regular file: {name}')
    return path


def crypt(source, target, password, decrypt=False):
    command = ['gpg', '--batch', '--yes', '--no-symkey-cache',
               '--pinentry-mode', 'loopback', '--passphrase-fd', '0',
               '--output', str(target)]
    command += ['--decrypt'] if decrypt else ['--symmetric', '--cipher-algo', 'AES256']
    command.append(str(source))
    result = subprocess.run(command, input=password + b'\n', capture_output=True)
    if result.returncode:
        raise RuntimeError('GPG failed: ' + result.stderr.decode(errors='replace'))


def verify_archive(path, inventory):
    expected = {row['path']: row for row in inventory}
    with tarfile.open(path, 'r:gz') as archive:
        seen = set()
        for member in archive.getmembers():
            if not member.isfile() or member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unexpected archive member')
            if member.name in seen:
                raise ValueError('Duplicate archive member')
            seen.add(member.name)
            if member.name == 'snapshot-metadata.json':
                continue
            row = expected.get(member.name)
            if row is None:
                raise ValueError('Unexpected archive file')
            stream = archive.extractfile(member)
            h = hashlib.sha256()
            size = 0
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
                size += len(block)
            if h.hexdigest() != row['sha256'] or size != row['size_bytes']:
                raise ValueError('Archive content failed checksum verification')
        if seen != set(expected) | {'snapshot-metadata.json'}:
            raise ValueError('Archive is missing files')


def package(root, plan, output, password):
    if not password or b'\n' in password or b'\r' in password:
        raise ValueError('Password must be nonempty and contain no newline')
    bundles = plan['bundles']
    if isinstance(bundles, list):
        bundles = {bundle['id']: bundle for bundle in bundles}
    if set(bundles) != {'tables', 'notebooks', 'imaging'}:
        raise ValueError('Expected exactly tables, notebooks, and imaging bundles')
    packaged = datetime.now(timezone.utc).isoformat(timespec='seconds')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    public = {'schema_version': 1, 'packaged_at': packaged, 'bundles': []}
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'snapshot.json').exists():
        raise FileExistsError('Existing snapshot.json; choose a new output directory')
    with tempfile.TemporaryDirectory(prefix='checkpoint-', dir=output) as temporary:
        staging = Path(temporary)
        for bundle_id, bundle in bundles.items():
            names = sorted(set(bundle['files']))
            if not names:
                raise ValueError(f'Empty bundle: {bundle_id}')
            if 'snapshot-metadata.json' in names:
                raise ValueError('Reserved archive path')
            inventory = []
            for name in names:
                path = local_file(root, name)
                inventory.append({'path': name, 'size_bytes': path.stat().st_size,
                                  'sha256': digest(path)})
            metadata = {'schema_version': 1, 'id': bundle_id,
                        'packaged_at': packaged, 'source': bundle,
                        'inventory': inventory}
            plain = staging / f'{bundle_id}.tar.gz'
            with tarfile.open(plain, 'w:gz') as archive:
                for name in names:
                    archive.add(local_file(root, name), arcname=name, recursive=False)
                data = json.dumps(metadata, indent=2).encode()
                info = tarfile.TarInfo('snapshot-metadata.json')
                info.size = len(data)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(data))
            filename = f'cloneid-{bundle_id}-{stamp}.tar.gz.gpg'
            encrypted = staging / filename
            crypt(plain, encrypted, password)
            restored = staging / f'{bundle_id}-verified.tar.gz'
            crypt(encrypted, restored, password, decrypt=True)
            if digest(plain) != digest(restored):
                raise ValueError('Encrypted roundtrip did not preserve archive')
            verify_archive(restored, inventory)
            public['bundles'].append({
                'id': bundle_id, 'filename': filename,
                'description': bundle.get('description', bundle_id),
                'source_last_updated': bundle.get('source_last_updated'),
                'source_date_basis': bundle.get('source_date_basis', 'Latest raw source file modification time'),
                'size_bytes': encrypted.stat().st_size, 'sha256': digest(encrypted)})
        manifest = staging / 'snapshot.json'
        manifest.write_text(json.dumps(public, indent=2) + '\n')
        # Exclusive creation avoids overwriting previously packaged assets.
        for source in [staging / row['filename'] for row in public['bundles']] + [manifest]:
            with source.open('rb') as src, (output / source.name).open('xb') as dst:
                for block in iter(lambda: src.read(1024 * 1024), b''):
                    dst.write(block)
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'tmp/checkpoint/source-plan.json')
    parser.add_argument('--imaging-dir', type=Path, default=ROOT / 'tmp/checkpoint/imaging')
    parser.add_argument('--output', type=Path, default=ROOT / 'tmp/checkpoint/encrypted')
    parser.add_argument('--password-file', type=Path, help='Optional ignored local file; never commit it')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if isinstance(plan['bundles'], list):
        plan['bundles'] = {b['id']: b for b in plan['bundles']}
    if 'imaging' not in plan['bundles']:
        imaging = args.imaging_dir.resolve()
        if not imaging.is_relative_to(ROOT) or not imaging.is_dir():
            parser.error('Imaging directory must exist inside repository')
        files = [str(p.relative_to(ROOT)) for p in sorted(imaging.rglob('*')) if p.is_file()]
        plan['bundles']['imaging'] = {
            'description': 'Recursive CellSegmentations imaging, segmentation, and per-cell feature inventory',
            'files': files, 'source_last_updated': None,
            'source_date_basis': 'See encrypted manifest for source modification dates'}
        summary_path = imaging / 'summary.json'
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            if not summary.get('complete_scan', False):
                parser.error('Imaging manifest scan is incomplete')
            plan['bundles']['imaging']['source_last_updated'] = summary.get('source_last_updated')
            plan['bundles']['imaging']['source_date_basis'] = 'Latest CellSegmentations file modification time'
    output_path = args.output.resolve()
    ignored = subprocess.run(['git', 'check-ignore', '-q', str(output_path / 'snapshot.json')], cwd=ROOT)
    if not output_path.is_relative_to(ROOT) or ignored.returncode:
        parser.error('Output directory must be Git-ignored and inside repository (use tmp/)')
    if args.password_file:
        password_path = args.password_file.resolve()
        ignored = subprocess.run(['git', 'check-ignore', '-q', str(password_path)], cwd=ROOT)
        if ignored.returncode:
            parser.error('--password-file must be a Git-ignored local file')
        password = password_path.read_bytes().rstrip(b'\r\n')
    else:
        first = getpass.getpass('Shared snapshot password: ')
        second = getpass.getpass('Confirm password: ')
        if first != second:
            parser.error('Passwords differ')
        password = first.encode('utf-8')
    result = package(ROOT, plan, args.output, password)
    print(f"Packaged and verified {len(result['bundles'])} encrypted bundles in {args.output}")


if __name__ == '__main__':
    main()
