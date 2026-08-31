from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from faturamento_bot.print_desktop import print_store
from faturamento_bot.print_grid import GridRow
from faturamento_bot.print_once import OrderIdentity, PrintJournal


class FakeGrid:
    def __init__(self, pages):
        self.pages = pages
        self.page = 0
        self.sent = []
        self.confirm = True
        self.start_calls = 0
        self.runner = SimpleNamespace(log=Mock())

    def preflight(self):
        pass

    def start_pages(self, channel):
        self.start_calls += 1
        self.page = 0
        return (self.pages[-1][-1][0],) if self.pages else None

    def snapshot(self):
        return None, [GridRow(400 + i * 20, green, printed, printed, False)
                      for i, (_, green, printed) in enumerate(self.pages[self.page])]

    def record(self, row):
        return self.pages[self.page][(row.y - 400) // 20]

    def page_key(self, row, channel):
        return (self.record(row)[0],)

    def select_and_identify(self, row):
        index = self.record(row)[0]
        return OrderIdentity('ML CENTRAL', str(2000000000 + index), str(index))

    def verify_candidate(self, row, order):
        assert self.select_and_identify(row) == order

    def dispatch(self, row, order):
        self.sent.append(order)

    def wait_result(self, row, order):
        if self.confirm:
            i = (row.y - 400) // 20
            index, green, _ = self.pages[self.page][i]
            self.pages[self.page][i] = (index, green, True)
        return self.confirm

    def next_page(self, channel, tail):
        if self.page + 1 >= len(self.pages):
            return False
        self.page += 1
        return True


class BatchPrintTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.journal = PrintJournal(Path(temporary.name) / 'journal.sqlite3')

    def run_store(self, backend):
        return print_store(backend, self.journal, 'ML CENTRAL', ['ML CENTRAL'])

    def test_multiple_orders_across_pages(self):
        grid = FakeGrid([[(1, True, False), (2, False, False)], [(3, True, False), (4, True, True)]])
        self.assertEqual(self.run_store(grid), 2)
        self.assertEqual([o.invoice for o in grid.sent], ['1', '3'])
        self.assertEqual(grid.start_calls, 2)  # impressão + uma verificação completa sem pendências

    def test_next_round_rechecks_previously_red(self):
        grid = FakeGrid([[(1, False, False), (2, True, False)]])
        self.assertEqual(self.run_store(grid), 1)
        grid.pages[0][0] = (1, True, False)
        self.assertEqual(self.run_store(grid), 1)
        self.assertEqual([o.invoice for o in grid.sent], ['2', '1'])

    def test_journal_prevents_repeat_when_checkbox_reverts(self):
        grid = FakeGrid([[(1, True, False), (2, True, False)]])
        self.assertEqual(self.run_store(grid), 2)
        grid.pages[0][0] = (1, True, False)
        self.assertEqual(self.run_store(grid), 0)
        self.assertEqual(len(grid.sent), 2)

    def test_uncertain_first_order_stops_before_second(self):
        grid = FakeGrid([[(1, True, False), (2, True, False)]])
        grid.confirm = False
        with self.assertRaisesRegex(RuntimeError, 'sem confirmação'):
            self.run_store(grid)
        self.assertEqual(len(grid.sent), 1)
        self.assertTrue(self.journal.attempted(grid.sent[0]))

    def test_last_page_without_movement_completes_scan(self):
        grid = FakeGrid([[(1, True, False)]])
        self.assertEqual(self.run_store(grid), 1)
        self.assertEqual([order.invoice for order in grid.sent], ['1'])

    def test_empty_store_sends_nothing(self):
        grid = FakeGrid([])
        self.assertEqual(self.run_store(grid), 0)
        self.assertEqual(grid.sent, [])
