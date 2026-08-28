import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from types import SimpleNamespace

from faturamento_bot.updater import latest, validate_payload, version_tuple, prepare_update, activate_on_close
from update_bootstrap import preserve_local, resolve_version


class UpdaterTests(unittest.TestCase):
    def payload(self, extra=None):
        files = {'faturamento_bot/__init__.py': '__version__ = "0.5.1"',
                 'faturamento_bot/__main__.py': 'pass', 'requirements.txt': 'Pillow>=10.4\n',
                 'update-release.json': json.dumps({'format': 1, 'version': '0.5.1'})}
        files.update(extra or {})
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, value in files.items():
                info = zipfile.ZipInfo('placeholder')
                info.filename = name  # Preserve malformed Windows separators for rejection tests.
                archive.writestr(info, value)
        return stream.getvalue()

    def check(self, content, digest=None):
        return validate_payload(content, digest or hashlib.sha256(content).hexdigest(), 'Pillow>=10.4\n')

    def test_valid_package(self):
        files, manifest = self.check(self.payload())
        self.assertIn('faturamento_bot/__main__.py', files)
        self.assertEqual(manifest['version'], '0.5.1')

    def test_bad_checksum(self):
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            self.check(self.payload(), '0'*64)

    def test_paths_and_local_data_are_rejected(self):
        for name in ('../outside.py', 'faturamento_bot/../../bad.py', 'config/faturamento.toml',
                     'runtime/profiles/calibration.json', 'assets/screenshot.png', 'C:/bad.py',
                     'faturamento_bot\\bad.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(self.payload({name: 'pass'}))

    def test_dependency_change_requires_full_install(self):
        with self.assertRaisesRegex(ValueError, 'dependências'):
            self.check(self.payload({'requirements.txt': 'NewDependency'}))

    def test_invalid_python_rejected_before_activation(self):
        with self.assertRaises(SyntaxError):
            self.check(self.payload({'faturamento_bot/broken.py': 'def :'}))

    def test_version_comparison_and_invalid_tag(self):
        self.assertGreater(version_tuple('v0.5.1'), version_tuple('0.5.0-updater'))
        with self.assertRaises(ValueError):
            version_tuple('../../evil')

    @patch('faturamento_bot.updater.fetch')
    def test_latest_rejects_foreign_download(self, fetch):
        fetch.return_value = json.dumps({'tag_name': 'v0.5.1', 'assets': [
            {'name': 'etiquetas-update.zip', 'browser_download_url': 'https://other.test/payload'}]}).encode()
        with self.assertRaises(ValueError):
            latest('0.5.0')

    @patch('faturamento_bot.updater.fetch')
    def test_current_release_never_downgrades(self, fetch):
        fetch.return_value = b'{"tag_name":"v0.4.0", "assets":[]}'
        self.assertIsNone(latest('0.5.0'))

    def test_preserves_local_configuration_and_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'old', Path(directory)/'new'
            for name in ('config/faturamento.toml', 'runtime/profiles/local/calibration.json', 'assets/local.png'):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('local-data')
            preserve_local(source, target)
            self.assertEqual((target/'runtime/profiles/local/calibration.json').read_text(), 'local-data')
            self.assertEqual((target/'config/faturamento.toml').read_text(), 'local-data')

    def test_version_pointer_cannot_escape_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                resolve_version(Path(directory), '../outside')

    @patch.dict('os.environ', {}, clear=True)
    def test_direct_launch_cannot_stage_update(self):
        with self.assertRaisesRegex(RuntimeError, 'ABRIR'):
            prepare_update(None, {})

    @patch('faturamento_bot.updater.fetch')
    def test_staging_does_not_replace_running_code_or_activate_early(self, fetch):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'config').mkdir()
            (root/'assets').mkdir()
            (root/'config/faturamento.toml').write_text('printer="local"')
            (root/'requirements.txt').write_text('Pillow>=10.4\n')
            content = self.payload()
            fetch.side_effect = [hashlib.sha256(content).hexdigest().encode(), content]
            with patch.dict('os.environ', {'ETIQUETAS_INSTALL_ROOT': str(root)}):
                prepared = prepare_update(SimpleNamespace(root=root), {'tag':'v0.5.1', 'sha':'sha', 'zip':'zip'})
            target = root/prepared['target']
            self.assertTrue((target/'faturamento_bot/__main__.py').exists())
            self.assertEqual((root/'config/faturamento.toml').read_text(), 'printer="local"')
            self.assertFalse((root/'.update-pending.json').exists())
            activate_on_close(prepared)
            self.assertEqual(json.loads((root/'.update-pending.json').read_text())['target'], prepared['target'])
