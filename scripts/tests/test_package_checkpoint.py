"""Real GPG roundtrips on synthetic data; no research data or durable password."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('package_checkpoint', Path(__file__).parents[1] / 'package_checkpoint.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PackagingTest(unittest.TestCase):
    def test_all_bundles_roundtrip_and_public_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundles = {}
            for bundle in ('tables', 'notebooks', 'imaging'):
                source = root / f'private-{bundle}.txt'
                source.write_text(f'Private synthetic data for {bundle}\n')
                bundles[bundle] = {'files': [source.name], 'description': bundle,
                                   'source_last_updated': '2026-01-01T00:00:00+00:00'}
            output = root / 'encrypted'
            manifest = module.package(root, {'bundles': bundles}, output, b'synthetic-test-only')
            self.assertEqual(len(manifest['bundles']), 3)
            self.assertNotIn('private-', json.dumps(manifest))
            for bundle in manifest['bundles']:
                encrypted = output / bundle['filename']
                self.assertEqual(module.digest(encrypted), bundle['sha256'])
                self.assertGreater(encrypted.stat().st_size, 0)
            with self.assertRaises(FileExistsError):
                module.package(root, {'bundles': bundles}, output, b'synthetic-test-only')

    def test_external_paths_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('/etc/passwd', '../outside'):
                with self.assertRaises(ValueError):
                    module.local_file(root, name)
            (root / 'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                module.local_file(root, 'link')


if __name__ == '__main__':
    unittest.main()
