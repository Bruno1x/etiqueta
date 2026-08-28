"""Build a code-only release. Run from the project directory."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
tree = ast.parse((root / 'faturamento_bot/__init__.py').read_text('utf-8'))
version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets))
destination = root / 'dist'
destination.mkdir(exist_ok=True)
archive_path = destination / 'etiquetas-update.zip'
with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((root / 'faturamento_bot').rglob('*.py')):
        archive.write(path, path.relative_to(root).as_posix())
    archive.write(root / 'requirements.txt', 'requirements.txt')
    archive.writestr('update-release.json', json.dumps({'format': 1, 'version': version}))
(destination / 'etiquetas-update.sha256').write_text(
    hashlib.sha256(archive_path.read_bytes()).hexdigest() + '  etiquetas-update.zip\n', encoding='ascii')
print(f'Pacote de código {version} criado em dist. Configuração, imagens e histórico não incluídos.')
