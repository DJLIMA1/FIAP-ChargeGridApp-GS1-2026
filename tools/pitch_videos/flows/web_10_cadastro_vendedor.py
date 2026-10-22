"""Painel web · Criar conta de vendedor: login -> cadastro -> aguardando habilitação."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

with WebSession(url='http://localhost:5181/dashboard/', port=9190) as s:
    s.hold(PACE.intro)
    s.click_text('Criar conta de vendedor', wait=0.6)
    s.hold(0.8)
    s.type_into('input[autocomplete="name"]', 'Carlos Lima')
    s.hold(0.3)
    s.type_into('input[type="email"]', 'carlos@eletroposto.com.br')
    s.hold(0.3)
    s.type_into('input[autocomplete="new-password"]', 'chargegrid2026')
    s.hold(0.3)
    s.hold(0.1)
    s.click_css('input[placeholder="Repita a senha"]', wait=0.25)
    s.type('chargegrid2026')
    s.hold(0.6)
    s.click_css('button[type="submit"]', wait=0.3)
    s.pause()
    while not s.cdp.js("!location.pathname.includes('criar-conta') && document.body.innerText.length > 100"):
        s.hold(0.3)
    s.hold(1.0)
    s.resume()
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/10-criar-conta-vendedor.mp4')
