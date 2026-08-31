"""Small local preferences that survive code updates."""
import json
import os
from pathlib import Path

MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 1440


def validate_interval(value):
    if isinstance(value, bool):
        raise ValueError('O intervalo deve ser um número inteiro de minutos.')
    try:
        minutes = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError('Informe um número inteiro de minutos.') from error
    if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
        raise ValueError(f'O intervalo deve ficar entre {MIN_INTERVAL_MINUTES} e {MAX_INTERVAL_MINUTES} minutos.')
    return minutes


def settings_path(root: Path):
    return root / 'runtime' / 'operator_settings.json'


def _read_settings(root: Path):
    path = settings_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _save_settings(root: Path, updates):
    data = _read_settings(root)
    data.update(updates)
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def load_interval(root: Path, default):
    fallback = validate_interval(default)
    try:
        data = _read_settings(root)
        return validate_interval(data['patrol_interval_minutes'])
    except (KeyError, TypeError, ValueError):
        return fallback


def save_interval(root: Path, value):
    minutes = validate_interval(value)
    _save_settings(root, {'patrol_interval_minutes': minutes})
    return minutes


def validate_channels(selected, allowed):
    allowed_channels = tuple(str(item) for item in allowed)
    if not allowed_channels:
        raise ValueError('Nenhuma loja foi configurada no sistema.')
    selected_set = {str(item) for item in selected}
    unknown = selected_set.difference(allowed_channels)
    if unknown:
        raise ValueError('Loja não autorizada: ' + ', '.join(sorted(unknown)))
    result = tuple(item for item in allowed_channels if item in selected_set)
    if not result:
        raise ValueError('Selecione pelo menos uma loja para a ronda.')
    return result


def load_channels(root: Path, allowed):
    allowed_channels = tuple(allowed)
    try:
        return validate_channels(_read_settings(root)['label_channels'], allowed_channels)
    except (KeyError, TypeError, ValueError):
        return allowed_channels


def save_channels(root: Path, selected, allowed):
    channels = validate_channels(selected, allowed)
    _save_settings(root, {'label_channels': list(channels)})
    return channels
