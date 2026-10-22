"""Painel web · Alertas: visão geral -> Alertas -> filtro por severidade -> abrir estação do alerta."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402


def wait(s, expr):
    while not s.cdp.js(expr):
        s.hold(0.3)


with WebSession(url='http://localhost:5179/dashboard/', port=9140) as s:
    s.pause()  # login fora de câmera
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.3)
    wait(s, "document.body.innerText.includes('Bom dia') && document.body.innerText.includes('R$ 8.')")
    s.hold(1.0)
    s.resume()
    s.hold(PACE.intro)
    s.click_text('Alertas', exact=True, wait=0.3)
    s.pause()
    wait(s, "!!document.querySelector('.chips .chip') && !document.querySelector('.skeleton') && document.body.innerText.includes('Alertas operacionais')")
    s.hold(0.8)
    s.resume()
    s.hold(PACE.read)
    s.click_css('.chips .chip', index=1, wait=0.3)  # Crítico
    s.hold(PACE.read)
    s.click_css('.chips .chip', index=2, wait=0.3)  # Atenção
    s.hold(PACE.read)
    s.click_css('.chips .chip', index=0, wait=0.3)  # Todos
    s.hold(PACE.after_tap)
    s.click_css('a[title="Abrir estação"]', index=0, wait=0.3)
    s.pause()
    s.hold(1.0)
    s.resume()
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/05-alertas.mp4')
