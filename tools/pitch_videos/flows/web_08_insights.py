"""Painel web · Insights: Visão geral -> Insights -> Gerar insights -> resumo e recomendações."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

SCRATCH = Path('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad')

with WebSession(url='http://localhost:5179/dashboard/', port=9170) as s:
    s.pause()
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.5)
    while not s.cdp.js("document.body.innerText.includes('Bom dia') && document.body.innerText.includes('R$ 8.')"):
        s.hold(0.3)
    s.hold(1.5)
    s.cdp.js('window.scrollTo(0,0)')
    s.cdp.frames.clear()
    s.resume()
    s.hold(PACE.intro)
    s.move(700, 300); s.hold(0.6)
    s.click_text('Insights', exact=False, wait=PACE.read)
    s.shot(SCRATCH / 'w08-a.png')
    s.click_text('Gerar insights', exact=False, wait=0.3)
    s.pause()
    while not s.cdp.js("document.body.innerText.includes('Recomendações')"):
        s.hold(0.3)
    s.hold(0.8)
    s.cdp.js('window.scrollTo(0,0)')
    s.resume()
    s.hold(PACE.read)
    s.shot(SCRATCH / 'w08-b.png')
    s.scroll(380, x=900, y=500, seconds=0.9)
    s.hold(0.5)
    s.move(700, 380, 0.6); s.hold(0.9)
    s.move(700, 560, 0.6); s.hold(0.9)
    s.shot(SCRATCH / 'w08-c.png')
    s.scroll(500, x=900, y=500, seconds=0.9)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/08-insights.mp4')
