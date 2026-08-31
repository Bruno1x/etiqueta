import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from faturamento_bot.runner import WorkflowRunner


class SingleStoreSelectionTests(unittest.TestCase):
    def make_runner(self):
        runner = WorkflowRunner.__new__(WorkflowRunner)
        runner.mode = SimpleNamespace(live=True)
        runner.config = SimpleNamespace(
            target_window={},
            processing={'label_channels': ('ML CENTRAL', 'ML DISTRIBUIDOR')},
        )
        runner.log = Mock()
        runner.reference_matcher = Mock()
        runner.reference_matcher.detect_visible_screen.return_value = SimpleNamespace(
            screen_id='ecommerce_manager'
        )
        runner.validate_environment = Mock()
        runner._check_cancelled = Mock()
        runner._clear_company_checkbox = Mock()
        runner._prepare_label_dates = Mock()
        runner._wait_ecommerce_stable = Mock()
        runner._set_checklist_value = Mock()
        runner._click_reference = Mock()
        return runner

    @patch('faturamento_bot.runner.time.sleep')
    @patch('faturamento_bot.runner.activate_and_maximize')
    @patch('faturamento_bot.runner.find_unique_window')
    def test_clears_every_store_before_selecting_first(self, window, activate, sleep):
        runner = self.make_runner()
        runner.test_ecommerce_channel_cycle()
        states = [(call.args[4], call.kwargs['selected'])
                  for call in runner._set_checklist_value.call_args_list]
        self.assertEqual(states, [
            ('ML CENTRAL', False), ('ML DISTRIBUIDOR', False),
            ('ML CENTRAL', True), ('ML CENTRAL', False),
            ('ML DISTRIBUIDOR', True), ('ML DISTRIBUIDOR', False),
        ])
        selecting = [call for call in runner._set_checklist_value.call_args_list
                     if call.kwargs['selected']]
        self.assertTrue(all(call.kwargs['force_click'] for call in selecting))

    @patch('faturamento_bot.runner.time.sleep')
    @patch('faturamento_bot.runner.activate_and_maximize')
    @patch('faturamento_bot.runner.find_unique_window')
    def test_error_still_deselects_current_store(self, window, activate, sleep):
        runner = self.make_runner()
        with self.assertRaisesRegex(RuntimeError, 'falha controlada'):
            runner.test_ecommerce_channel_cycle(
                after_search=Mock(side_effect=RuntimeError('falha controlada'))
            )
        states = [(call.args[4], call.kwargs['selected'])
                  for call in runner._set_checklist_value.call_args_list]
        self.assertEqual(states[-2:], [('ML CENTRAL', True), ('ML CENTRAL', False)])


if __name__ == '__main__':
    unittest.main()
