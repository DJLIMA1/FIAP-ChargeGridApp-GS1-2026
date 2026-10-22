"""Painel web · Visão geral: KPIs, gráficos com tooltip, período, rolagem até o ranking."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

SCRATCH = Path(__file__).resolve().parents[3] / 'tmp' / 'w02'

with WebSession(url='http://localhost:5181/dashboard/', port=9110) as s:
    # Login fora de câmera
    s.pause()
    for _ in range(4):
        s.hold(1.0)
        s.type_into('input[type="email"]', 'joao@postosilva.com.br')
        s.type_into('input[type="password"]', 'chargegrid2026')
        s.click_text('Entrar', exact=True, wait=0.5)
        s.hold(2.5)
        if 'Bom dia' in (s.cdp.js('document.body.innerText') or '') or 'Boa ' in (s.cdp.js('document.body.innerText') or ''):
            break
    s.hold(3.0)
    s.cdp.js('window.scrollTo(0,0)')
    s.navigated()
    s.shot(SCRATCH / 'w02-a.png')
    s.resume(clear=True)
    s.hold(PACE.intro)
    # KPIs: cursor passeia pelos cartões
    s.move(420, 250); s.hold(0.5)
    s.move(930, 250); s.hold(0.4)
    s.move(1290, 250); s.hold(0.4)
    # período: 30 dias
    s.click_text('30 dias', exact=True, wait=PACE.read)
    s.scroll(420, x=900, y=500)
    s.hold(0.4)
    s.move(380, 232, 0.5); s.move(520, 232, 0.5); s.hold(0.9)
    s.move(1100, 225, 0.8); s.hold(0.8)
    s.move(1260, 300, 0.6); s.hold(0.8)
    s.shot(SCRATCH / 'w02-d.png')
    s.scroll(560, x=900, y=500, seconds=0.9)
    s.hold(1.2)
    s.shot(SCRATCH / 'w02-e.png')
    s.scroll(900, x=900, y=500, seconds=1.2)
    s.shot(SCRATCH / 'w02-f.png')
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/02-visao-geral.mp4')
