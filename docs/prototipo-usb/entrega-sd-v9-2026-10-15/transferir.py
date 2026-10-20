"""Transferência delimitada ao ChargeGrid; conferir UUID antes de alterar o SD."""
from pathlib import Path
import datetime, hashlib, json, os, plistlib, shutil, subprocess, sys, zipfile

ROOT = Path(__file__).resolve().parent
CARD = Path('/Volumes/NO NAME')
UUID = '5D4EEFBC-2500-3F9A-B4FA-BCBCA63DC2A3'
STAGE = ROOT / 'CONTEUDO-SD'
MANIFEST = ROOT / 'manifesto-esperado.json'
RECEIPT = ROOT / 'recibo-transferencia.json'
REMOVE = [
    'CGFINAL', 'CGDOC6', 'COMECE.txt',
    '._CGFINAL', '._CGDOC6', '._COMECE.txt',
    '.Trashes/501/ChargeGrid-PLA-2026-10-14',
    '.Trashes/501/._ChargeGrid-PLA-2026-10-14',
    '.Trashes/501/00-teste-encaixes.3mf',
    '.Trashes/501/00-teste-encaixes.stl',
    '.Trashes/501/._00-teste-encaixes.3mf',
    '.Trashes/501/._00-teste-encaixes.stl',
]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def identify():
    p = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(CARD)]))
    assert p['VolumeUUID'] == UUID and p['MountPoint'] == str(CARD), p
    assert not p['Internal'] and p['RemovableMedia'] and p['WritableVolume'], p
    return {k:p[k] for k in ['VolumeUUID', 'DeviceIdentifier', 'ParentWholeDisk', 'MountPoint', 'TotalSize']}

def verify(target):
    m = json.loads(MANIFEST.read_text())
    failures = []
    for n, h in m['files'].items():
        p = target / n
        if not p.is_file() or digest(p) != h: failures.append(n)
    if (target/'CGDOC9/MANIFESTO-SD.json').read_bytes() != MANIFEST.read_bytes():
        failures.append('manifest_mismatch')
    expected = {n for n in m['files'] if n.lower().endswith('.gcode')}
    actual = {str(p.relative_to(target)) for p in target.rglob('*.gcode')
              if not any(s.startswith('.') for s in p.relative_to(target).parts)}
    if actual != expected: failures.append({'unexpected_or_missing_gcodes': sorted(actual ^ expected)})
    for n in REMOVE:
        # O macOS pode recriar AppleDouble para os nomes atuais; não são G-codes antigos.
        if n not in ['CGFINAL','COMECE.txt','._CGFINAL','._COMECE.txt'] and (target/n).exists():
            failures.append('obsolete: '+n)
    result = {'time':datetime.datetime.now().astimezone().isoformat(), 'files':len(m['files'])+1,
              'gcodes':len(expected), 'passed':not failures, 'failures':failures}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    assert not failures, failures
    return result

def install(receipt):
    identify()
    for n in REMOVE:
        p = CARD/n
        if p.is_dir(): shutil.rmtree(p)
        else: p.unlink(missing_ok=True)
    for p in sorted(STAGE.rglob('*')):
        target = CARD / p.relative_to(STAGE)
        if p.is_dir(): target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with p.open('rb') as src, target.open('wb') as dest:
                shutil.copyfileobj(src,dest,1024*1024)
                dest.flush()
                os.fsync(dest.fileno())
    subprocess.run(['sync'],check=True)
    receipt['phase'] = 'copied'
    RECEIPT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    result = verify(CARD)
    receipt['phase']='initial_readback_passed'
    receipt['readbacks'].append({'label':'immediate',**result})
    RECEIPT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'verify':
        identity = identify()
        result = verify(CARD)
        receipt = json.loads(RECEIPT.read_text())
        receipt.setdefault('readbacks', []).append({'label':sys.argv[2], 'device':identity, **result})
        RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    elif mode == 'copy':
        assert not RECEIPT.exists(), 'Transferência já iniciada; inspecionar recibo antes de repetir'
        identity = identify()
        verify(STAGE)
        assert not (CARD/'CGDOC9').exists(), 'Pasta v9 já existe; inspecionar antes de substituir'
        targets = [CARD/n for n in REMOVE if (CARD/n).exists()]
        files = sorted(p for t in targets for p in (t.rglob('*') if t.is_dir() else [t]) if p.is_file())
        assert not any(p.is_symlink() for t in targets for p in ([t]+list(t.rglob('*')) if t.is_dir() else [t]))
        before = {str(p.relative_to(CARD)):digest(p) for p in files}
        backup = ROOT.parent / 'arquivo-sd' / 'ChargeGrid-SD-antes-v9-20261015.zip'
        assert not backup.exists(), 'Backup já existe; não sobrescrever'
        with zipfile.ZipFile(backup, 'x', zipfile.ZIP_DEFLATED, compresslevel=3) as z:
            for p in files: z.write(p, str(p.relative_to(CARD)))
        with zipfile.ZipFile(backup) as z:
            assert z.testzip() is None
            assert set(z.namelist()) == set(before)
            for n, h in before.items():
                assert hashlib.sha256(z.read(n)).hexdigest() == h, 'Backup divergente: '+n
                assert digest(CARD/n) == h, 'Leitura instável antes da cópia: '+n
        receipt = {'delivery':'v9-pendentes','device':identity,'backup':str(backup),
                   'backup_sha256':digest(backup),'backup_files':before,'removed_paths':REMOVE,
                   'phase':'backup_verified','readbacks':[]}
        RECEIPT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'backup_verified':True,'files':len(files),'backup_bytes':backup.stat().st_size}),flush=True)
        install(receipt)
    elif mode == 'resume':
        identify()
        receipt=json.loads(RECEIPT.read_text())
        assert receipt['phase']=='backup_verified'
        backup=Path(receipt['backup'])
        assert digest(backup)==receipt['backup_sha256']
        with zipfile.ZipFile(backup) as z:
            assert z.testzip() is None
            for n,h in receipt['backup_files'].items():
                assert hashlib.sha256(z.read(n)).hexdigest()==h
        for n in REMOVE:
            t=CARD/n
            for p in (t.rglob('*') if t.is_dir() else [t]):
                if p.is_file():
                    rel=str(p.relative_to(CARD))
                    assert rel in receipt['backup_files'] and digest(p)==receipt['backup_files'][rel]
        verify(STAGE)
        install(receipt)
    else: raise SystemExit('Use copy, resume ou verify ROTULO')
