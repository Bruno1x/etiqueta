"""Stable launcher. Versions are side by side; mutable local data never ships."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def resolve_version(base, relative):
    target = (base / relative).resolve()
    if target != base.resolve() and (not target.is_relative_to((base / '.updates').resolve())
                                      or target == (base / '.updates').resolve()):
        raise ValueError('Caminho de versão inválido.')
    if not (target / 'faturamento_bot/__main__.py').is_file():
        raise ValueError('Versão incompleta.')
    return target


def preserve_local(source, target):
    if source == target:
        return
    for name in ('config', 'runtime', 'assets'):
        if (source / name).exists():
            shutil.copytree(source / name, target / name, dirs_exist_ok=True)


def main():
    import msvcrt
    base = Path(__file__).resolve().parent
    lock = (base / '.update-launcher.lock').open('a+b')
    try:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise RuntimeError('O bot já está aberto nesta instalação. Feche-o antes de atualizar ou restaurar.')
    state_file = base / '.update-state.json'
    pending_file = base / '.update-pending.json'
    state = json.loads(state_file.read_text('utf-8')) if state_file.exists() else {'active': '.', 'previous': None}
    if '--rollback' in sys.argv:
        if not state.get('previous'):
            raise RuntimeError('Não existe versão anterior para restaurar.')
        write_json(pending_file, {'target': state['previous']})
    while True:
        active = resolve_version(base, state['active'])
        changed = False
        if pending_file.exists():
            try:
                request = json.loads(pending_file.read_text('utf-8'))
                target = resolve_version(base, request['target'])
                preserve_local(active, target)
                # Import/config check runs without opening the GUI or touching SYSEMP.
                subprocess.run([sys.executable, '-c', 'from faturamento_bot.config import load_config; load_config(); import faturamento_bot.gui'],
                               cwd=target, check=True, timeout=30)
            except Exception as error:
                os.replace(pending_file, base / '.update-failed.json')
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, f'Atualização não aplicada. A versão atual será mantida.\n{error}', 'Etiquetas Bot', 0x10)
            else:
                state = {'active': request['target'], 'previous': state['active']}
                write_json(state_file, state)
                pending_file.unlink()
                active = target
                changed = True
        env = dict(os.environ, ETIQUETAS_INSTALL_ROOT=str(base))
        result = subprocess.run([sys.executable, '-m', 'faturamento_bot', 'gui'], cwd=active, env=env)
        if result.returncode and changed and state.get('previous'):
            # Keep current data, revert the code pointer, and stop for inspection.
            previous = resolve_version(base, state['previous'])
            preserve_local(active, previous)
            write_json(state_file, {'active': state['previous'], 'previous': state['active']})
            raise RuntimeError('A nova versão encerrou com erro. A versão anterior foi restaurada; abra o bot novamente.')
        if not pending_file.exists():
            break
    lock.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), 'Atualização do Etiquetas Bot', 0x10)
        sys.exit(1)
