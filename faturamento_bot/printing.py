from __future__ import annotations

from ctypes import (
    POINTER,
    Structure,
    WinDLL,
    WinError,
    byref,
    cast,
    create_string_buffer,
    get_last_error,
)
from ctypes import wintypes


PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004
ERROR_INSUFFICIENT_BUFFER = 122


class PRINTER_INFO_4W(Structure):
    _fields_ = [
        ("pPrinterName", wintypes.LPWSTR),
        ("pServerName", wintypes.LPWSTR),
        ("Attributes", wintypes.DWORD),
    ]


def installed_printer_names() -> tuple[str, ...]:
    winspool = WinDLL("winspool.drv", use_last_error=True)
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed = wintypes.DWORD()
    returned = wintypes.DWORD()
    winspool.EnumPrintersW(
        flags, None, 4, None, 0, byref(needed), byref(returned)
    )
    error = get_last_error()
    if needed.value == 0:
        if error not in (0, ERROR_INSUFFICIENT_BUFFER):
            raise WinError(error)
        return tuple()

    buffer = create_string_buffer(needed.value)
    if not winspool.EnumPrintersW(
        flags,
        None,
        4,
        buffer,
        needed.value,
        byref(needed),
        byref(returned),
    ):
        raise WinError()

    records = cast(buffer, POINTER(PRINTER_INFO_4W))
    names = {
        records[index].pPrinterName.strip()
        for index in range(returned.value)
        if records[index].pPrinterName and records[index].pPrinterName.strip()
    }
    return tuple(sorted(names, key=str.casefold))


def find_required_printer(
    names: tuple[str, ...], required_fragment: str
) -> str | None:
    fragment = required_fragment.strip().casefold()
    if not fragment:
        raise ValueError("O nome da impressora obrigatória não pode ficar vazio.")
    exact = [name for name in names if name.casefold() == fragment]
    if len(exact) == 1:
        return exact[0]
    matches = [name for name in names if fragment in name.casefold()]
    if not matches:
        return None
    if len(matches) > 1:
        joined = ", ".join(matches)
        raise RuntimeError(
            f"Mais de uma impressora corresponde a {required_fragment!r}: {joined}. "
            "Configure o nome exato antes da execução noturna."
        )
    return matches[0]


def required_printer() -> str | None:
    return find_required_printer(installed_printer_names(), "Zebra")
