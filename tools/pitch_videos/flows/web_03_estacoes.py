"""Painel web · Estações: menu Estações -> lista -> detalhe (dados, conectores GoodWe, comodidades)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, WebSession  # noqa: E402

with WebSession(url='http://localhost:5181/dashboard/', port=9120) as s:
    # Login fora de câmera; começa na visão geral
    s.pause()
    s.type_into('input[type="email"]', 'joao@postosilva.com.br')
    s.type_into('input[type="password"]', 'chargegrid2026')
    s.click_text('Entrar', exact=True, wait=0.5)
    s.hold(3.0)
    s.cdp.js('window.scrollTo(0,0)')
    s.navigated()
    s.resume(clear=True)
    s.hold(PACE.intro + 0.6)
    s.click_text('Estações', exact=True, index=0, wait=PACE.read + 0.5)
    # abre o detalhe: o clique aparece em câmera, o "Carregando estação..." fica fora
    x, y = s.find('Marginal Pinheiros', exact=True)
    s.move(x, y)
    s.cdp.js(f'window.__cg.click({x},{y})')
    s.hold(0.3)
    s.pause()
    s._mouse('mousePressed', x, y, clickCount=1)
    s._mouse('mouseReleased', x, y, clickCount=1)
    s.hold(0.8)
    while s.cdp.js("document.body.innerText.includes('Carregando estação')"):
        s.hold(0.3)
    s.hold(1.0)
    s.resume()
    s.hold(PACE.read)
    s.scroll(520, x=1000, y=500)
    s.hold(PACE.read)
    # rola até a seção Potência (refeita): disponível, régua de limites, margem estimada da loja
    s.pause()
    for _ in range(100):
        if s.cdp.js("(([...document.querySelectorAll('section.card')].find(c => /^Potência/.test(c.innerText.trim())))||{innerText:''}).innerText.includes('Limite')"):
            break
        s.hold(0.3)
    s.hold(1.5)
    s.resume()
    top = s.cdp.js("Math.round([...document.querySelectorAll('section.card')].find(c => /^Potência/.test(c.innerText.trim())).getBoundingClientRect().top)")
    s.scroll(max(top - 90, 0), x=1000, y=500, steps=24, seconds=1.0)
    s.hold(PACE.read + 1.5)
    s.scroll(500, x=1000, y=500)
    s.hold(PACE.read + PACE.outro)
    s.render('output/pitch-videos/web/03-estacoes-e-detalhe.mp4')
