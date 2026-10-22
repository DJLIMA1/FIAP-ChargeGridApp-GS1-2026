"""Painel web · Resultado financeiro: receita -> margem, troca de período, exportação CSV."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402


def wait(s, expr):
    while not s.cdp.js(expr):
        s.hold(0.3)


with WebSession(url='http://localhost:5179/dashboard/', port=9150) as s:
    s.pause()  # login fora de câmera
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.3)
    wait(s, "document.body.innerText.includes('Bom dia') && document.body.innerText.includes('R$ 8.')")
    s.hold(1.0)
    s.resume()
    s.hold(PACE.intro)
    s.click_text('Resultado', exact=True, wait=0.3)
    s.pause()
    wait(s, "document.body.innerText.includes('Da receita à margem') && document.body.innerText.includes('Receita bruta')")
    s.hold(0.8)
    s.resume()
    s.hold(PACE.read)
    s.scroll(560, x=1100, y=600)
    s.hold(PACE.read)
    s.scroll(-1200, x=1100, y=600, seconds=0.5)
    s.hold(0.4)
    # troca de período
    s.click_text('30 dias', exact=True, wait=0.3)
    s.pause()
    s.hold(1.0)
    wait(s, "document.body.innerText.includes('Últimos 30 dias') && document.body.innerText.includes('Da receita à margem')")
    s.resume()
    s.hold(PACE.read)
    s.scroll(560, x=1100, y=600)
    s.hold(PACE.read)
    s.scroll(-1200, x=1100, y=600, seconds=0.5)
    s.hold(0.4)
    # exportação
    s.click_text('CSV', exact=False, wait=0.3)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/06-resultado-financeiro.mp4')
