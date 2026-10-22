"""App · Cupons (vendedor, único acesso real): Estações > Gerenciar cupons > Criar cupom > lista."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402
with AppSession(port=8980, route='home', mode='vendor') as s:
    s.hold(PACE.intro)
    s.tap_text('Estações', exact=True, wait=1.0)
    s.scroll(900)
    s.hold(0.5)
    s.tap_text('Gerenciar cupons', wait=PACE.read)
    s.tap_text('Criar cupom', exact=True, wait=1.0)
    s.tap_text('Código', exact=True, wait=0.9)
    s.type('VERAO15')
    s.hold(0.4)
    s.tap_text('Descrição', exact=True, wait=0.9)
    s.type('15% na recarga de verão')
    s.hold(0.4)
    s.tap_text('Desconto %', exact=True, wait=0.9)
    s.key('Backspace', 'Backspace', 8)
    s.key('Backspace', 'Backspace', 8)
    s.type('15')
    s.hold(0.4)
    s.shot('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/e1.png')
    s.tap_text('Salvar cupom', exact=True, wait=PACE.read)
    s.shot('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/e2.png')
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/10-cupons.mp4')
