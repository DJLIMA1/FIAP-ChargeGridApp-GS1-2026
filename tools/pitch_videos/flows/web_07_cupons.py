"""Painel web · Cupons: Visão geral -> Cupons -> Novo cupom (PITCH10, 10%) -> salvo na lista."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

with WebSession(url='http://localhost:5179/dashboard/', port=9160) as s:
    s.pause()  # login + esqueletos fora de câmera
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.5)
    while not s.cdp.js("document.body.innerText.includes('Bom dia') && document.body.innerText.includes('R$ 8.')"):
        s.hold(0.3)
    s.hold(1.5)
    s.navigated()
    s.cdp.frames.clear()
    s.resume()
    s.move(900, 400, 0.3)
    s.hold(PACE.intro)
    s.click_text('Cupons', exact=True, wait=0.3)
    while not s.cdp.js("document.body.innerText.includes('VERAO10')"):
        s.hold(0.1)
    s.hold(PACE.read)
    s.click_text('Novo cupom', exact=True, wait=PACE.after_tap)
    s.click_css('input.input-big')
    s.type('PITCH10')
    s.hold(0.4)
    s.click_css('textarea')
    s.type('10% de desconto em recargas')
    s.hold(0.6)
    s.click_text('Criar cupom', exact=True, wait=0.5)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/07-cupons.mp4')
