from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from faturamento_bot.print_desktop import DirectPrintDesktop


class IdentityColumnTests(unittest.TestCase):
    def make_backend(self):
        backend = object.__new__(DirectPrintDesktop)
        backend.expanded_grid = False
        backend.read_cell = Mock(side_effect=['ML CENTRAL', '4.037', '100'])
        return backend

    def test_identity_does_not_read_marketplace_order_column(self):
        backend = self.make_backend()
        identity = backend.identity(SimpleNamespace(y=500))
        self.assertEqual(identity.channel, 'ML CENTRAL')
        self.assertEqual(identity.invoice, '4.037')
        self.assertEqual(identity.marketplace_order, '00004037')
        self.assertEqual(backend.read_cell.call_count, 3)

    def test_page_key_uses_only_channel_and_invoice(self):
        backend = object.__new__(DirectPrintDesktop)
        backend.expanded_grid = False
        backend.read_cell = Mock(return_value='4.037')
        self.assertEqual(backend.page_key(SimpleNamespace(y=500), 'ML CENTRAL'), ('4.037',))
        self.assertEqual(backend.read_cell.call_count, 1)


if __name__ == '__main__':
    unittest.main()
