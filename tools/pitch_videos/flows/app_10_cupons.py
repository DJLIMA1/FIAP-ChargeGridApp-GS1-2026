"""App · Cupons (vendedor): Estações > Gerenciar cupons > filtros/uso > Criar cupom (VERAO15, 15%) > lista."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8980, route='home', mode='vendor') as s:
    s.hold(PACE.intro)
    s.tap_text('Estações', exact=True, wait=1.0)
    s.tap_text('Gerenciar cupons', wait=PACE.read)
    s.tap_text('Ativos', exact=True, index=1, wait=1.2)
    s.tap_text('Todos', exact=True, wait=0.8)
    s.tap_text('Criar cupom', exact=True, wait=1.0)
    s.tap_text('Ex.: VERAO15', wait=0.9)
    s.type('VERAO15')
    s.hold(0.4)
    s.tap_text('Ex.: 10% na primeira recarga', wait=0.9)
    s.type('15% na recarga de verão')
    s.hold(0.4)
    s.tap_text('15%', exact=True, wait=0.8)
    s.hold(0.6)
    s.scroll(600)
    s.hold(0.4)
    s.tap_text('Salvar cupom', exact=True, wait=1.0)
    s.scroll(500)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/10-cupons.mp4')
