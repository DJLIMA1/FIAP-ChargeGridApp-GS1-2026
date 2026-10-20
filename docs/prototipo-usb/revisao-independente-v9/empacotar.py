from pathlib import Path
import hashlib,json,zipfile,shutil
base=Path(__file__).resolve().parent.parent;r=base/'ender3-pla-oficial-v9'
for p in r.rglob('__pycache__'):shutil.rmtree(p)
files={str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file() and p.name!='SHA256SUMS.json'}
(r/'SHA256SUMS.json').write_text(json.dumps({'release':'v9','date':'2026-10-15','geometry_release_date':'2026-10-14','algorithm':'sha256','files':files},indent=2)+'\n')
archive=base/'ChargeGrid-Ender3-PLA-OFICIAL-v9.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in sorted(r.rglob('*')):
  if p.is_file():z.write(p,'ChargeGrid-OFICIAL-v9/'+str(p.relative_to(r)))
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 for n,d in files.items():assert hashlib.sha256(z.read('ChargeGrid-OFICIAL-v9/'+n)).hexdigest()==d
idx=base/'integridade.json';data=json.loads(idx.read_text());c=data['constraints']
c.pop('only_changed_job_from_v6',None)
c.update(active_print_delivery='ender3-pla-oficial-v9',physical_fit_tested=True,physical_fit_scope='Only user-reported previous coupons and v5 standard cover snap; carrier pins, rigid stops with ties, lower cover variant, seams and full enclosure assembly remain physically untested',full_enclosure_physically_assembled=False,new_internal_pins_physically_tested=False,independent_review_completed=True,short_flexible_D_stop_removed=True,new_rigid_stops_and_ties_physically_assembled=False,join_keys_physically_fit_tested=False,join_socket_geometry_corrected=True,changed_jobs_from_v6=['03TRINF7','05QDINF8','10BERCO9','11TRAVA9'],sd_updated_to_v9=False)
for p in [base.parent/'plano-prototipo-usb.md',archive,*[p for p in r.rglob('*') if p.is_file()]]:
 n='../plano-prototipo-usb.md' if p.name=='plano-prototipo-usb.md' else str(p.relative_to(base));data['files'][n]=hashlib.sha256(p.read_bytes()).hexdigest()
idx.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
receipt={'files':len(files),'zip_bytes':archive.stat().st_size,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'zip_verified':True,'sd_copy_performed':False}
(base/'revisao-independente-v9/recibo-local.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
