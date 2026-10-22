"""Painel web · Login: e-mail + senha -> Visão geral."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

with WebSession(url='http://localhost:5179/dashboard/', port=9100) as s:
    s.hold(PACE.intro)
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.hold(0.4)
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.hold(0.5)
    s.click_text('Entrar', exact=True, wait=0.3)
    s.pause()  # esqueleto de carregamento fora de câmera
    while not s.cdp.js("document.body.innerText.includes('Bom dia') && document.body.innerText.includes('R$ 8.')"):
        s.hold(0.3)
    s.hold(1.0)
    s.resume()
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/01-login.mp4')
