"""Celda de arranque: copiar completa a Google Colab y ejecutar."""
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import sys
import zipfile

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
print(f'Versión: {commit}\nResultados: {run_dir}', flush=True)
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
