"""Validation and due-time calculation for per-store cutoff schedules."""
from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_CUTOFFS = {
    'ML SHOPPING': ('11:15', '14:15'),
    'ML STORE': ('10:45', '14:00'),
    'ML CENTRAL': ('14:30', ''),
    'ML UNIVERSO': ('14:45', ''),
    'ML HERO BAND': ('14:30', ''),
    'ML POOLSY': ('15:00', ''),
    'ML DISTRIBUIDOR': ('15:15', ''),
    'ML FABRICA': ('14:45', ''),
}


def normalize_time(value):
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.strptime(text, '%H:%M').strftime('%H:%M')
    except ValueError as error:
        raise ValueError(f'Horário inválido: {text}. Use HH:MM, por exemplo 14:30.') from error


def validate_cutoff_settings(value, allowed_channels):
    value = value or {}
    advance = int(value.get('advance_minutes', 30))
    if not 0 <= advance <= 240:
        raise ValueError('A antecedência deve ficar entre 0 e 240 minutos.')
    weekdays = sorted({int(day) for day in value.get('weekdays', range(6))})
    if any(day < 0 or day > 6 for day in weekdays):
        raise ValueError('Dias da semana inválidos.')
    stores = {}
    raw_stores = value.get('stores', {})
    for channel in allowed_channels:
        defaults = DEFAULT_CUTOFFS.get(channel, ('', ''))
        raw = raw_stores.get(channel, {}) if isinstance(raw_stores, dict) else {}
        first = normalize_time(raw.get('first', defaults[0]))
        second = normalize_time(raw.get('second', defaults[1]))
        stores[channel] = {
            'enabled': bool(raw.get('enabled', bool(first or second))),
            'first': first,
            'second': second,
        }
    return {
        'enabled': bool(value.get('enabled', False)),
        'advance_minutes': advance,
        'weekdays': weekdays,
        'stores': stores,
    }


def due_channels(settings, now, completed):
    """Return channel/cutoff pairs whose anticipation window is currently open."""
    if not settings['enabled'] or now.weekday() not in settings['weekdays']:
        return []
    due = []
    for channel, store in settings['stores'].items():
        if not store['enabled']:
            continue
        for slot in ('first', 'second'):
            cutoff = store[slot]
            if not cutoff:
                continue
            cutoff_at = datetime.combine(now.date(), datetime.strptime(cutoff, '%H:%M').time())
            starts_at = cutoff_at - timedelta(minutes=settings['advance_minutes'])
            key = f'{now.date().isoformat()}|{channel}|{slot}|{cutoff}'
            if starts_at <= now <= cutoff_at and key not in completed:
                due.append((channel, key))
    return due
