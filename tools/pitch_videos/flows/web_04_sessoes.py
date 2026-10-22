"""Painel web · Sessões: visão geral -> Sessões -> busca/filtro -> detalhe -> exportação."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402


def wait(s, expr):
    while not s.cdp.js(expr):
        s.hold(0.3)


with WebSession(url='http://localhost:5181/dashboard/', port=9130) as s:
    s.pause()  # login fora de câmera
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.3)
    wait(s, "document.body.innerText.includes('Receita bruta') && document.body.innerText.includes('R$ 8.')")
    s.hold(1.0)
    s.resume(clear=True)
    s.hold(PACE.intro)
    s.click_text('Sessões', exact=True, wait=0.05)
    s.pause()
    wait(s, "!!document.querySelector('table.table tbody tr')")
    s.hold(0.8)
    s.resume()
    s.hold(PACE.read)
    # filtro por status
    s.click_css('.chips .chip', index=0, wait=0.3)
    s.pause()
    s.hold(1.0)
    wait(s, "!!document.querySelector('table.table tbody tr') || document.body.innerText.includes('Nenhuma sessão')")
    s.resume()
    s.hold(PACE.read)
    s.click_text('Limpar', exact=True, wait=0.5)
    s.hold(PACE.after_tap)
    # abrir detalhe
    s.click_css('table.table tbody tr', index=1, wait=0.3)
    s.hold(PACE.read + 1.0)
    s.cdp.js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
    s.hold(PACE.after_tap)
    # exportação
    s.click_text('CSV', exact=False, wait=0.3)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/web/04-sessoes.mp4')
