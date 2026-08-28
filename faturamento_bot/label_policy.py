"""Regras de seleção; a leitura da grade deve ser validada separadamente."""

from datetime import date, timedelta
from typing import Mapping


def eligible_for_print(*, release_green: bool | None, printed: bool | None) -> bool:
    # Sem cache de rejeições: cada ronda deve fornecer uma observação nova.
    return release_green is True and printed is False


def delivery_window(settings: Mapping[str, object], today: date) -> tuple[date, date]:
    start = settings["start_offset_days"]
    end = settings["end_offset_days"]
    if type(start) is not int or type(end) is not int:
        raise ValueError("Os deslocamentos de entrega devem ser dias inteiros.")
    if start > end:
        raise ValueError("O início do período de entrega não pode superar o fim.")
    return today + timedelta(days=start), today + timedelta(days=end)
