"""Case inclinado para a Waveshare ESP32-S3-Touch-LCD-7 (com touch). Python + numpy + manifold3d + trimesh.

Pecas impressas, unidas so por travas, chaves e cola (nenhum parafuso):
  1. MOLDURA  - frente; segura o vidro pela borda e tem 6 ganchos.
  2. CORPO    - cunha inclinada; recebe os ganchos e empurra o LCD com 6 molas impressas.
  3. BASE     - apoio traseiro que encaixa por baixo do corpo.
Para caber em impressoras de 180 x 180 x 180 mm, cada peca sai em metades (esquerda/direita) unidas por
chaves borboleta impressas e cola. Sem nome ou logotipo nas superficies.

Referencial da tela (S): X para a direita olhando a tela, V para cima, Z saindo da tela.
Z = 0 e a face frontal do vidro. Mundo (W): x direita, y para tras, z para cima.
Uso: python gerar.py   (gera stl/, verificacao/ e parametros.json)
"""
from pathlib import Path
import json, math, os
import numpy as np
import manifold3d as md
import trimesh

ROOT = Path(__file__).resolve().parent
for d in ['stl', 'verificacao']:
    (ROOT / d).mkdir(exist_ok=True)

# ---------------------------------------------------------------- medidas da tela (desenho oficial Waveshare)
GLASS_W, GLASS_H, GLASS_R = 192.96, 110.76, 7.88   # vidro touch
STACK = 5.00                                        # TP + LCD (desenho: "TP+LCD=5.00")
PCB_FRONT = 8.50                                    # vidro -> face da PCB voltada ao LCD
PCB_T = 1.6
LCD = dict(x0=-84.39, x1=81.33, v0=-48.08, v1=49.52)          # quadro metalico do LCD (165.72 x 97.6)
M3 = [(61.57, -33.80), (61.57, 31.85), (-64.63, -33.80), (-64.63, 31.85)]  # suportes M3 originais
# STEP da PCB (vista traseira) -> S: X = 55.04 - x, V = y - 47.30, Z = -10.1 - z
PCB_X0, PCB_Y0 = 55.04, -47.30

# ---------------------------------------------------------------- parametros do case
P = dict(
    tilt_deg=20.0,          # inclinacao da tela para tras
    clr_glass=0.35,         # folga vidro -> saia da moldura (por lado)
    skirt_t=2.0, skirt_depth=6.5,
    clr_fit=0.25,           # folga saia -> corpo (por lado)
    collar_wall=3.0, wall=3.0,     # paredes principais com 3 mm (recomendacao do laboratorio)
    plate_t=3.0, lip=2.5, window_chamfer=1.5, outer_chamfer=1.0,
    chin=9.0,               # queixo inferior (abriga os ganchos inferiores com a inclinacao de 20 graus)
    top_depth=28.0,         # espessura do corpo no topo (sem a moldura)
    r_top=None, r_bottom=6.0, ch_back=6.0, ch_back_bottom=2.0,   # arestas que tocam a mesa de impressao: chanfros >= 45 graus
    hook_len=16.0, hook_t=1.6, hook_w=10.0,
    spring_t=1.2, spring_w=8.0, spring_len=16.0, spring_angle=50.0, spring_preload=0.4, post_d=8.0,
    usb_hole=[13.5, 8.5], pin_d=2.2,
    key_clear=0.15, bed_max=180.0,   # chaves borboleta; limite da impressora da faculdade
    base_t=4.0, base_back=50.0, base_r_back=20.0, base_hook_x=40.0, base_hook_y=24.0, base_hook_len=13.0,
)
P.update(json.loads(os.environ.get('CASE_PARAMS', '{}')))   # para estudos: CASE_PARAMS='{"tilt_deg": 20}'
th = math.radians(P['tilt_deg']); S_, C_ = math.sin(th), math.cos(th)

GX, GV = GLASS_W / 2, GLASS_H / 2
SK_IN_X, SK_IN_V = GX + P['clr_glass'], GV + P['clr_glass']
SK_OUT_X, SK_OUT_V = SK_IN_X + P['skirt_t'], SK_IN_V + P['skirt_t']
CAV_X, CAV_V = SK_OUT_X + P['clr_fit'], SK_OUT_V + P['clr_fit']
OUT_X, OUT_TOP = CAV_X + P['collar_wall'], CAV_V + P['collar_wall']
OUT_BOT = -OUT_TOP - P['chin']
R_OUT = GLASS_R + (OUT_X - GX)
P['r_top'] = round(R_OUT, 3)
R_SK_IN, R_SK_OUT, R_CAV = GLASS_R + P['clr_glass'], GLASS_R + P['clr_glass'] + P['skirt_t'], GLASS_R + (CAV_X - GX)

def to_world(X, V, Z):
    return X, V * S_ - Z * C_, V * C_ + Z * S_      # x, y (para tras), z

Z_TABLE = OUT_BOT * C_                              # mesa passa pela aresta frontal inferior
Y_BACK = OUT_TOP * S_ + P['top_depth'] * C_          # plano traseiro (vertical)

# ---------------------------------------------------------------- utilitarios
def poly_round(pts, radii, seg=10):
    pts = [np.array(p, float) for p in pts]; out = []
    n = len(pts)
    for i, p in enumerate(pts):
        r = radii[i] if isinstance(radii, (list, tuple)) else radii
        if r <= 0:
            out.append(tuple(p)); continue
        a, b = pts[i - 1] - p, pts[(i + 1) % n] - p
        a /= np.linalg.norm(a); b /= np.linalg.norm(b)
        ang = math.acos(max(-1, min(1, float(a @ b))))
        d = r / math.tan(ang / 2)
        p1, p2 = p + a * d, p + b * d
        bis = (a + b) / np.linalg.norm(a + b)
        c = p + bis * (r / math.sin(ang / 2))
        a1, a2 = math.atan2(*(p1 - c)[::-1]), math.atan2(*(p2 - c)[::-1])
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        for k in range(seg + 1):
            t = a1 + da * k / seg
            out.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return out

def poly_chamfer(pts, dists):
    """substitui vertices por chanfros; dist = d ou (d_aresta_anterior, d_aresta_seguinte)."""
    pts = [np.array(p, float) for p in pts]; out = []
    for i, p in enumerate(pts):
        d = dists[i]
        da, db = (d, d) if np.isscalar(d) else d
        if max(da, db) <= 0:
            out.append(tuple(p)); continue
        a, b = pts[i - 1] - p, pts[(i + 1) % len(pts)] - p
        out += [tuple(p + a / np.linalg.norm(a) * da), tuple(p + b / np.linalg.norm(b) * db)]
    return out

def area(pts):
    p = np.array(pts); return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))

def ccw(pts):
    return pts if area(pts) > 0 else pts[::-1]

def rrect(x0, x1, y0, y1, r_top, r_bot, seg=16):
    return ccw(poly_round([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [r_bot, r_bot, r_top, r_top], seg))

def prism_z(pts, z0, z1):   # perfil (X,V) extrudado em Z
    return md.Manifold.extrude(md.CrossSection([ccw(pts)]), z1 - z0).translate([0, 0, z0])

def prism_x(pts_vz, x0, x1):  # perfil (V,Z) extrudado em X
    m = md.Manifold.extrude(md.CrossSection([ccw(pts_vz)]), x1 - x0).translate([0, 0, x0])
    return m.transform(np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], float))

def prism_v(pts_xz, v0, v1):  # perfil (X,Z) extrudado em V
    m = md.Manifold.extrude(md.CrossSection([ccw(pts_xz)]), v1 - v0).translate([0, 0, -v1])
    return m.transform(np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0]], float))

W2S = np.array([[1, 0, 0, 0], [0, S_, C_, 0], [0, -C_, S_, 0]], float)   # mundo -> S
S2W = np.array([[1, 0, 0, 0], [0, S_, -C_, 0], [0, C_, S_, 0]], float)   # S -> mundo

def world_prism_z(pts_xy, z0, z1):  # prisma vertical no mundo, devolvido em S
    return md.Manifold.extrude(md.CrossSection([ccw(pts_xy)]), z1 - z0).translate([0, 0, z0]).transform(W2S)

def box(x0, x1, v0, v1, z0, z1):
    return md.Manifold.cube([x1 - x0, v1 - v0, z1 - z0]).translate([x0, v0, z0])

def U(items): return md.Manifold.batch_boolean(items, md.OpType.Add)
def D(a, items): return md.Manifold.batch_boolean([a] + items, md.OpType.Subtract)

def bowtie(half_len, end_w, neck_w):   # chave borboleta, eixo longo em x
    return ccw([(-half_len, -end_w / 2), (0, -neck_w / 2), (half_len, -end_w / 2), (half_len, end_w / 2), (0, neck_w / 2), (-half_len, end_w / 2)])

def key_offset(pts, d):
    return ccw([tuple(q) for q in md.CrossSection([pts]).offset(d, md.JoinType.Miter, 4.0).to_polygons()[0]])

KEY_BIG = bowtie(12.0, 12.0, 6.0)      # corpo e base
KEY_SMALL = bowtie(9.0, 8.5, 4.2)      # moldura (queixo)

# ---------------------------------------------------------------- MOLDURA
outline = rrect(-OUT_X, OUT_X, OUT_BOT, OUT_TOP, R_OUT, P['r_bottom'])
pt, ch, oc = P['plate_t'], P['window_chamfer'], P['outer_chamfer']
plate = U([prism_z(outline, 0, pt - oc)] + [
    prism_z(ccw([tuple(p) for p in md.CrossSection([outline]).offset(-oc * k / 4, md.JoinType.Round).to_polygons()[0]]),
            pt - oc + oc * (k - 1) / 4, pt - oc + oc * k / 4) for k in range(1, 5)])
win = rrect(-(GX - P['lip']), GX - P['lip'], -(GV - P['lip']), GV - P['lip'], GLASS_R - P['lip'], GLASS_R - P['lip'])
win_cut = [prism_z(win, -1, pt + 1)]
for k in range(1, 6):     # chanfro 45 graus da janela, alargando para a frente
    z0 = pt - ch + ch * (k - 1) / 5
    grow = ch * k / 5
    win_cut.append(prism_z(ccw([tuple(p) for p in md.CrossSection([win]).offset(grow, md.JoinType.Round).to_polygons()[0]]), z0, pt + 1))
skirt_out = rrect(-SK_OUT_X, SK_OUT_X, -SK_OUT_V, SK_OUT_V, R_SK_OUT, R_SK_OUT)
skirt_in = rrect(-SK_IN_X, SK_IN_X, -SK_IN_V, SK_IN_V, R_SK_IN, R_SK_IN)
skirt = D(prism_z(skirt_out, -P['skirt_depth'], 0.01), [prism_z(skirt_in, -P['skirt_depth'] - 1, 0.0)])
bezel = D(U([plate, skirt]), win_cut)

Z_SK = -P['skirt_depth']; Z_TIP = Z_SK - P['hook_len']
HT, HW = P['hook_t'], P['hook_w']
# (eixo, sinal, centro ao longo da borda, tipo) tipo 'janela' = 90 graus com janela de soltura; 'bolso' = 45 graus escondido
HOOKS = [('V', +1, -55.0, 'bolso'), ('V', +1, 55.0, 'bolso'),
         ('V', -1, -55.0, 'janela'), ('V', -1, 55.0, 'janela'),
         ('X', -1, 0.0, 'bolso'), ('X', +1, 30.0, 'bolso')]
LIP = {'bolso': [(-0.2, -19.6), (0.0, -19.6), (1.0, -20.6), (1.0, -20.8), (0.0, Z_TIP), (-0.2, Z_TIP)],
       'janela': [(-0.2, -19.6), (1.2, -19.6), (1.2, -20.4), (0.0, Z_TIP), (-0.2, Z_TIP)]}

def place_pz(pz_pts, axis, sign, c, w):
    """perfil (p, Z) onde p = distancia para fora da face externa da saia; largura w ao longo da borda."""
    if axis == 'V':
        base = SK_OUT_V
        prof = [(sign * (base + p), z) for p, z in pz_pts]           # (V, Z)
        return prism_x(prof, c - w / 2, c + w / 2)
    base = SK_OUT_X
    prof = [(sign * (base + p), z) for p, z in pz_pts]               # (X, Z)
    return prism_v(prof, c - w / 2, c + w / 2)

hooks = []
for axis, sign, c, kind in HOOKS:
    beam = [(-HT, Z_SK + 0.6), (0, Z_SK + 0.6), (0, Z_TIP), (-HT, Z_TIP)]
    hooks += [place_pz(beam, axis, sign, c, HW), place_pz(LIP[kind], axis, sign, c, HW)]
bezel = U([bezel] + hooks)
# chave borboleta no verso do queixo (fora da saia): une as metades da moldura sem aparecer na frente
V_KEY_BEZEL = (-(SK_OUT_V + 0.5) + (OUT_BOT + 1.5)) / 2
bezel = bezel - prism_z([(x, y + V_KEY_BEZEL) for x, y in key_offset(KEY_SMALL, P['key_clear'])], -1.0, 1.6)
key_bezel = prism_z([(x, y + V_KEY_BEZEL) for x, y in KEY_SMALL], 0.1, 1.6)

# ---------------------------------------------------------------- CORPO
# perfil lateral externo (V,Z)
F_T = (OUT_TOP, 0.0)
B_T = (OUT_TOP, -P['top_depth'])
B_B = (Y_BACK * S_ + Z_TABLE * C_, -Y_BACK * C_ + Z_TABLE * S_)
F_B = (OUT_BOT, 0.0)
# chanfro superior traseiro assimetrico: a face fica a 45 graus da mesa de impressao (o topo ja cai 20 graus)
k45 = (C_ - S_)                                   # d_costas = k45 * d_topo
prof_out = poly_chamfer([F_T, B_T, B_B, F_B], [0, (P['ch_back'] + 1, (P['ch_back'] + 1) * k45), P['ch_back_bottom'], 0])
w = P['wall']
yb_in, zt_in = Y_BACK - w, Z_TABLE + w
cA = (CAV_V, 5.0)
cB = (CAV_V, (CAV_V * S_ - yb_in) / C_)
cC = (yb_in * S_ + zt_in * C_, -yb_in * C_ + zt_in * S_)
cD = (-CAV_V, (zt_in + CAV_V * C_) / S_)
cE = (-CAV_V, 5.0)
prof_in = poly_round([cA, cB, cC, cD, cE], [0, 3.0, 1.0, 0, 0])

outer = U([prism_x(prof_out, -OUT_X, OUT_X)])
outer = outer ^ prism_z(rrect(-OUT_X, OUT_X, OUT_BOT, OUT_TOP, R_OUT, P['r_bottom']), -120, 0)
outer = outer ^ world_prism_z(ccw(poly_chamfer([(-OUT_X, -200), (OUT_X, -200), (OUT_X, Y_BACK), (-OUT_X, Y_BACK)], [0, 0, (P['ch_back'] * 1.3, P['ch_back']), (P['ch_back'], P['ch_back'] * 1.3)])), -150, 150)
cav = prism_x(prof_in, -CAV_X, CAV_X)
cav = cav ^ prism_z(rrect(-CAV_X, CAV_X, -CAV_V, CAV_V, R_CAV, R_CAV), -120, 6)
cav = cav ^ world_prism_z(ccw(poly_chamfer([(-CAV_X, -200), (CAV_X, -200), (CAV_X, yb_in), (-CAV_X, yb_in)], [0, 0, (P['ch_back'] * 1.3 - 1.0, P['ch_back'] - 1.0), (P['ch_back'] - 1.0, P['ch_back'] * 1.3 - 1.0)])), -150, 150)
body = outer - cav

# molas: postes a partir da parede traseira + dedo a 50 graus que empurra o verso do LCD
PADS = [(72.0, 42.0, +1), (72.0, -42.0, +1), (-73.0, 42.0, -1), (-73.0, -42.0, -1), (-73.0, 0.0, -1), (-35.0, 40.0, -1)]
ang = math.radians(P['spring_angle']); L, t, bw = P['spring_len'], P['spring_t'], P['spring_w']
nub_r = 1.0
Z_LCD_BACK = -STACK
Z_NUB_TOP = Z_LCD_BACK + P['spring_preload']
springs, spring_info = [], []
for xp, vp, sd in PADS:
    z_tip = Z_NUB_TOP - 2 * nub_r + 0.2                       # centro da viga na ponta
    x_root = xp + sd * L * math.cos(ang); z_root = z_tip - L * math.sin(ang)
    x_post = x_root + sd * P['post_d'] / 2
    # viga: retangulo (X,Z) rotacionado
    d = np.array([xp - x_root, z_tip - z_root]) / L
    n = np.array([-d[1], d[0]])
    a0 = np.array([x_root, z_root]) - d * 1.5; a1 = np.array([xp, z_tip]) + d * 0.6
    beam = [tuple(a0 - n * t / 2), tuple(a1 - n * t / 2), tuple(a1 + n * t / 2), tuple(a0 + n * t / 2)]
    nub = md.Manifold.cylinder(6.0, nub_r, nub_r, 32).rotate([90, 0, 0]).translate([xp, vp + 3.0, Z_NUB_TOP - nub_r])
    post = md.Manifold.cylinder(80, P['post_d'] / 2, P['post_d'] / 2, 40).translate([x_post, vp, z_root + 0.8 - 80])
    springs += [prism_v(beam, vp - bw / 2, vp + bw / 2), nub, post ^ outer]
    spring_info.append(dict(pad_X=xp, pad_V=vp, poste_X=round(x_post, 2), raiz_Z=round(z_root, 2), topo_ressalto_Z=round(Z_NUB_TOP, 2)))
body = U([body] + springs)

# encaixes dos ganchos
cuts = []
for axis, sign, c, kind in HOOKS:
    if kind == 'janela':
        cuts.append(box(c - HW / 2 - 0.5, c + HW / 2 + 0.5, -200, -CAV_V + 0.5, -23.5, -19.55))
    else:
        # bolso cego: face frontal a 45 graus (mesma inclinacao do dente), 0,05 mm a frente do dente
        pz = [(-0.1, -19.45), (1.35, -20.9), (1.35, -23.2), (-0.1, -23.2)]
        cuts.append(place_pz(pz, axis, sign, c, HW + 1.0))
# furos USB-C na lateral direita (eixo X)
USB_V = [35.735 + PCB_Y0, 50.835 + PCB_Y0]
USB_Z = -(PCB_FRONT + PCB_T) - 1.17
hw, hh = P['usb_hole']
for vc in USB_V:
    hole = rrect(vc - hw / 2, vc + hw / 2, USB_Z - hh / 2, USB_Z + hh / 2, 2.0, 2.0)
    m = md.Manifold.extrude(md.CrossSection([ccw(hole)]), 10).translate([0, 0, CAV_X - 2])
    cuts.append(m.transform(np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], float)))
    for k in range(4):  # chanfro externo
        g = 0.8 * (k + 1) / 4
        hole2 = ccw([tuple(p) for p in md.CrossSection([ccw(hole)]).offset(g, md.JoinType.Round).to_polygons()[0]])
        m = md.Manifold.extrude(md.CrossSection([hole2]), 3).translate([0, 0, OUT_X - 0.8 + 0.8 * k / 4])
        cuts.append(m.transform(np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], float)))
# furos de pino para RESET / BOOT (por baixo)
BTN = {'RESET': 55.04 - 48.10, 'BOOT': 55.04 - 59.20}
Z_BTN = -(PCB_FRONT + PCB_T) - 0.07
for name, xb in BTN.items():
    cuts.append(md.Manifold.cylinder(30, P['pin_d'] / 2, P['pin_d'] / 2, 24).rotate([-90, 0, 0]).translate([xb, -85, Z_BTN]))
# ventilacao traseira (mundo)
vent = U([md.Manifold.cube([3.0, 20, 34]).translate([(i + 0.5) * 7.0 - 1.5, Y_BACK - 10, 0]) for i in range(-5, 5)])
cuts.append(vent.transform(W2S))     # 10 fendas, nenhuma sobre a emenda central
body = D(body, cuts)

# emenda central do corpo: nervura na parede traseira com 3 chaves borboleta (encaixe pelo lado de dentro)
def world_xz(poly_xz, y0, y1):    # perfil (x, z) do mundo extrudado de y0 a y1
    m = md.Manifold.extrude(md.CrossSection([ccw(poly_xz)]), y1 - y0).translate([0, 0, -y1])
    return m.transform(np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0]], float))
y_rib = Y_BACK - w - 4.5
rib_w = md.Manifold.cube([34.0, 5.0, -2.5 - (Z_TABLE + w - 0.5)]).translate([-17.0, y_rib, Z_TABLE + w - 0.5])
body = body + (rib_w.transform(W2S) ^ outer)
key_z = [Z_TABLE + w + 11.0, (Z_TABLE + w + 11.0 - 12.0) / 2, -12.0]
body = body - U([world_xz([(x, z + zc) for x, z in key_offset(KEY_BIG, P['key_clear'])], y_rib - 1.0, y_rib + 3.2).transform(W2S) for zc in key_z])
keys_body = [world_xz([(x, z + zc) for x, z in KEY_BIG], y_rib + 0.1, y_rib + 3.1).transform(W2S) for zc in key_z]

# ---------------------------------------------------------------- BASE (opcional, aumenta o apoio traseiro)
# Mundo: a base fica sob o corpo; topo da base = mesa do corpo (Z_TABLE). Dois ganchos sobem pelo piso do corpo
# e prendem em janelas de nervuras internas. Sem parafusos; sai puxando com firmeza (dente a 45 graus).
bt_, bk = P['base_t'], P['base_back']
y_front = to_world(0, OUT_BOT, P['plate_t'])[1] - 0.3
base_ol = rrect(-OUT_X, OUT_X, y_front, Y_BACK + bk, P['base_r_back'], P['r_bottom'])
base = md.Manifold.extrude(md.CrossSection([base_ol]), bt_ - 1.0)
for k in range(1, 5):   # chanfro superior 1 mm
    ol = ccw([tuple(q) for q in md.CrossSection([base_ol]).offset(-0.25 * k, md.JoinType.Round).to_polygons()[0]])
    base = base + md.Manifold.extrude(md.CrossSection([ol]), 0.25).translate([0, 0, bt_ - 1.0 + 0.25 * (k - 1)])
base = base.translate([0, 0, Z_TABLE - bt_])
for fx in (-OUT_X + 18, OUT_X - 18):     # rebaixos para pes de borracha adesivos (10 mm)
    for fy in (y_front + 14, Y_BACK + bk - 16):
        base = base - md.Manifold.cylinder(1.6, 5.3, 5.3, 48).translate([fx, fy, Z_TABLE - bt_ - 0.6])
hx, hy, HL = P['base_hook_x'], P['base_hook_y'], P['base_hook_len']
z_floor_in = Z_TABLE + w
z_catch = Z_TABLE + HL - 3.0                       # face de retencao do dente
base_hooks, body_catch, body_slots = [], [], []
for sx in (-1, 1):
    c = sx * hx
    xo = c + sx * 0.8                                # face externa da haste
    beam = md.Manifold.cube([1.6, 10.0, HL + 1.0]).translate([c - 0.8, hy - 5.0, Z_TABLE - 0.6])   # haste passa 0,4 do dente
    # dente sobreposto 0,2 mm a haste (nenhum vertice exatamente na face da haste)
    lip_xz = [(xo - sx * 0.2, z_catch - 0.2), (xo + sx * 0.8, z_catch + 0.8), (xo + sx * 0.8, z_catch + 1.0),
              (xo - sx * 0.2, Z_TABLE + HL + 0.3)]
    lip = md.Manifold.extrude(md.CrossSection([ccw([(x, -z) for x, z in lip_xz])]), 10.0).translate([0, 0, -hy - 5.0]) \
        .transform(np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, -1, 0, 0]], float))
    base_hooks += [beam, lip]
    # rasgo no piso do corpo (folga para dentro, onde a haste flexiona)
    xs = sorted([c - sx * (0.8 + 0.6), c + sx * (0.8 + 0.25)])
    body_slots.append(md.Manifold.cube([xs[1] - xs[0], 10.6, 6.0]).translate([xs[0], hy - 5.3, Z_TABLE - 2.0]))
    # nervura com janela: o dente entra na janela
    xr = c + sx * (0.8 + 0.25)
    rib = md.Manifold.cube([1.8, 14.0, HL + 3.0 - 0.5]).translate([xr if sx > 0 else xr - 1.8, hy - 7.0, Z_TABLE + 1.0])
    win_r = md.Manifold.cube([4.0, 10.6, 3.2]).translate([xr - 1.0 if sx > 0 else xr - 3.0, hy - 5.3, z_catch - 0.05])
    body_catch.append(rib - win_r)
# furos de acesso na base: janelas de soltura da moldura e pinos RESET/BOOT continuam alcancaveis por baixo
def on_table(Z):   # ponto do plano da mesa para um Z da tela -> y do mundo
    V = (Z_TABLE - Z * S_) / C_; return V * S_ - Z * C_
acc = []
for axis, sign, c, kind in HOOKS:
    if kind == 'janela':
        ya, yb = sorted([on_table(-23.5), on_table(-19.55)])
        acc.append(md.Manifold.cube([HW + 2.0, yb - ya + 1.0, bt_ + 2]).translate([c - HW / 2 - 1.0, ya - 0.5, Z_TABLE - bt_ - 1]))
for name, xb in BTN.items():
    acc.append(md.Manifold.cylinder(bt_ + 2, 2.0, 2.0, 32).translate([xb, on_table(Z_BTN), Z_TABLE - bt_ - 1]))
key_y_base = [y_front + 30.0, Y_BACK + bk - 30.0]
for yk in key_y_base:   # chaves borboleta por baixo da base, rentes
    acc.append(md.Manifold.extrude(md.CrossSection([[(x, y + yk) for x, y in key_offset(KEY_BIG, P['key_clear'])]]), 3.1).translate([0, 0, Z_TABLE - bt_ - 1.0]))
keys_base = [md.Manifold.extrude(md.CrossSection([[(x, y + yk) for x, y in KEY_BIG]]), 2.0).translate([0, 0, Z_TABLE - bt_ + 0.1]) for yk in key_y_base]
base = D(U([base] + base_hooks), acc)
body = D(U([body] + [m.transform(W2S) for m in body_catch]), [m.transform(W2S) for m in body_slots])
base_w = base

# ---------------------------------------------------------------- exportar
def mesh(s):
    m = s.to_mesh(); return trimesh.Trimesh(np.array(m.vert_properties[:, :3]), np.array(m.tri_verts), process=False)

body_w = body.transform(S2W)                                  # mundo: y para tras, z para cima
TO_PRINT_BODY = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0]], float)   # costas na mesa: (x, z, -y)
def center(m):
    bb = m.bounding_box(); return m.translate([-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, -bb[2]])
def halves(m):    # (esquerda X<=0, direita X>=0) vistas de frente
    return m.trim_by_plane([-1, 0, 0], 0.0), m.trim_by_plane([1, 0, 0], 0.0)
for d in (ROOT / 'stl').glob('*.stl'):
    d.unlink()
prints = {}
for side, mb in zip(['esquerda', 'direita'], halves(bezel)):
    prints[f'01-MOLDURA-{side}'] = center(mb.rotate([180, 0, 0]))            # frente na mesa
for side, mc in zip(['esquerdo', 'direito'], halves(body)):
    prints[f'02-CORPO-{side}'] = center(mc.transform(S2W).transform(TO_PRINT_BODY))
for side, ma in zip(['esquerda', 'direita'], halves(base)):
    prints[f'03-BASE-{side}'] = center(ma)                                   # deitada
# chaves: 3 do corpo + 2 reservas, 1 da moldura + 2 reservas, 2 da base + 2 reservas
kb = md.Manifold.extrude(md.CrossSection([KEY_BIG]), 3.0)
kz = md.Manifold.extrude(md.CrossSection([KEY_SMALL]), 1.5)
kbase = md.Manifold.extrude(md.CrossSection([KEY_BIG]), 2.0)
lot = [kb.translate([-30 + 30 * (i % 3), -22 + 16 * (i // 3), 0]) for i in range(5)]
lot += [kz.translate([-30 + 30 * i, 26, 0]) for i in range(3)]
lot += [kbase.translate([-30 + 30 * (i % 3), 44 + 16 * (i // 3), 0]) for i in range(4)]
prints['04-CHAVES-12un'] = center(U(lot))
# cupons de teste do encaixe (faixa com um gancho de bolso em cima e um de janela embaixo)
cx0, cx1 = 42.0, 68.0
cup_m = bezel ^ box(cx0, cx1, -200, 200, -40, 10)
cup_c = body ^ box(cx0, cx1, -200, 200, -25, 10)
cm = cup_m.rotate([180, 0, 0]); bb = cm.bounding_box(); cm = cm.translate([-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, -bb[2]])
cc = cup_c; bb = cc.bounding_box(); cc = cc.translate([-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, -bb[2]])
prints['00-TESTE-encaixe-moldura'] = cm
prints['00-TESTE-encaixe-corpo'] = cc
for name in prints:   # elimina arestas microscopicas que viram triangulos nulos ao gravar o STL em float32
    prints[name] = prints[name].simplify(0.002)
    mesh(prints[name]).export(ROOT / 'stl' / f'{name}.stl')
mesh(bezel).export(ROOT / 'verificacao' / 'montagem-moldura.stl')
mesh(body).export(ROOT / 'verificacao' / 'montagem-corpo.stl')
mesh(base_w.transform(W2S)).export(ROOT / 'verificacao' / 'montagem-base.stl')
keys_all = U(keys_body + [key_bezel] + [k.transform(W2S) for k in keys_base])
mesh(keys_all).export(ROOT / 'verificacao' / 'montagem-chaves.stl')

# ---------------------------------------------------------------- modelo da tela para verificacao
pcb_ref = json.loads((ROOT / 'referencia' / 'pcb-componentes-step.json').read_text())
def step_box(b):
    x0, y0, z0, x1, y1, z1 = b
    return box(PCB_X0 - x1, PCB_X0 - x0, PCB_Y0 + y0, PCB_Y0 + y1, -10.1 - z1, -10.1 - z0)
TG = 1.8
screen = [prism_z(rrect(-GX, GX, -GV, GV, GLASS_R, GLASS_R), -TG, 0),
          box(LCD['x0'], LCD['x1'], LCD['v0'], LCD['v1'], -STACK, -TG),
          step_box(pcb_ref['pcb'])] + [step_box(b) for b in pcb_ref['caixas_componentes']]
screen += [box(x - 4.5, x + 4.5, v - 3.5, v + 3.5, -8.6, -STACK) for x, v in M3]     # suportes M3 (altura estimada)
screen += [box(-18.5, 15.2, 25.7, LCD['v1'], -9.5, -STACK)]                           # FPCs dobrados (envelope)
screen = U(screen)
plugs = U([box(55.6, 125, vc - 6.25, vc + 6.25, USB_Z - 3.25, USB_Z + 3.25) for vc in USB_V])

mesh(screen).export(ROOT / 'verificacao' / 'tela-referencia.stl')
mesh(plugs).export(ROOT / 'verificacao' / 'plugues-usb-c.stl')

def inter(a, b): return max(0.0, (a ^ b).volume())
nubs_only = U([md.Manifold.cylinder(6.0, nub_r + 0.05, nub_r + 0.05, 32).rotate([90, 0, 0]).translate([xp, vp + 3.0, Z_NUB_TOP - nub_r]) for xp, vp, _ in PADS])
checks = {
    'moldura_x_corpo_mm3': inter(bezel, body),
    'tela_x_moldura_mm3': inter(screen, bezel),
    'tela_x_corpo_sem_ressaltos_mm3': inter(screen, body - nubs_only),
    'tela_x_ressaltos_mm3 (pre-carga intencional)': inter(screen, nubs_only),
    'plugue_usb_x_corpo_mm3': inter(plugs, body),
    'plugue_usb_x_moldura_mm3': inter(plugs, bezel),
}
# folga minima tela <-> corpo (sem ressaltos)
checks['folga_min_tela_corpo_mm'] = round((body - nubs_only).min_gap(screen, 5.0), 3)
checks['folga_min_tela_moldura_mm'] = round(bezel.min_gap(screen, 5.0), 3)
checks['cupons_teste_x_mm3'] = inter(cup_m, cup_c)
checks['chaves_x_pecas_e_tela_mm3'] = inter(keys_all, U([bezel, body, base_w.transform(W2S), screen]))
checks['arquivos'] = {}
for name, s in prints.items():
    m = trimesh.load(ROOT / 'stl' / f'{name}.stl')    # confere o arquivo gravado, nao so a geometria em memoria
    bb = s.bounding_box(); dims = [round(bb[3] - bb[0], 2), round(bb[4] - bb[1], 2), round(bb[5] - bb[2], 2)]
    checks['arquivos'][name] = dict(dimensoes_mm=dims, cabe_180=bool(max(dims) <= P['bed_max'] - 2),
                                    volume_cm3=round(s.volume() / 1000, 1), estanque=bool(m.is_watertight), triangulos_nulos=int((m.area_faces < 1e-9).sum()), pecas=len(s.decompose()))
# estabilidade: toque perpendicular ao vidro que levanta a frente (tomba para tras), com e sem a base
bw_m = mesh(body_w); vw = bw_m.vertices; zw_m = mesh(bezel.transform(S2W)); ba_m = mesh(base_w)
m_body, m_bezel, m_base = body.volume() / 1000 * 1.24 * 0.8, bezel.volume() / 1000 * 1.24 * 0.9, base_w.volume() / 1000 * 1.24 * 0.6
mass_screen = 230.0
com_screen = np.array(to_world(0, 0, -6))
g = 9.81e-3
def tip_force(with_base):
    ms = [(m_body, bw_m.center_mass), (m_bezel, zw_m.center_mass), (mass_screen, com_screen)]
    if with_base: ms.append((m_base, ba_m.center_mass))
    # pivo: pes de borracha traseiros da base (centro a 16 mm da borda) ou aresta traseira do corpo
    y_piv = float(Y_BACK + bk - 16) if with_base else float(vw[vw[:, 2] < Z_TABLE + 0.05][:, 1].max())
    z0 = Z_TABLE - (bt_ if with_base else 0)
    m_tot = sum(m for m, _ in ms); cg = sum(m * c for m, c in ms) / m_tot
    restoring = g * m_tot * (y_piv - cg[1])
    def at(V):   # forca perpendicular ao vidro no ponto (0, V) que inicia o tombamento
        _, yp, zp = to_world(0, V, 0)
        return round(restoring / (C_ * (zp - z0) - S_ * (y_piv - yp)), 1)
    return dict(massa_g=round(m_tot), cg_y=round(float(cg[1]), 1), pivo_y=round(y_piv, 1),
                N_topo_area_ativa=at(GV - 13.04), N_centro=at(0.0))
checks['estabilidade_sem_base'] = tip_force(False)
checks['estabilidade_com_base'] = tip_force(True)
checks['base_x_corpo_mm3'] = inter(base_w.transform(W2S), body)
checks['base_x_tela_mm3'] = inter(base_w.transform(W2S), screen)
info = dict(P, medidas_case=dict(largura=round(2 * OUT_X, 2), altura_frente=round(OUT_TOP - OUT_BOT, 2),
            altura_mesa=round(float(to_world(0, OUT_TOP, 0)[2] - Z_TABLE), 1),
            profundidade_base=round(Y_BACK - float(to_world(0, OUT_BOT, P['plate_t'])[1]), 1),
            espessura_topo_com_moldura=P['top_depth'] + P['plate_t']),
            molas=spring_info, verificacao=checks)
(ROOT / 'parametros.json').write_text(json.dumps(info, indent=2, ensure_ascii=False) + '\n')
print(json.dumps(checks, indent=1, ensure_ascii=False))
