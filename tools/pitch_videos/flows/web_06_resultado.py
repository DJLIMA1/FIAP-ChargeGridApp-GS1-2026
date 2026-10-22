"""Painel web · Resultado financeiro: receita -> margem, troca de período, exportação CSV."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402


def wait(s, expr):
    while not s.cdp.js(expr):
        s.hold(0.3)


def hold(s, seconds):
    s.hold(seconds)


with WebSession(url='http://localhost:5181/dashboard/', port=9150) as s:
    s.pause()  # login fora de câmera
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.3)
    wait(s, "!!document.querySelector('.brand-sub') && !document.querySelector('.skeleton')")
    s.hold(1.5)
    s.navigated()
    s.resume(clear=True)
    hold(s, PACE.intro)
    s.click_text('Resultado', exact=True, wait=0.1)
    s.pause()
    wait(s, "document.body.innerText.includes('Da receita à margem') && document.body.innerText.includes('Receita bruta') && !document.querySelector('.skeleton')")
    s.hold(1.5)
    s.resume()
    hold(s, PACE.read)
    s.scroll(560, x=1100, y=600)
    hold(s, PACE.read)
    s.scroll(-1200, x=1100, y=600, seconds=0.5)
    hold(s, 0.4)
    # troca de período
    s.click_text('30 dias', exact=True, wait=0.1)
    s.pause()
    s.hold(1.0)
    wait(s, "document.body.innerText.includes('Da receita à margem') && !document.querySelector('.skeleton')")
    s.hold(1.0)
    s.resume()
    hold(s, PACE.read)
    s.scroll(-1200, x=1100, y=600, seconds=0.3)
    # exportação
    s.click_text('CSV', exact=True, wait=0.3)
    hold(s, PACE.read)
    hold(s, PACE.outro)
    s.render('output/pitch-videos/web/06-resultado-financeiro.mp4')
