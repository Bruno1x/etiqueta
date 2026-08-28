"""Public GitHub releases, code-only payloads and verified side-by-side staging."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import urllib.error
import urllib.request
import uuid
import zipfile

REPOSITORY = 'Bruno1x/etiqueta'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_PACKAGE = 20 * 1024 * 1024


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-[a-zA-Z0-9.-]+)?', value)
    if not match:
        raise ValueError('Formato de versão inválido.')
    return tuple(map(int, match.groups()))


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'EtiquetasBot-Updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=25) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError('Download excedeu o tamanho permitido.')
    return content


def latest(current):
    try:
        release = json.loads(fetch(API, 1024 * 1024))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if release.get('draft') or release.get('prerelease') or version_tuple(release['tag_name']) <= version_tuple(current):
        return None
    assets = {item['name']: item['browser_download_url'] for item in release['assets']}
    prefix = f'https://github.com/{REPOSITORY}/releases/download/{release["tag_name"]}/'
    for name in ('etiquetas-update.zip', 'etiquetas-update.sha256'):
        if name not in assets or not assets[name].startswith(prefix):
            raise ValueError('Release sem pacote e checksum válidos do repositório configurado.')
    return {'tag': release['tag_name'], 'zip': assets['etiquetas-update.zip'], 'sha': assets['etiquetas-update.sha256']}


def validate_payload(content, digest, current_requirements):
    if not re.fullmatch('[0-9a-fA-F]{64}', digest) or hashlib.sha256(content).hexdigest() != digest.lower():
        raise ValueError('Checksum do pacote não confere. Atualização cancelada.')
    files = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_PACKAGE:
            raise ValueError('Pacote descompactado excede o limite.')
        for item in archive.infolist():
            name = item.orig_filename
            path = PurePosixPath(name)
            if item.is_dir():
                continue
            allowed = (name in ('requirements.txt', 'update-release.json') or
                       (len(path.parts) >= 2 and path.parts[0] == 'faturamento_bot' and path.suffix == '.py'))
            if (not allowed or '\\' in name or '\x00' in name or ':' in name or '..' in path.parts or path.is_absolute()
                    or (item.external_attr >> 16) & 0o170000 == 0o120000 or name.casefold() in files):
                raise ValueError(f'Arquivo não autorizado no pacote: {name}')
            files[name.casefold()] = archive.read(item)
    for name in ('faturamento_bot/__main__.py', 'faturamento_bot/__init__.py', 'requirements.txt', 'update-release.json'):
        if name not in files:
            raise ValueError('Pacote incompleto.')
    if files['requirements.txt'].decode().split() != current_requirements.split():
        raise ValueError('Esta versão muda dependências. É necessária uma nova instalação completa.')
    manifest = json.loads(files['update-release.json'])
    if manifest.get('format') != 1:
        raise ValueError('Formato de atualização não suportado.')
    for name, data in files.items():
        if name.endswith('.py'):
            compile(data, name, 'exec')
    return files, manifest


def prepare_update(config, release):
    base_text = os.environ.get('ETIQUETAS_INSTALL_ROOT')
    if not base_text:
        raise RuntimeError('Abra o bot pelo novo ABRIR_FATURAMENTO_BOT.cmd para habilitar atualizações.')
    base = Path(base_text).resolve()
    if config.root.resolve() != base and not config.root.resolve().is_relative_to(base / '.updates'):
        raise ValueError('A instalação ativa não pertence a este atualizador.')
    checksum = fetch(release['sha'], 1024).decode('ascii').split()[0]
    content = fetch(release['zip'], MAX_PACKAGE)
    files, manifest = validate_payload(content, checksum, (config.root / 'requirements.txt').read_text('utf-8'))
    if version_tuple(manifest['version']) != version_tuple(release['tag']):
        raise ValueError('Versão do pacote difere da release.')
    version_source = files['faturamento_bot/__init__.py'].decode('utf-8')
    match = re.search(r'__version__\s*=\s*[\"\']([^\"\']+)', version_source)
    if not match or version_tuple(match[1]) != version_tuple(release['tag']):
        raise ValueError('Versão do código difere da release.')
    target = base / '.updates' / (release['tag'] + '-' + uuid.uuid4().hex)
    target.mkdir(parents=True)
    # Copy local-only resources; releases never contain screen captures or settings.
    for name in ('config', 'assets'):
        shutil.copytree(config.root / name, target / name)
    for name, data in files.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return {'target': target.relative_to(base).as_posix(), 'tag': release['tag'], 'base': str(base)}


def activate_on_close(prepared):
    base = Path(prepared['base'])
    temporary = base / '.update-pending.tmp'
    temporary.write_text(json.dumps({'target': prepared['target']}), encoding='utf-8')
    os.replace(temporary, base / '.update-pending.json')
