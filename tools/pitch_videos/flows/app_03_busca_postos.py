"""App · Busca de postos: Início -> aba Recarga -> mapa/lista -> busca "Pinheiros" -> filtros -> resultados."""
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402


def grab(s):
    """Força um quadro real agora (o screencast fica esparso quando a máquina está carregada)."""
    shot = s.cdp.call('Page.captureScreenshot', format='jpeg', quality=95)['data']
    if s.cdp.recording:
        s.cdp.frames.append((time.time() - s.cdp.offset, base64.b64decode(shot)))


def hold(s, seconds):
    """Espera `seconds` forçando alguns quadros reais (máquina carregada deixa o screencast esparso)."""
    end = time.time() + seconds
    while True:
        grab(s)
        left = end - time.time()
        if left <= 0:
            break
        time.sleep(min(0.5, left))


def wait_map(s, seconds):
    s.pause()
    time.sleep(seconds)
    s.resume()


def tap(s, text, wait=0.8):
    s.tap_text(text, exact=True, wait=0)
    hold(s, wait)


with AppSession(port=8945, route='home', mode='consumer') as s:
    hold(s, PACE.intro)
    tap(s, 'Recarga', 0.4)
    wait_map(s, 7)
    hold(s, PACE.read)
    s.tap(190, 45, wait=0)   # sem grab() até digitar: capturar quadro tira o foco do campo
    for _ in range(40):      # o foco do campo demora com a máquina carregada
        if s.cdp.js("document.activeElement.tagName") == 'INPUT':
            break
        time.sleep(0.15)
    s.type('Pinheiros')
    hold(s, 0.5)
    s.key('Enter', 'Enter', 13)
    wait_map(s, 5)
    hold(s, PACE.read)
    tap(s, 'Filtros', 1.2)
    tap(s, 'Tipo 2', 0.9)
    tap(s, 'Menor tarifa', 0.9)
    tap(s, 'Aplicar filtros', 0.4)
    wait_map(s, 6)
    s._mouse('mouseMoved', 200, 330)  # tira o tooltip do menu inferior
    hold(s, PACE.read)
    hold(s, PACE.outro)
    s.render('output/pitch-videos/app/03-busca-de-postos.mp4')
