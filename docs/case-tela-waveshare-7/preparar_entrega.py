"""Monta o pacote para a faculdade a partir de stl/ e parametros.json. Uso: python preparar_entrega.py (depois de gerar.py)."""
from pathlib import Path
import json, hashlib, shutil, zipfile, csv
import trimesh

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'entrega-faculdade'
ZIP = ROOT / 'ChargeGrid-Case-Tela7-Faculdade-v4.zip'
info = json.loads((ROOT / 'parametros.json').read_text())['verificacao']['arquivos']
GROUPS = {'1-TESTE-PRIMEIRO': [n for n in info if n.startswith('00-')],
          '2-PECAS': sorted(n for n in info if not n.startswith('00-'))}
# configuracao por arquivo: (preenchimento, adesao, pecas no arquivo, observacao)
CFG = {'00-TESTE-encaixe-moldura': ('20%', 'brim 5 mm', 2, 'frente na mesa'),
       '00-TESTE-encaixe-corpo': ('20%', 'brim 5 mm', 1, 'deitado no fundo, como o corpo'),
       '01-MOLDURA-esquerda': ('20%', 'saia', 1, 'frente visivel na mesa'),
       '01-MOLDURA-direita': ('20%', 'saia', 1, 'frente visivel na mesa'),
       '02-CORPO-esquerdo': ('20%', 'brim 5 mm', 1, 'deitado no fundo'),
       '02-CORPO-direito': ('20%', 'brim 5 mm', 1, 'deitado no fundo'),
       '03-BASE-esquerda': ('20%', 'saia', 1, 'deitada'),
       '03-BASE-direita': ('20%', 'saia', 1, 'deitada'),
}
for n in info:
    if n.startswith('04-CHAVES-'):
        CFG[n] = ('100%', 'saia', int(n.split('-')[-1][:-2]), 'chaves macicas')

if OUT.exists():
    shutil.rmtree(OUT)
rows, conf = [], {}
for group, names in GROUPS.items():
    (OUT / 'STL' / group).mkdir(parents=True)
    for n in names:
        src = ROOT / 'stl' / f'{n}.stl'; dst = OUT / 'STL' / group / f'{n}.stl'
        shutil.copyfile(src, dst)
        m = trimesh.load(dst); d = info[n]
        ext = [round(float(v), 2) for v in m.extents]
        assert all(abs(a - b) < 0.05 for a, b in zip(ext, d['dimensoes_mm'])) and m.is_watertight and max(ext) <= 178, (n, ext)
        fill, adh, qty, obs = CFG[n]
        rows.append([group, f'{n}.stl', *[f'{v:.1f}'.replace('.', ',') for v in ext], qty, f"{d['volume_cm3']:.1f}".replace('.', ','), fill, adh, obs])
        conf[f'STL/{group}/{n}.stl'] = dict(sha256=hashlib.sha256(dst.read_bytes()).hexdigest(), bytes=dst.stat().st_size,
                                            dimensoes_mm=ext, pecas=qty, volume_cm3=d['volume_cm3'], estanque=True)
with open(OUT / 'DIMENSOES.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f, delimiter=';')
    w.writerow(['pasta', 'arquivo', 'x_mm', 'y_mm', 'z_mm', 'pecas', 'volume_cm3', 'preenchimento', 'adesao', 'orientacao'])
    w.writerows(rows)
total = sum(v['bytes'] for v in conf.values())
(OUT / 'CONFERENCIA.json').write_text(json.dumps(dict(arquivos=conf, total_bytes=total, maior_dimensao_mm=max(max(v['dimensoes_mm']) for v in conf.values()),
                                                     limite_informado_mm=[180, 180, 180]), indent=2, ensure_ascii=False) + '\n')
for t in ['LEIA-ANTES-DE-ENVIAR.txt', 'CONFIGURACOES-DE-IMPRESSAO.txt']:
    shutil.copyfile(ROOT / 'textos-entrega' / t, OUT / t)
with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):  # noqa
        if p.is_file():
            z.write(p, p.relative_to(OUT))
print(f'{len(conf)} STL, {total / 1e6:.2f} MB, zip {ZIP.stat().st_size / 1e6:.2f} MB')
