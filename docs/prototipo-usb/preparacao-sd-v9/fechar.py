from pathlib import Path
import json,hashlib,zipfile
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'CONTEUDO-SD';DOC=OUT/'CGDOC9';h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
# Current copy instructions reflect the user's confirmation; archive stays historical and unchanged.
for n in ['LEIA-PRIMEIRO.md','RELATORIO-REVISAO.md']:
 p=DOC/n;s=p.read_text();s=s.replace('O usuário informou que 01 já foi impresso e 02 está em impressão.','O usuário confirmou que 01CHAVE e 02TRSUP já foram impressos.').replace('Como 01 já foi impresso e 02 está em andamento, continue em 03TRINF7 depois de atualizar o SD.','Como 01CHAVE e 02TRSUP já foram impressos, continue em 03TRINF7 depois de atualizar o SD.').replace('Deixe a peça 02 terminar. Antes de iniciar 03','Com as peças 01 e 02 já impressas, antes de iniciar 03').replace('Deixe 02 terminar e atualize o cartão antes de iniciar 03.','Atualize o cartão antes de iniciar 03; 01 e 02 já foram impressos.');p.write_text(s)
files={str(f.relative_to(OUT)):h(f) for f in sorted(OUT.rglob('*')) if f.is_file() and f.name!='MANIFESTO-SD.json'}
manifest={'release':'v9','last_review_date':'2026-10-15','algorithm':'sha256','files':files,'already_printed':['01CHAVE.gcode','02TRSUP.gcode'],'next_print':'03TRINF7.gcode','card_written':False}
(DOC/'MANIFESTO-SD.json').write_text(json.dumps(manifest,indent=2)+'\n');(ROOT/'manifesto-esperado.json').write_bytes((DOC/'MANIFESTO-SD.json').read_bytes())
zip_path=ROOT.parent/'ChargeGrid-SD-PRONTO-v9.zip'
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for f in sorted(OUT.rglob('*')):
  if f.is_file():z.write(f,'CONTEUDO-SD/'+str(f.relative_to(OUT)))
 for name in ['LEIA-ANTES-DA-COPIA.md','verificar-copia.py','manifesto-esperado.json']:z.write(ROOT/name,name)
with zipfile.ZipFile(zip_path) as z:
 assert z.testzip() is None
 for n,d in files.items():assert hashlib.sha256(z.read('CONTEUDO-SD/'+n)).hexdigest()==d
 assert z.read('manifesto-esperado.json')==z.read('CONTEUDO-SD/CGDOC9/MANIFESTO-SD.json')
p=ROOT/'recibo-preparacao.json';data=json.loads(p.read_text());data.update(last_complete_review='2026-10-15',zip_sha256=h(zip_path),content_bytes=sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file()),prepared_files=len(files)+1,zip_bytes=zip_path.stat().st_size);p.write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data))
