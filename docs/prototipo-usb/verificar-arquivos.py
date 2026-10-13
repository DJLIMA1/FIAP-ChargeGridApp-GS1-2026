"""Confere hashes do pacote de estudo, sem testar a engenharia ou alterar arquivos."""
from pathlib import Path
import hashlib
import json
import sys

base = Path(__file__).resolve().parent
manifest = json.loads((base / 'integridade.json').read_text())
failures = []
for relative, expected in manifest['files'].items():
    path = base / relative
    if not path.is_file():
        failures.append({'file': relative, 'reason': 'missing'})
    elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        failures.append({'file': relative, 'reason': 'hash_changed'})
print(json.dumps({'checked_files': len(manifest['files']), 'failures': failures,
                  'scope': 'file integrity only; not manufacturing approval'},
                 ensure_ascii=False, indent=2))
sys.exit(1 if failures else 0)
