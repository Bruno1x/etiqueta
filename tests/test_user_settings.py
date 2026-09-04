from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from faturamento_bot.user_settings import (
    load_printer,
    load_channels,
    load_interval,
    save_channels,
    save_interval,
    save_printer,
    validate_channels,
    validate_interval,
)


class UserSettingsTests(unittest.TestCase):
    def test_validate_interval_boundaries(self):
        self.assertEqual(validate_interval('1'), 1)
        self.assertEqual(validate_interval(1440), 1440)
        for value in (0, 1441, True, '1.5', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_interval(value)

    def test_printer_selection_is_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(load_printer(root, 'Zebra A'), 'Zebra A')
            save_printer(root, 'Zebra B')
            self.assertEqual(load_printer(root, 'Zebra A'), 'Zebra B')

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

    def test_channels_default_to_all_allowed(self):
        with TemporaryDirectory() as directory:
            allowed = ('ML CENTRAL', 'ML STORE', 'ML UNIVERSO')
            self.assertEqual(load_channels(Path(directory), allowed), allowed)

    def test_store_selection_and_interval_are_preserved_together(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = ('ML CENTRAL', 'ML STORE', 'ML UNIVERSO')
            save_interval(root, 12)
            save_channels(root, ('ML CENTRAL',), allowed)
            self.assertEqual(load_interval(root, 1), 12)
            self.assertEqual(load_channels(root, allowed), ('ML CENTRAL',))
            save_interval(root, 25)
            self.assertEqual(load_channels(root, allowed), ('ML CENTRAL',))

    def test_channels_reject_empty_or_unknown_selection(self):
        allowed = ('ML CENTRAL', 'ML STORE')
        with self.assertRaises(ValueError):
            validate_channels((), allowed)
        with self.assertRaises(ValueError):
            validate_channels(('ML CENTRAL', 'NUVEM ATACADO'), allowed)
