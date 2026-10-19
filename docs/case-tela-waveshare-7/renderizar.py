"""Previas do case com rasterizador z-buffer proprio (numpy + Pillow). Uso: python renderizar.py (depois de gerar.py)."""
from pathlib import Path
import json, math
import numpy as np, trimesh, manifold3d as md
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'previas'; OUT.mkdir(exist_ok=True)
P = json.loads((ROOT / 'parametros.json').read_text())
th = math.radians(P['tilt_deg']); S_, C_ = math.sin(th), math.cos(th)
S2W = np.array([[1, 0, 0], [0, S_, -C_], [0, C_, S_]])
FONT = ROOT.parents[1] / 'apps' / 'mobile' / 'assets' / 'Inter-SemiBold.ttf'
COL = {'moldura': (0.13, 0.14, 0.16), 'corpo': (0.92, 0.92, 0.93), 'base': (0.78, 0.12, 0.16),
       'vidro': (0.03, 0.03, 0.05), 'pcb': (0.12, 0.36, 0.66), 'usb': (0.45, 0.46, 0.50), 'mesa': (0.80, 0.82, 0.86),
       'peca': (0.96, 0.58, 0.18)}

def load(name, world=True):
    m = trimesh.load(ROOT / 'verificacao' / name)
    if world: m.vertices = m.vertices @ S2W.T
    return m

def cut(m, x0, keep=1):
    mm = md.Manifold(md.Mesh(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.uint32))).trim_by_plane([keep, 0, 0], keep * x0)
    o = mm.to_mesh(); return trimesh.Trimesh(np.array(o.vert_properties[:, :3]), np.array(o.tri_verts), process=False)

def render(parts, fname, elev, azim, title, size=(1500, 1000), ss=2, light=(-0.35, -0.8, 0.55), cut_normal=None):
    W, H = size[0] * ss, size[1] * ss
    e, a = math.radians(elev), math.radians(azim)
    cam = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])   # da cena para a camera
    f = -cam; r = np.cross(f, [0, 0, 1]); r /= np.linalg.norm(r); u = np.cross(r, f)
    allv = np.vstack([m.vertices for m, _ in parts])
    px, py = allv @ r, allv @ u
    sc = 0.86 * min(W / (px.max() - px.min()), H / (py.max() - py.min()))
    cx, cy = (px.max() + px.min()) / 2, (py.max() + py.min()) / 2
    zb = np.full((H, W), np.inf); img = np.ones((H, W, 3)); nid = np.zeros((H, W), np.int32)
    L = np.array(light, float); L /= np.linalg.norm(L)
    fid = 0
    for m, col in parts:
        v = m.vertices; tri = v[m.faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); nn = np.linalg.norm(n, axis=1); ok = nn > 1e-12
        tri, n = tri[ok], n[ok] / nn[ok, None]
        front = n @ f < 0
        tri, n = tri[front], n[front]
        X = (tri @ r - cx) * sc + W / 2; Y = H / 2 - (tri @ u - cy) * sc; Z = tri @ f
        diff = np.clip(n @ L, 0, 1); hv = (L - f) / np.linalg.norm(L - f); spec = np.clip(n @ hv, 0, 1) ** 40
        shade = 0.30 + 0.62 * diff + 0.10 * np.clip(n @ np.array([0.5, 0.6, 0.4]) / 1.0, 0, 1)
        colr = np.array(col)
        is_cut = np.zeros(len(n), bool) if cut_normal is None else (np.abs(n @ np.array(cut_normal)) > 0.999)
        for i in range(len(tri)):
            x, y, z = X[i], Y[i], Z[i]
            x0, x1 = max(int(x.min()), 0), min(int(x.max()) + 1, W - 1); y0, y1 = max(int(y.min()), 0), min(int(y.max()) + 1, H - 1)
            if x0 > x1 or y0 > y1: continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
            if abs(d) < 1e-9: continue
            w0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
            w1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
            w2 = 1 - w0 - w1
            msk = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not msk.any(): continue
            zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
            sub = zb[y0:y1 + 1, x0:x1 + 1]
            upd = msk & (zz < sub)
            if not upd.any(): continue
            sub[upd] = zz[upd]
            c = (colr * 0.55 + 0.05) if is_cut[i] else colr * shade[i] + spec[i] * 0.25
            img[y0:y1 + 1, x0:x1 + 1][upd] = np.clip(c, 0, 1)
            nid[y0:y1 + 1, x0:x1 + 1][upd] = fid + 1 + int(np.round((n[i] @ np.array([1, 7, 49])) * 4))
        fid += 1000
    # contornos: descontinuidades de profundidade e de normal
    fin = np.isfinite(zb); zf = np.where(fin, zb, zb[fin].max() + 50 if fin.any() else 0)
    edge = np.zeros_like(fin)
    dz = 1.2 / sc * ss
    for ax in (0, 1):
        edge |= np.abs(np.diff(zf, axis=ax, append=np.take(zf, [-1], axis=ax))) > 3.0 * dz * 2
        edge |= np.diff(nid, axis=ax, append=np.take(nid, [-1], axis=ax)) != 0
    edge &= fin | np.roll(fin, 1, 0) | np.roll(fin, 1, 1)
    img[edge] = img[edge] * 0.35
    im = Image.fromarray((img * 255).astype(np.uint8)).resize(size, Image.LANCZOS)
    dr = ImageDraw.Draw(im)
    try: fnt = ImageFont.truetype(str(FONT), 26)
    except Exception: fnt = None
    dr.text((28, 22), title, fill=(30, 30, 34), font=fnt)
    im.save(OUT / fname)

mol, cor, base, tela, usb, chv = (load(n) for n in ['montagem-moldura.stl', 'montagem-corpo.stl', 'montagem-base.stl', 'tela-referencia.stl', 'plugues-usb-c.stl', 'montagem-chaves.stl'])
COL['chave'] = (0.20, 0.55, 0.85)
asm = [(mol, COL['moldura']), (cor, COL['corpo']), (base, COL['base']), (tela, COL['vidro'])]
render(asm, '01-frente-3-4.png', 14, -62, 'Montado - frente 3/4')
render(asm, '02-lateral.png', 0, 0, 'Lateral - tela inclinada %.0f graus' % P['tilt_deg'], light=(0.8, -0.4, 0.5))
render(asm, '03-traseira-3-4.png', 20, 128, 'Traseira 3/4 - ventilacao e base (sem nome)', light=(0.3, 0.8, 0.6))
render([(cor, COL['corpo']), (base, COL['base']), (mol, COL['moldura']), (tela, COL['vidro']), (usb, COL['usb'])], '04-lateral-direita-usb.png', 6, -18,
       'Lateral direita - furos USB-C (plugues de exemplo)', light=(0.9, -0.4, 0.4))
nrm = np.array([0, -C_, S_])
mol2 = mol.copy(); mol2.vertices += nrm * 75; tela2 = tela.copy(); tela2.vertices += nrm * 42
base2 = base.copy(); base2.vertices += np.array([0, 0, -40])
render([(mol2, COL['moldura']), (tela2, COL['pcb']), (cor, COL['corpo']), (base2, COL['base'])], '05-explodida.png', 16, -50,
       'Explodida - moldura, tela, corpo, base (encaixe por pressao)')
for x0, f, t in [(0.0, '06-corte-centro.png', 'Corte X=0 - vidro preso entre moldura e corpo'),
                 (72.0, '07-corte-molas.png', 'Corte X=72 - mola impressa apoiando o verso do LCD'),
                 (55.0, '08-corte-ganchos.png', 'Corte X=55 - ganchos superior (bolso) e inferior (janela)')]:
    parts = [(cut(mol, x0), COL['moldura']), (cut(cor, x0), COL['corpo']), (cut(base, x0), COL['base']), (cut(tela, x0), COL['pcb'])]
    render(parts, f, 0, 180, t, light=(-0.9, -0.3, 0.4), cut_normal=(1, 0, 0))
render([(cor, COL['corpo']), (base, COL['base']), (chv, COL['chave'])], '09-interior.png', 32, -72, 'Interior - molas, nervura central com 3 chaves (azul), encaixes da base')
for f, t in [('01-MOLDURA-esquerda.stl', '10-impressao-moldura.png'), ('02-CORPO-esquerdo.stl', '11-impressao-corpo.png'),
             ('03-BASE-esquerda.stl', '12-impressao-base.png'), ('04-CHAVES-12un.stl', '14-impressao-chaves.png')]:
    m = trimesh.load(ROOT / 'stl' / f)
    bed = trimesh.creation.box([180, 180, 1.0]); bed.vertices += [0, 0, -0.5]
    render([(bed, COL['mesa']), (m, COL['peca'])], t, 30, -58, f + ' - orientacao de impressao, mesa 180 x 180')
bm = load('montagem-base.stl')
render([(bm, COL['base']), (chv, COL['chave'])], '13-base-por-baixo.png', -50, -60, 'Base por baixo - chaves da emenda, acessos de soltura, RESET/BOOT e pes', light=(-0.3, -0.5, -0.8))
print(sorted(p.name for p in OUT.glob('*.png')))
