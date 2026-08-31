from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from faturamento_bot.runner import ECOMMERCE_CHANNEL_INDEX, RunMode, WorkflowRunner


class KeyboardChannelTests(unittest.TestCase):
    def make_runner(self):
        runner = WorkflowRunner.__new__(WorkflowRunner)
        runner.mode = RunMode(live=True, confirm_live=True)
        runner.log = Mock()
        runner.calibration = Mock()
        runner._check_cancelled = Mock()
        runner._check_input = Mock()
        return runner

    @patch('faturamento_bot.runner.time.sleep')
    @patch('pyautogui.press')
    @patch('pyautogui.click')
    def test_selects_central_from_first_item_and_verifies(self, click, press, sleep):
        runner = self.make_runner()
        runner._ecommerce_channel_is_in_field = Mock(side_effect=[False, True])
        field = SimpleNamespace(x=450, y=211)
        runner._set_ecommerce_channel_by_keyboard(
            field, 'channels/ml_central.png', 'ML CENTRAL', True
        )
        click.assert_called_once_with(450, 211)
        self.assertEqual(press.call_args_list, [
            call('home'),
            call('down', presses=ECOMMERCE_CHANNEL_INDEX['ML CENTRAL'], interval=.025),
            call('space'),
            call('escape'),
        ])

    @patch('faturamento_bot.runner.time.sleep')
    @patch('pyautogui.press')
    @patch('pyautogui.click')
    def test_already_clear_channel_does_not_open_list(self, click, press, sleep):
        runner = self.make_runner()
        runner._ecommerce_channel_is_in_field = Mock(return_value=False)
        runner._set_ecommerce_channel_by_keyboard(
            SimpleNamespace(x=450, y=211),
            'channels/ml_distribuidor.png', 'ML DISTRIBUIDOR', False
        )
        click.assert_not_called()
        press.assert_not_called()

    @patch('faturamento_bot.runner.time.sleep')
    @patch('pyautogui.press')
    @patch('pyautogui.click')
    def test_failed_validation_reverts_the_toggle(self, click, press, sleep):
        runner = self.make_runner()
        runner._ecommerce_channel_is_in_field = Mock(side_effect=[False, False])
        with self.assertRaisesRegex(RuntimeError, 'Não foi possível marcar'):
            runner._set_ecommerce_channel_by_keyboard(
                SimpleNamespace(x=450, y=211),
                'channels/ml_central.png', 'ML CENTRAL', True
            )
        self.assertEqual(click.call_count, 2)
        self.assertEqual(press.call_args_list.count(call('space')), 2)


if __name__ == '__main__':
    unittest.main()
