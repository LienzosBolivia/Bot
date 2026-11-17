"""Ejecuta el laboratorio y conserva logs, estado, versión e informes."""
import argparse
import contextlib
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)
    def flush(self):
        for stream in self.streams: stream.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', default=None)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    out = Path(args.output_dir or f'outputs/{stamp}').resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('MPLBACKEND', 'Agg')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or 'unknown'
    status = dict(state='running', started_at=datetime.now(timezone.utc).isoformat(), commit=commit,
                  python=platform.python_version(), output_dir=str(out),
                  packages={p: importlib.metadata.version(p) for p in ['numpy', 'pandas', 'scipy', 'matplotlib', 'requests']})
    status_path = out/'status.json'
    status_path.write_text(json.dumps(status, indent=2), encoding='utf-8')
    exit_code = 0
    with (out/'execution.log').open('w', encoding='utf-8', buffering=1) as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            print(f'COMMIT: {commit}\nRESULTADOS: {out}', flush=True)
            try:
                import research
                research.main(out)
                status['state'] = 'completed'
            except BaseException as exc:
                status.update(state='failed', error=f'{type(exc).__name__}: {exc}')
                traceback.print_exc()
                exit_code = 130 if isinstance(exc, KeyboardInterrupt) else 1
            finally:
                status['finished_at'] = datetime.now(timezone.utc).isoformat()
                status_path.write_text(json.dumps(status, indent=2), encoding='utf-8')
                print(f"ESTADO: {status['state']}\nRESULTADOS: {out}", flush=True)
    return exit_code

if __name__ == '__main__':
    raise SystemExit(main())
