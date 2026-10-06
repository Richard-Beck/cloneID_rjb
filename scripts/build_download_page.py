#!/usr/bin/env python3
"""Validate release assets and render the public static download page."""
import argparse
import hashlib
import html
import json
from pathlib import Path


def build(assets, output):
    snapshot = json.loads((assets / 'snapshot.json').read_text())
    if snapshot.get('schema_version') != 1:
        raise ValueError('Unsupported snapshot schema')
    bundles = snapshot['bundles']
    if {b['id'] for b in bundles} != {'tables', 'notebooks', 'imaging'} or len(bundles) != 3:
        raise ValueError('Expected exactly tables, notebooks, imaging')
    cards = []
    total = 0
    for bundle in bundles:
        name = bundle['filename']
        if Path(name).name != name or not name.endswith('.tar.gz.gpg'):
            raise ValueError('Unsafe or unexpected asset filename')
        path = assets / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing regular encrypted asset')
        size = path.stat().st_size
        hasher = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        if size != bundle['size_bytes'] or digest != bundle['sha256']:
            raise ValueError('Encrypted asset checksum/size mismatch')
        total += size
        esc = html.escape
        date_label = 'Latest observed file modification' if bundle['id'] == 'imaging' else 'Raw source file last updated'
        cards.append(f'''<article><h2>{esc(bundle['id'].title())}</h2>
<p>{esc(bundle['description'])}</p>
<p>{date_label}: <strong>{esc(str(bundle.get('source_last_updated') or 'Unknown'))}</strong></p>
<p class="muted">{esc(bundle.get('source_date_basis', 'Latest apparent raw-source file modification time; not independently verified.'))}</p>
<p><a class="download" href="{esc(name, quote=True)}">Download encrypted archive</a> ({size / 1048576:.1f} MiB)</p>
<details><summary>SHA-256 checksum</summary><code>{digest}</code></details></article>''')
    if total > 900 * 1024 * 1024:
        raise ValueError('Assets exceed the conservative 900 MiB Pages packaging limit; host release links instead')
    output.mkdir(parents=True, exist_ok=True)
    import shutil
    for bundle in bundles:
        shutil.copyfile(assets / bundle['filename'], output / bundle['filename'])
    shutil.copyfile(assets / 'snapshot.json', output / 'snapshot.json')
    template = Path(__file__).resolve().parents[1] / 'site' / 'index.template.html'
    rendered = template.read_text().replace('{{BUNDLES}}', '\n'.join(cards)).replace('{{PACKAGED_AT}}', html.escape(snapshot['packaged_at']))
    (output / 'index.html').write_text(rendered)
    (output / '.nojekyll').touch()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.assets, args.output)
