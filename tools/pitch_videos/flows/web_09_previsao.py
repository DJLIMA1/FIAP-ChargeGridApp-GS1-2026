"""Painel web · Previsão: menu Previsão -> ocupação prevista (hover) -> acerto/sugestões -> histórico (Energia, 8 sem.)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

with WebSession(url='http://localhost:5179/dashboard/', port=9180) as s:
    s.pause()
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.5)
    while not s.cdp.js("document.body.innerText.includes('Bom dia') && document.body.innerText.includes('R$ 8.')"):
        s.hold(0.3)
    s.hold(1.0)
    s.cdp.js('window.scrollTo(0,0)')
    s.navigated()
    s.cdp.frames.clear()
    s.resume()
    s.hold(PACE.intro + 0.4)
    s.click_text('Previsão', exact=True, index=0, wait=0.2)
    s.pause()
    while not s.cdp.js("!!document.querySelector('.recharts-bar-rectangle') && document.body.innerText.includes('Sugestões')"):
        s.hold(0.3)
    s.hold(0.8)
    s.cdp.js('window.scrollTo(0,0)')
    s.cdp.frames.clear()
    s.resume()
    s.hold(PACE.read)
    # hover nas barras do gráfico
    box = s.cdp.js("(() => { const r = document.querySelector('.chart-box').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
    l, t, w, h = box
    for fx in (0.25, 0.5, 0.68):
        s.move(l + w * fx, t + h * 0.55, seconds=0.7)
        s.hold(1.3)
    s.scroll(560, x=1000, y=500)
    s.hold(PACE.read)
    s.scroll(560, x=1000, y=500)
    s.hold(PACE.read)
    s.click_text('Energia', exact=True, wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/09-previsao.mp4')
