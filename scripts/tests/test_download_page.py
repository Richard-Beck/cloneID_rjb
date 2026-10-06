"""Public page rejects corrupted assets and escapes metadata."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('download_page', Path(__file__).resolve().parents[1] / 'build_download_page.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DownloadPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        bundles = []
        for label in ('tables', 'notebooks', 'imaging'):
            name = label + '.tar.gz.gpg'
            payload = ('encrypted-placeholder-' + label).encode()
            (self.assets / name).write_bytes(payload)
            bundles.append(dict(id=label, filename=name, description='<script>private</script>',
                                source_last_updated='2026-07-30', size_bytes=len(payload),
                                sha256=hashlib.sha256(payload).hexdigest()))
        self.snapshot = dict(schema_version=1, packaged_at='2026-10-06', bundles=bundles)
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.assets / 'snapshot.json').write_text(json.dumps(self.snapshot))

    def test_escapes_metadata_and_copies_exact_assets(self):
        out = self.root / 'site'
        module.build(self.assets, out)
        text = (out / 'index.html').read_text()
        self.assertIn('&lt;script&gt;', text)
        self.assertNotIn('<script>private</script>', text)
        self.assertEqual((out / 'tables.tar.gz.gpg').read_bytes(), (self.assets / 'tables.tar.gz.gpg').read_bytes())

    def test_rejects_tampered_asset(self):
        (self.assets / 'tables.tar.gz.gpg').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum/size'):
            module.build(self.assets, self.root / 'site')

    def test_rejects_path_traversal(self):
        self.snapshot['bundles'][0]['filename'] = '../tables.tar.gz.gpg'
        self.save()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            module.build(self.assets, self.root / 'site')


if __name__ == '__main__':
    unittest.main()
