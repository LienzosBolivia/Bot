"""Celda de arranque: copiar completa a Google Colab y ejecutar."""
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import sys
import zipfile
import hashlib
import json

REPO_URL = 'https://github.com/LienzosBolivia/Bot.git'
BRANCH = 'main'
PROJECT = Path('/content/bot')
RESULTS = Path('/content/bot_results')

def command(*args, cwd=None):
    subprocess.run(list(args), cwd=cwd, check=True)

if not PROJECT.exists():
    command('git', 'clone', '--branch', BRANCH, '--single-branch', REPO_URL, str(PROJECT))
else:
    if not (PROJECT / '.git').is_dir():
        raise RuntimeError(f'{PROJECT} existe pero no es una copia Git del proyecto.')
    remote = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=PROJECT, text=True).strip()
    if remote != REPO_URL:
        raise RuntimeError(f'El directorio pertenece a otro repositorio: {remote}')
    command('git', 'fetch', 'origin', BRANCH, cwd=PROJECT)
    # Copia de ejecución desechable. Los resultados se guardan fuera de ella.
    command('git', 'checkout', '-B', BRANCH, f'origin/{BRANCH}', cwd=PROJECT)
    command('git', 'reset', '--hard', f'origin/{BRANCH}', cwd=PROJECT)

command(sys.executable, '-m', 'pip', 'install', '--quiet', '-r', str(PROJECT/'requirements.txt'))
commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=PROJECT, text=True).strip()
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
run_dir = RESULTS / f'{stamp}_{commit}'
run_dir.mkdir(parents=True)
# Congelar los archivos ANTES de ejecutar: el TXT corresponde a esta versión.
full_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip()
tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=PROJECT).split(b'\0')
sections = [
    'CÓDIGO COMPLETO — BOT BTC/BNB',
    f'Commit: {full_commit}',
    f'Ejecución UTC: {stamp}',
    'Copia de revisión organizada por archivo. No es un script ejecutable único.',
    'Incluye fuentes Python, dependencias y celdas de código del notebook.',
    'Los tests y el notebook se incluyen como referencia; no todos se ejecutan en el ensayo.',
    '',
]
for raw_name in sorted(n for n in tracked if n):
    name = raw_name.decode('utf-8')
    path = PROJECT / name
    if path.suffix not in {'.py', '.ipynb'} and name != 'requirements.txt':
        continue
    data = path.read_bytes()
    sections.extend(['=' * 80, f'ARCHIVO: {name}',
                     f'SHA256: {hashlib.sha256(data).hexdigest()}', '=' * 80])
    if path.suffix == '.ipynb':
        notebook = json.loads(data.decode('utf-8'))
        for number, cell in enumerate(notebook.get('cells', []), 1):
            if cell.get('cell_type') == 'code':
                source = cell.get('source', [])
                sections.extend([f'# Celda {number}', ''.join(source) if isinstance(source, list) else source])
    else:
        sections.append(data.decode('utf-8'))
    sections.append('')
source_snapshot = run_dir / 'codigo_completo.txt'
source_snapshot.write_text('\n'.join(sections), encoding='utf-8')
print(f'Versión: {commit}\nResultados: {run_dir}\nCódigo: {source_snapshot}', flush=True)
try:
    # Proceso nuevo: no reutiliza módulos/variables de ejecuciones anteriores.
    process = subprocess.Popen([sys.executable, '-u', 'run.py', '--output-dir', str(run_dir)],
                               cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    with (run_dir/'colab.log').open('w', encoding='utf-8') as log:
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    print(f'Código de salida: {code}', flush=True)
    from IPython.display import display, Image
    if (run_dir/'equity_dev.png').exists(): display(Image(filename=str(run_dir/'equity_dev.png')))
finally:
    archive = RESULTS/f'{run_dir.name}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(run_dir.rglob('*')):
            if path.is_file(): z.write(path, path.relative_to(run_dir))
    print(f'Logs e informes: {archive}', flush=True)
    from google.colab import files
    files.download(str(archive))
    files.download(str(source_snapshot))
