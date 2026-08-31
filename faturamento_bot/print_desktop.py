"""Windows adapter for the recording's direct Etiqueta + Documentos flow."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time
import re
import unicodedata
from contextlib import contextmanager

from PIL import ImageGrab
import pyautogui

from .print_grid import PrintGridReader
from .print_once import NoEligibleOrder, OrderIdentity, PrintJournal, print_one
from .printing import installed_printer_names
from .windows import (activate_and_maximize, find_unique_window,
                      foreground_root_handle, foreground_window_info, virtual_screen_metrics)


COMPACT_COLUMNS = {'channel': 180, 'invoice': 308, 'status': 391}
EXPANDED_COLUMNS = {'channel': 428, 'invoice': 560, 'status': 644}


def is_print_workspace(window, class_name, process_regex):
    if class_name == '#32770' or not re.search(process_regex, window.process_path):
        return False
    title = ''.join(char for char in unicodedata.normalize('NFKD', window.title)
                    if not unicodedata.combining(char)).casefold().strip()
    return bool(re.match(r'^(?:\[0682\]\s*)?gerenciador de impressoes d[eo] e-commerce\s*$', title)
                or re.match(r'^erp\s+sysemp\b', title))


class WindowsClipboard:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.GetClipboardSequenceNumber.restype = wintypes.DWORD
        self.user.GetClipboardData.argtypes = [wintypes.UINT]
        self.user.GetClipboardData.restype = wintypes.HANDLE
        self.user.OpenClipboard.argtypes = [wintypes.HWND]
        self.user.OpenClipboard.restype = wintypes.BOOL
        self.kernel.GlobalLock.argtypes = [wintypes.HANDLE]
        self.kernel.GlobalLock.restype = ctypes.c_void_p
        self.kernel.GlobalUnlock.argtypes = [wintypes.HANDLE]
        self.kernel.GlobalSize.argtypes = [wintypes.HANDLE]
        self.kernel.GlobalSize.restype = ctypes.c_size_t

    def sequence(self):
        return self.user.GetClipboardSequenceNumber()

    def text(self):
        if not self.user.OpenClipboard(None):
            return None
        try:
            handle = self.user.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                return None
            size = self.kernel.GlobalSize(handle)
            if not 0 < size <= 65536:
                return None
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.string_at(pointer, size).decode('utf-16-le').split('\0', 1)[0].strip()
            finally:
                self.kernel.GlobalUnlock(handle)
        finally:
            self.user.CloseClipboard()


class DirectPrintDesktop:
    def __init__(self, runner, routing_confirmed):
        self.runner = runner
        self.config = runner.config
        self.routing_confirmed = routing_confirmed
        self.reader = PrintGridReader(self.config.root / 'assets/print_ui')
        self.clipboard = WindowsClipboard()
        self.layout = None
        self.expanded_grid = False
        self.window = None

    def guard(self):
        self.runner._check_input()
        if self.window is not None and foreground_root_handle() != self.window.handle:
            active, class_name = foreground_window_info()
            raise RuntimeError(f'Outra janela ou diálogo está ativo: {active.title!r} ({class_name}). Esperada: {self.window.title!r}. Nenhum diálogo será confirmado.')
        if any(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12)):
            raise RuntimeError('Solte Shift, Ctrl e Alt antes do teste. Nenhuma seleção múltipla será usada.')

    def preflight(self):
        if not self.routing_confirmed or not self.config.safety['allow_live']:
            raise RuntimeError('Impressão real não autorizada.')
        self.printer_check()
        window = find_unique_window(**{key: self.config.target_window.get(key)
                                      for key in ('title_regex', 'process_path_regex')})
        activate_and_maximize(window)
        time.sleep(.8)
        # The manager can be an owned top-level form omitted by main-window enumeration.
        # Bind once to the actual foreground workspace after activating the ERP.
        self.runner._check_input()
        active, class_name = foreground_window_info()
        if not is_print_workspace(active, class_name, self.config.target_window['process_path_regex']):
            raise RuntimeError(f'Janela ativa não validada: {active.title!r}, classe {class_name!r}. Abra o gerenciador e feche diálogos.')
        self.window = active
        self.runner.log.info('Janela de impressão validada: %s; classe %s; handle %s', active.title, class_name, active.handle)
        self.guard()
        self.layout = self.resolve_layout(ImageGrab.grab(all_screens=True))
        self.check_target(self.layout.point(0, 0))
        self.check_target(self.layout.point(1134, 20))

    def check_target(self, point):
        virtual = virtual_screen_metrics()
        x, y = point[0] + virtual.left, point[1] + virtual.top
        window = self.window
        if not (window.left <= x < window.left + window.width and
                window.top <= y < window.top + window.height):
            raise RuntimeError('O ponto reconhecido está fora da janela do SYSEMP. Nenhum clique será enviado.')

    def printer_check(self):
        required = self.config.raw['printing']['printer_name_contains']
        # Direct SYSEMP routing was explicitly confirmed by the operator.
        # Existence of this queue alone does NOT prove SYSEMP routing or paper output.
        if required.casefold() not in {name.casefold() for name in installed_printer_names()}:
            raise RuntimeError(f'A fila exata {required!r} não está instalada. Impressão bloqueada.')

    def snapshot(self):
        self.guard()
        image = ImageGrab.grab(all_screens=True)
        layout = self.resolve_layout(image)
        self.validate_layout(layout)
        return image, self.reader.rows(image, layout, expanded=self.expanded_grid)

    def validate_layout(self, layout):
        if self.layout is None:
            raise RuntimeError('A grade ainda não foi validada.')
        if (abs(layout.left - self.layout.left) > 4 or abs(layout.top - self.layout.top) > 4
                or abs(layout.scale - self.layout.scale) > .03):
            raise RuntimeError('A grade mudou de posição/escala durante o teste. Recomece sem imprimir.')

    def resolve_layout(self, image):
        try:
            layout = self.reader.layout(image)
            self.expanded_grid = False
            self.runner.log.debug('Grade reconhecida pelo cabeçalho visual.')
            return layout
        except RuntimeError as visual_error:
            try:
                layout = self.calibrated_layout()
            except Exception as calibration_error:
                raise RuntimeError(
                    'Grade não reconhecida pelo tema nem pela geometria calibrada. '
                    'Mantenha Lib Etiqueta na primeira coluna e execute Auto calibrar. '
                    f'Detalhes: {visual_error}; {calibration_error}'
                ) from calibration_error
            self.runner.log.info('Cabeçalho de outro tema: grade localizada pela geometria calibrada do SYSEMP.')
            self.expanded_grid = True
            return layout

    def column_x(self, name):
        columns = EXPANDED_COLUMNS if self.expanded_grid else COMPACT_COLUMNS
        return columns[name]

    def calibrated_layout(self):
        """Map the known grid geometry through the recognized manager screen."""
        import cv2
        import numpy as np

        matcher = self.runner.reference_matcher
        matched = matcher.match('ecommerce_manager')
        if matched is None:
            raise RuntimeError('Tela do gerenciador não corresponde aos temas calibrados.')
        variant = next((item for item in matcher.manifest['screens'].values()
                        if item.get('canonical_screen') == 'ecommerce_manager'
                        and 'canonical_transform' in item), None)
        if variant is None:
            raise RuntimeError('Transformação canônica do gerenciador não configurada.')
        canonical_transform = np.asarray(variant['canonical_transform'], dtype=float).reshape(3, 3)
        inverse = np.linalg.inv(canonical_transform)
        light = np.float32([[[0, 384]], [[1134, 384]], [[0, 404]]])
        canonical = cv2.perspectiveTransform(light, inverse)
        mapped = cv2.perspectiveTransform(canonical, matched.homography).reshape(-1, 2)
        return self.reader.layout_from_points(mapped[0], mapped[1], mapped[2])

    def choose_candidate(self):
        _, rows = self.snapshot()
        eligible = [row for row in rows if row.green and row.printed is False]
        selected = [row for row in rows if row.selected]
        if len(selected) == 1 and selected[0] in eligible:
            return selected[0]
        if not eligible:
            raise NoEligibleOrder('Nenhum pedido verde e com Etiq Impressa desmarcada foi reconhecido na área visível. Nada foi enviado.')
        return eligible[0]

    def click(self, point):
        self.guard()
        # The title may be the ERP parent while the manager is an MDI child.
        # Require the actual grid, not a substring in the root window title.
        self.validate_layout(self.resolve_layout(ImageGrab.grab(all_screens=True)))
        self.check_target(point)
        virtual = virtual_screen_metrics()
        pyautogui.click(point[0] + virtual.left, point[1] + virtual.top)

    def read_cell(self, x, row):
        before = self.clipboard.sequence()
        self.click((self.layout.point(x, 0)[0], row.y))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.guard()
            if self.clipboard.sequence() != before:
                value = self.clipboard.text()
                if value:
                    return value
            time.sleep(.08)
        raise RuntimeError('A célula não foi copiada. No SYSEMP, deixe “Ao clicar na Linha da Grid, copiar o conteúdo da Célula” em Sim. Nada foi impresso.')

    def identity(self, row):
        channel = self.read_cell(self.column_x('channel'), row)
        invoice = self.read_cell(self.column_x('invoice'), row)
        status = self.read_cell(self.column_x('status'), row)
        if status != '100':
            raise RuntimeError(f'Status NFe diferente de 100 ({status!r}); impressão bloqueada.')
        # Nota Fiscal is unique inside one channel and is sufficient for the
        # durable duplicate guard. Reading the far-right marketplace column can
        # horizontally move some SYSEMP grids and invalidate their geometry.
        safe_order_key = invoice.replace('.', '').zfill(8)
        return OrderIdentity(channel, safe_order_key, invoice)

    def select_and_identify(self, row):
        return self.identity(row)

    def page_key(self, row, channel):
        actual = self.read_cell(self.column_x('channel'), row)
        if actual != channel:
            raise RuntimeError(f'Grade de {actual}, esperada {channel}. Ronda interrompida.')
        invoice = self.read_cell(self.column_x('invoice'), row)
        if not invoice.replace('.', '').isdigit():
            raise RuntimeError('Não foi possível identificar a posição da grade com segurança.')
        return (invoice,)

    def move_grid(self, key):
        self.guard()
        pyautogui.press(key)
        time.sleep(1.2)
        self.guard()

    def start_pages(self, channel):
        """Focus the grid and return to its first record.

        Do not probe past the bottom edge. Some SYSEMP grid themes lose their
        visual row state when Down is sent after Ctrl+End. Page traversal can
        identify completion safely when PageDown no longer changes the tail.
        """
        self.preflight()
        _, rows = self.snapshot()
        if not rows:
            return None
        self.read_cell(self.column_x('channel'), rows[0])  # Focus the grid before keyboard navigation.
        self.guard()
        pyautogui.hotkey('ctrl', 'home')
        time.sleep(1.2)
        _, rows = self.snapshot()
        if not rows:
            raise RuntimeError('A grade desapareceu ao retornar para a primeira página.')
        self.page_key(rows[0], channel)
        return True

    def seek_grid_edge(self, channel, *, bottom):
        """Check record identity at an edge, not the theme's selection color.

        Explicitly focus the edge row before arrow navigation. A shortcut that
        only moves the active cell is insufficient: continue while records move.
        """
        self.guard()
        pyautogui.hotkey('ctrl', 'end' if bottom else 'home')
        time.sleep(1.2)
        index = -1 if bottom else 0
        stable = 0
        for _ in range(2000):
            _, rows = self.snapshot()
            if not rows:
                raise RuntimeError('A grade desapareceu durante a verificação de seus limites.')
            before = self.page_key(rows[index], channel)
            self.move_grid('down' if bottom else 'up')
            _, rows = self.snapshot()
            if not rows:
                raise RuntimeError('A grade desapareceu após avançar uma linha.')
            after = self.page_key(rows[index], channel)
            stable = stable + 1 if before == after else 0
            if stable >= 2:
                self.runner.log.info('Limite %s da grade identificado pelo pedido, sem depender da cor de seleção.',
                                     'inferior' if bottom else 'superior')
                return after
        raise RuntimeError('Não foi possível identificar o limite da grade dentro do limite de navegação.')

    def next_page(self, channel, previous_tail):
        _, rows = self.snapshot()
        if not rows:
            raise RuntimeError('A grade desapareceu antes de avançar.')
        self.read_cell(self.column_x('channel'), rows[-1])
        self.move_grid('pagedown')
        _, rows = self.snapshot()
        if not rows:
            raise RuntimeError('A grade desapareceu após Page Down.')
        return self.page_key(rows[-1], channel) != previous_tail

    def verify_candidate(self, row, order):
        if self.identity(row) != order:
            raise RuntimeError('O pedido mudou durante a leitura; nada foi impresso.')
        _, rows = self.snapshot()
        selected = [item for item in rows if item.selected]
        if len(selected) != 1 or abs(selected[0].y - row.y) > 3*self.layout.scale or not selected[0].green or selected[0].printed is not False:
            raise RuntimeError('Não foi possível confirmar uma única linha verde e não impressa. Nada foi enviado.')

    def dispatch(self, row, order):
        self.printer_check()
        self.verify_candidate(row, order)
        image, _ = self.snapshot()
        point = self.reader.print_point(image)
        self.runner.log.warning('Envio real: Etiqueta + Documentos, nota %s, canal %s. Sem repetição automática.', order.invoice, order.channel)
        self.click(point)

    def wait_result(self, row, order):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.runner._check_cancelled()
            try:
                _, rows = self.snapshot()
            except RuntimeError:
                return False
            current = [item for item in rows if abs(item.y - row.y) <= 3*self.layout.scale and item.selected]
            if len(current) == 1 and current[0].printed is True and current[0].invoice_printed is True:
                # Confirm the same order, not a different row after a refresh.
                return self.identity(row) == order
            time.sleep(.5)
        return False


@contextmanager
def print_session():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Local\\SysempEtiquetasPrintOnce')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError('Já existe um teste de impressão em execução. Feche a outra instância.')
    try:
        local = os.environ.get('LOCALAPPDATA')
        if not local:
            raise RuntimeError('LOCALAPPDATA não disponível para proteger contra duplicações.')
        journal = PrintJournal(Path(local) / 'EtiquetasBot' / 'print_history.sqlite3')
        yield journal
    finally:
        kernel.CloseHandle(handle)


def run_direct_print_test(runner, routing_confirmed, expected_channel=None):
    with print_session() as journal:
        return print_one(DirectPrintDesktop(runner, routing_confirmed), journal,
                         runner.config.processing['label_channels'], expected_channel=expected_channel)


def _scan_store_once(backend, journal, channel, allowed_channels):
    """Drain every page once and return how many orders were confirmed."""
    if backend.start_pages(channel) is None:
        return 0
    count = 0
    seen_pages = set()
    for _ in range(2000):
        _, rows = backend.snapshot()
        if not rows:
            raise RuntimeError('Grade deixou de ser reconhecida durante a ronda.')
        tail = backend.page_key(rows[-1], channel)
        if tail in seen_pages:
            raise RuntimeError('A navegação repetiu uma página; ronda interrompida.')
        seen_pages.add(tail)
        for _ in range(10000):
            _, current = backend.snapshot()
            candidate = None
            for row in current:
                if row.green and row.printed is False:
                    order = backend.select_and_identify(row)
                    if order.channel != channel:
                        raise RuntimeError('Pedido de outra loja na grade; ronda interrompida.')
                    if not journal.attempted(order):
                        candidate = row
                        break
            if candidate is None:
                break
            print_one(backend, journal, allowed_channels, expected_channel=channel,
                      row=candidate, require_confirmation=True)
            count += 1
            backend.runner.log.info('%s: %d pedido(s) confirmado(s) pelo SYSEMP nesta passagem.', channel, count)
        else:
            raise RuntimeError('Limite de segurança de pedidos atingido; confira a grade.')
        _, current = backend.snapshot()
        if not current:
            raise RuntimeError('Grade desapareceu após a impressão.')
        if backend.page_key(current[-1], channel) != tail:
            raise RuntimeError('A ordem da grade mudou durante a impressão; confira os resultados.')
        if not backend.next_page(channel, tail):
            return count
    raise RuntimeError('Limite de páginas atingido; ronda interrompida.')


def print_store(backend, journal, channel, allowed_channels):
    """Do not leave a store until a complete verification pass prints nothing."""
    total = 0
    empty_passes = 0
    for pass_number in range(1, 1001):
        printed = _scan_store_once(backend, journal, channel, allowed_channels)
        total += printed
        backend.runner.log.info('%s: verificação completa %d; %d impressão(ões) nesta passagem.',
                                channel, pass_number, printed)
        empty_passes = empty_passes + 1 if printed == 0 else 0
        if empty_passes:
            backend.runner.log.info('%s: passagem vazia %d/2 antes de liberar a troca.', channel, empty_passes)
        if empty_passes >= 2:
            backend.runner.log.info('%s: duas verificações sem etiquetas; liberada a troca de loja.', channel)
            return total
    raise RuntimeError('A loja continuou recebendo etiquetas por muitas verificações; ronda interrompida.')


def run_print_patrol(runner):
    if not runner.print_routing_confirmed:
        raise RuntimeError('Confirme o destino da impressão antes de iniciar a ronda.')
    with print_session() as journal:
        total = 0
        def after_search(channel):
            nonlocal total
            count = print_store(DirectPrintDesktop(runner, True), journal, channel,
                                runner.config.processing['label_channels'])
            total += count
            runner.log.info('Loja %s encerrada: %d pedido(s) confirmado(s).', channel, count)
            return None  # Deselect and continue all stores, unlike the single-order test.
        runner.test_ecommerce_channel_cycle(after_search=after_search)
        runner.log.info('Ronda concluída: %d pedido(s) confirmado(s) pelo SYSEMP.', total)
        return total


def run_print_test_flow(runner, routing_confirmed):
    """Use the same filter/search route as the navigation test, then send once."""
    def after_search(channel):
        try:
            return run_direct_print_test(runner, routing_confirmed, expected_channel=channel)
        except NoEligibleOrder:
            runner.log.info('%s: nenhum candidato visível; seguindo para a próxima loja.', channel)
            return None

    result = runner.test_ecommerce_channel_cycle(after_search=after_search)
    return result or ('Nenhum pedido elegível foi reconhecido nas áreas visíveis das oito lojas. '
                      'Nada foi impresso; linhas fora da área visível não foram verificadas.')
