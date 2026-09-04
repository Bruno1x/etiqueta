import unittest
from datetime import datetime

from faturamento_bot.cutoff_schedule import due_channels, validate_cutoff_settings


class CutoffScheduleTests(unittest.TestCase):
    def settings(self):
        return validate_cutoff_settings({
            'enabled': True,
            'advance_minutes': 30,
            'weekdays': [0, 1, 2, 3, 4, 5],
            'stores': {
                'ML CENTRAL': {'enabled': True, 'first': '14:30', 'second': ''},
                'ML STORE': {'enabled': True, 'first': '10:45', 'second': '14:00'},
            },
        }, ('ML CENTRAL', 'ML STORE'))

    def test_store_becomes_due_thirty_minutes_before_cutoff(self):
        due = due_channels(self.settings(), datetime(2026, 9, 4, 14, 0), set())
        self.assertEqual([channel for channel, _ in due], ['ML CENTRAL', 'ML STORE'])

    def test_occurrence_runs_only_once(self):
        now = datetime(2026, 9, 4, 14, 5)
        first = due_channels(self.settings(), now, set())
        completed = {key for _, key in first}
        self.assertEqual(due_channels(self.settings(), now, completed), [])

    def test_does_not_start_after_cutoff(self):
        due = due_channels(self.settings(), datetime(2026, 9, 4, 14, 31), set())
        self.assertEqual(due, [])

    def test_disabled_day_does_not_run(self):
        due = due_channels(self.settings(), datetime(2026, 9, 6, 14, 0), set())
        self.assertEqual(due, [])

    def test_invalid_time_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_cutoff_settings({'stores': {
                'ML CENTRAL': {'enabled': True, 'first': '25:00'}
            }}, ('ML CENTRAL',))


if __name__ == '__main__':
    unittest.main()
