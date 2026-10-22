"""App (vendedor) · Exportar informações: Histórico -> Resultado -> período -> CSV -> confirmação."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=9030, route='history', mode='vendor', params={'manage': True}) as s:
    s.hold(PACE.intro)
    s.tap_text('Resultado do período', wait=PACE.read)
    s.tap_text('Escolher período', wait=0.8)
    s.tap_text('Últimos 30 dias', exact=True, wait=PACE.read)
    s.scroll(500, x=200, y=500)
    s.hold(0.5)
    s.scroll(900, x=200, y=500)
    s.hold(0.5)
    s.scroll(900, x=200, y=500)
    s.hold(0.5)
    s.scroll(900, x=200, y=500)
    s.hold(0.8)
    s.tap_text('CSV', exact=True, wait=0.3)
    s.hold(PACE.read)
    s.render('output/pitch-videos/app/20-exportar-informacoes.mp4')
