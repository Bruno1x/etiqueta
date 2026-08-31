import unittest

from faturamento_bot.print_grid import PrintGridReader


class AdaptiveGridTests(unittest.TestCase):
    def test_builds_layout_from_calibrated_geometry(self):
        layout = PrintGridReader.layout_from_points((10, 400), (1144, 400), (10, 420))
        self.assertEqual((layout.left, layout.top, layout.scale), (10, 400, 1.0))

    def test_accepts_uniform_scaled_geometry(self):
        layout = PrintGridReader.layout_from_points((5, 200), (572, 200), (5, 210))
        self.assertEqual((layout.left, layout.top), (5, 200))
        self.assertAlmostEqual(layout.scale, .5, places=6)

    def test_rejects_deformed_or_inverted_geometry(self):
        cases = (((0, 0), (1134, 0), (0, 35)),
                 ((0, 0), (1134, 100), (0, 20)),
                 ((0, 0), (1134, 0), (0, -20)))
        for points in cases:
            with self.subTest(points=points):
                with self.assertRaises(RuntimeError):
                    PrintGridReader.layout_from_points(*points)


if __name__ == '__main__':
    unittest.main()
