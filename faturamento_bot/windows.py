from __future__ import annotations

from ctypes import POINTER, WINFUNCTYPE, WinError, byref, c_int, windll
from ctypes.wintypes import BOOL, DWORD, HANDLE, HWND, LPARAM, LPWSTR, RECT
from dataclasses import dataclass
import re


PROCESS_PER_MONITOR_DPI_AWARE = -4
SW_MAXIMIZE = 3
SW_SHOW = 5
WNDENUMPROC = WINFUNCTYPE(BOOL, HWND, LPARAM)

windll.kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
windll.kernel32.OpenProcess.restype = HANDLE
windll.kernel32.QueryFullProcessImageNameW.argtypes = [
    HANDLE,
    DWORD,
    LPWSTR,
    POINTER(DWORD),
]
windll.kernel32.QueryFullProcessImageNameW.restype = BOOL
windll.kernel32.CloseHandle.argtypes = [HANDLE]
windll.kernel32.CloseHandle.restype = BOOL
windll.user32.GetWindowThreadProcessId.argtypes = [HWND, POINTER(DWORD)]
windll.user32.GetWindowThreadProcessId.restype = DWORD
windll.user32.GetWindowTextLengthW.argtypes = [HWND]
windll.user32.GetWindowTextLengthW.restype = c_int
windll.user32.GetWindowTextW.argtypes = [HWND, LPWSTR, c_int]
windll.user32.GetWindowTextW.restype = c_int
windll.user32.IsWindowVisible.argtypes = [HWND]
windll.user32.IsWindowVisible.restype = BOOL
windll.user32.GetWindow.argtypes = [HWND, DWORD]
windll.user32.GetWindow.restype = HWND
windll.user32.GetWindowRect.argtypes = [HWND, POINTER(RECT)]
windll.user32.GetWindowRect.restype = BOOL
windll.user32.GetForegroundWindow.restype = HWND
windll.user32.GetAncestor.argtypes = [HWND, DWORD]
windll.user32.GetAncestor.restype = HWND
windll.user32.SetForegroundWindow.argtypes = [HWND]
windll.user32.SetForegroundWindow.restype = BOOL
windll.user32.ShowWindow.argtypes = [HWND, c_int]
windll.user32.ShowWindow.restype = BOOL
windll.user32.IsZoomed.argtypes = [HWND]
windll.user32.IsZoomed.restype = BOOL
windll.user32.EnumWindows.argtypes = [WNDENUMPROC, LPARAM]
windll.user32.EnumWindows.restype = BOOL


@dataclass(frozen=True)
class ScreenMetrics:
    width: int
    height: int
    dpi: int

    @property
    def scale_percent(self) -> int:
        return round(self.dpi / 96 * 100)


@dataclass(frozen=True)
class VirtualScreenMetrics:
    left: int
    top: int
    width: int
    height: int
    monitor_count: int


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    left: int
    top: int
    width: int
    height: int
    process_path: str


def enable_dpi_awareness() -> None:
    try:
        windll.user32.SetProcessDpiAwarenessContext(PROCESS_PER_MONITOR_DPI_AWARE)
    except AttributeError:
        windll.user32.SetProcessDPIAware()


def screen_metrics() -> ScreenMetrics:
    enable_dpi_awareness()
    # GetSystemMetrics pode devolver pixels lógicos quando o host iniciou o
    # processo como DPI-unaware. DESKTOPHORZRES/DESKTOPVERTRES sempre refletem
    # a resolução física do monitor, então também permitem calcular a escala.
    horizontal_resolution = 8
    vertical_resolution = 10
    desktop_horizontal_resolution = 118
    desktop_vertical_resolution = 117
    device_context = windll.gdi32.CreateDCW("DISPLAY", None, None, None)
    if not device_context:
        raise WinError()
    try:
        logical_width = windll.gdi32.GetDeviceCaps(
            device_context, horizontal_resolution
        )
        physical_width = windll.gdi32.GetDeviceCaps(
            device_context, desktop_horizontal_resolution
        )
        physical_height = windll.gdi32.GetDeviceCaps(
            device_context, desktop_vertical_resolution
        )
        logical_height = windll.gdi32.GetDeviceCaps(
            device_context, vertical_resolution
        )
    finally:
        windll.gdi32.DeleteDC(device_context)

    if not all((logical_width, logical_height, physical_width, physical_height)):
        raise RuntimeError("O Windows não retornou métricas válidas do monitor.")
    scale = physical_width / logical_width
    dpi = round(96 * scale)
    return ScreenMetrics(physical_width, physical_height, dpi)


def virtual_screen_metrics() -> VirtualScreenMetrics:
    enable_dpi_awareness()
    return VirtualScreenMetrics(
        left=windll.user32.GetSystemMetrics(76),
        top=windll.user32.GetSystemMetrics(77),
        width=windll.user32.GetSystemMetrics(78),
        height=windll.user32.GetSystemMetrics(79),
        monitor_count=windll.user32.GetSystemMetrics(80),
    )


def _window_process_path(handle: int) -> str:
    process_id = DWORD()
    windll.user32.GetWindowThreadProcessId(handle, byref(process_id))
    process = windll.kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process:
        return ""
    try:
        capacity = DWORD(32768)
        buffer = __import__("ctypes").create_unicode_buffer(capacity.value)
        if not windll.kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, byref(capacity)
        ):
            return ""
        return buffer.value
    finally:
        windll.kernel32.CloseHandle(process)


def _window_title(handle: int) -> str:
    length = windll.user32.GetWindowTextLengthW(handle)
    buffer = __import__("ctypes").create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(handle, buffer, length + 1)
    return buffer.value


def find_unique_window(
    title_regex: str | None = None,
    process_path_regex: str | None = None,
) -> WindowInfo:
    if not title_regex and not process_path_regex:
        raise ValueError("Informe title_regex ou process_path_regex.")
    title_pattern = re.compile(title_regex) if title_regex else None
    process_pattern = re.compile(process_path_regex) if process_path_regex else None
    matches: list[WindowInfo] = []
    @WNDENUMPROC
    def callback(handle: int, _parameter: int) -> bool:
        if not windll.user32.IsWindowVisible(handle):
            return True
        if windll.user32.GetWindow(handle, 4):  # GW_OWNER: ignora diálogos secundários.
            return True
        title = _window_title(handle)
        process_path = _window_process_path(handle)
        matches_title = bool(title_pattern and title_pattern.search(title))
        matches_process = bool(process_pattern and process_pattern.search(process_path))
        matches_target = matches_process if process_pattern else matches_title
        if not matches_target:
            return True
        rect = RECT()
        if not windll.user32.GetWindowRect(handle, byref(rect)):
            raise WinError()
        matches.append(
            WindowInfo(
                handle=handle,
                title=title,
                left=rect.left,
                top=rect.top,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                process_path=process_path,
            )
        )
        return True

    windll.user32.EnumWindows(callback, 0)
    if len(matches) > 1:
        matches.sort(key=lambda item: item.width * item.height, reverse=True)
        largest_area = matches[0].width * matches[0].height
        second_area = matches[1].width * matches[1].height
        if largest_area >= second_area * 1.5:
            return matches[0]
    if len(matches) != 1:
        titles = ", ".join(repr(item.title) for item in matches) or "nenhuma"
        raise RuntimeError(
            "Esperava exatamente uma janela principal do SYSEMP; "
            f"encontradas: {titles}."
        )
    return matches[0]


def activate_and_maximize(window: WindowInfo) -> None:
    # Reenviar SW_MAXIMIZE para uma janela já maximizada pode deixar o Shell
    # sem redesenhar a barra de tarefas em alguns desktops com múltiplos DPI.
    if not windll.user32.IsZoomed(window.handle):
        windll.user32.ShowWindow(window.handle, SW_MAXIMIZE)
    if not windll.user32.SetForegroundWindow(window.handle):
        raise RuntimeError(f"Não foi possível ativar a janela {window.title!r}.")


def restore_taskbars() -> None:
    """Torna visíveis e redesenha as barras do Explorer sem roubar o foco."""
    redraw_flags = 0x0001 | 0x0080 | 0x0100  # INVALIDATE | ALLCHILDREN | UPDATENOW

    @WNDENUMPROC
    def callback(handle: int, _parameter: int) -> bool:
        class_buffer = __import__("ctypes").create_unicode_buffer(256)
        windll.user32.GetClassNameW(handle, class_buffer, len(class_buffer))
        if class_buffer.value in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
            windll.user32.ShowWindow(handle, SW_SHOW)
            windll.user32.RedrawWindow(handle, None, 0, redraw_flags)
        return True

    windll.user32.EnumWindows(callback, 0)


def foreground_title() -> str:
    handle = windll.user32.GetForegroundWindow()
    return _window_title(handle)


def foreground_root_handle() -> int:
    """MDI children share the root; owned modal dialogs have their own root."""
    handle = windll.user32.GetForegroundWindow()
    return int(windll.user32.GetAncestor(handle, 2) or handle or 0)


def foreground_window_info() -> tuple[WindowInfo, str]:
    handle = foreground_root_handle()
    rect = RECT()
    if not handle or not windll.user32.GetWindowRect(handle, byref(rect)):
        raise RuntimeError('Não foi possível identificar a janela ativa.')
    class_buffer = __import__('ctypes').create_unicode_buffer(256)
    windll.user32.GetClassNameW.argtypes = [HWND, LPWSTR, c_int]
    windll.user32.GetClassNameW(handle, class_buffer, len(class_buffer))
    return WindowInfo(handle, _window_title(handle), rect.left, rect.top,
                      rect.right - rect.left, rect.bottom - rect.top,
                      _window_process_path(handle)), class_buffer.value


def foreground_matches(
    title_regex: str | None,
    process_path_regex: str | None,
) -> bool:
    handle = windll.user32.GetForegroundWindow()
    title_matches = bool(title_regex and re.search(title_regex, _window_title(handle)))
    process_matches = bool(
        process_path_regex
        and re.search(process_path_regex, _window_process_path(handle))
    )
    return process_matches if process_path_regex else title_matches
