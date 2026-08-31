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


def load_interval(root: Path, default):
    fallback = validate_interval(default)
    path = settings_path(root)
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return validate_interval(data['patrol_interval_minutes'])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return fallback


def save_interval(root: Path, value):
    minutes = validate_interval(value)
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'patrol_interval_minutes': minutes}, indent=2), encoding='utf-8')
    os.replace(temporary, path)
    return minutes
