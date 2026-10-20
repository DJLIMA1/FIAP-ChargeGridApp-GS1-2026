"""Read-only check of prepared or copied SD content against the local expected manifest."""
from pathlib import Path
import json,hashlib,sys
if len(sys.argv)!=2:raise SystemExit('Uso: python3 verificar-copia.py /Volumes/NOME_DO_CARTAO')
ROOT=Path(__file__).resolve().parent;target=Path(sys.argv[1]).resolve()
expected_path=ROOT/'manifesto-esperado.json';manifest=json.loads(expected_path.read_text());failures=[]
for rel,digest in manifest['files'].items():
 p=target/rel
 if not p.is_file():failures.append({'file':rel,'error':'missing'});continue
 actual=hashlib.sha256(p.read_bytes()).hexdigest()
 if actual!=digest:failures.append({'file':rel,'error':'hash_mismatch'})
m=target/'CGDOC9/MANIFESTO-SD.json'
if not m.is_file() or m.read_bytes()!=expected_path.read_bytes():failures.append({'file':'CGDOC9/MANIFESTO-SD.json','error':'manifest_mismatch'})
expected_gc={n.casefold() for n in manifest['files'] if n.lower().endswith('.gcode')}
for p in (target/'CGFINAL').rglob('*'):
 if p.is_file() and p.suffix.lower()=='.gcode' and not p.name.startswith('._') and str(p.relative_to(target)).casefold() not in expected_gc:failures.append({'file':str(p.relative_to(target)),'error':'obsolete_or_unexpected_gcode'})
print(json.dumps({'root':str(target),'expected_files':len(manifest['files'])+1,'passed':not failures,'failures':failures},ensure_ascii=False,indent=2))
raise SystemExit(1 if failures else 0)
