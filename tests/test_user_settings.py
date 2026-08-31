from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from faturamento_bot.user_settings import load_interval, save_interval, validate_interval


class UserSettingsTests(unittest.TestCase):
    def test_validate_interval_boundaries(self):
        self.assertEqual(validate_interval('1'), 1)
        self.assertEqual(validate_interval(1440), 1440)
        for value in (0, 1441, True, '1.5', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_interval(value)

    def test_saved_value_survives_reload(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(load_interval(root, 15), 15)
            save_interval(root, 37)
            self.assertEqual(load_interval(root, 15), 37)

    def test_invalid_file_falls_back_safely(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'runtime/operator_settings.json'
            path.parent.mkdir(parents=True)
            path.write_text('{broken')
            self.assertEqual(load_interval(root, 15), 15)
