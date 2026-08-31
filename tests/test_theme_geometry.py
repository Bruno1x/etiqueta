from pathlib import Path
import unittest
from unittest.mock import patch

from faturamento_bot.config import load_config
from faturamento_bot.reference import ReferenceScreenMatcher
from faturamento_bot.windows import VirtualScreenMetrics, WindowInfo


ROOT = Path(__file__).resolve().parents[1]


class ThemeGeometryTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReferenceScreenMatcher(load_config(ROOT / "config" / "faturamento.toml"))
        self.manager = WindowInfo(
            10, "[0682] Gerenciador de Impressões do e-commerce",
            0, 0, 1920, 1020, r"C:\sysemp\sysemp.exe",
        )

    @patch("faturamento_bot.reference.virtual_screen_metrics")
    @patch("faturamento_bot.reference.foreground_window_info")
    def test_manager_geometry_is_independent_of_skin(self, foreground, virtual):
        foreground.return_value = self.manager, "TForm"
        virtual.return_value = VirtualScreenMetrics(0, 0, 3840, 1080, 2)
        matched = self.matcher._manager_geometry_match()
        self.assertIsNotNone(matched)
        point = self.matcher.map_point(matched, 450, 211)
        self.assertEqual((point.x, point.y), (450, 211))

    @patch("faturamento_bot.reference.foreground_window_info")
    def test_home_or_dialog_cannot_be_accepted_as_manager(self, foreground):
        foreground.return_value = WindowInfo(
            11, "ERP SYSEMP Vs: 26", 0, 0, 1920, 1020,
            r"C:\sysemp\sysemp.exe",
        ), "TForm"
        self.assertIsNone(self.matcher._manager_geometry_match())


if __name__ == "__main__":
    unittest.main()
