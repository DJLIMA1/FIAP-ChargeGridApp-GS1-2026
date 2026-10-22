"""App · Busca de postos: Início -> aba Recarga -> mapa/lista -> busca "Pinheiros" -> filtros -> resultados."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402


def wait_map(s, seconds):
    s.pause()
    time.sleep(seconds)
    s.resume()


def tap(s, text, wait=0.8):
    s.tap_text(text, exact=True, wait=wait)


with AppSession(port=8945, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    tap(s, 'Recarga', 0.4)
    wait_map(s, 7)
    s.hold(PACE.read)
    s.tap(190, 45, wait=0)
    for _ in range(40):      # o foco do campo demora com a máquina carregada
        if s.cdp.js("document.activeElement.tagName") == 'INPUT':
            break
        time.sleep(0.15)
    s.type('Pinheiros')
    got = s.cdp.js("document.activeElement.value")
    assert got == 'Pinheiros', f'campo ficou com {got!r}'
    s.hold(0.5)
    s.key('Enter', 'Enter', 13)
    wait_map(s, 5)
    s.hold(1.0)
    tap(s, 'Filtros', 0.3)
    wait_map(s, 2)
    tap(s, 'Tipo 2', 0.9)
    tap(s, 'Menor tarifa', 0.9)
    tap(s, 'Aplicar filtros', 0.4)
    s._mouse('mouseMoved', 200, 330)  # tira o tooltip do menu inferior
    wait_map(s, 6)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/03-busca-de-postos.mp4')
