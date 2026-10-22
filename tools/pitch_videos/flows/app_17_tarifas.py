"""App (vendedor) · Tarifas: Estações > posto > Tarifa > Tarifa base > novo preço > salvar."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402


def replace(s, x, y, text, erase=8):
    s.tap(x, y, wait=0.3)
    s.key('End', 'End', 35)
    for _ in range(erase):
        s.key('Backspace', 'Backspace', 8)
    s.type(text)
    s.hold(0.4)


with AppSession(port=9015, route='home', mode='vendor') as s:
    s.hold(PACE.intro)
    s.tap_text('Estações', exact=True, wait=2.2)
    s.tap_text('Marginal Pinheiros', wait=2.2)
    s.tap_text('Tarifa base, por', wait=2.5)
    s.hold(PACE.read)                      # preço atual
    s.tap_text('Tarifa base R$', wait=2.2)
    replace(s, 79, 329, '2,10')            # máxima DEMO-11
    replace(s, 79, 409, '1,68')            # reduzida DEMO-11
    s.shot('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/f_form.png')
    s.tap_text('Salvar tarifa base', wait=2.5)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.shot('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/f_end.png')
    s.render('output/pitch-videos/app/17-tarifas.mp4')
