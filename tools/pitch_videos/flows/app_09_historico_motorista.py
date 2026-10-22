"""App · Histórico do motorista: lista de recargas -> rolar -> Ver recibo -> recibo detalhado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8975, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Histórico', exact=True, wait=PACE.read)
    s.scroll(260, y=500)
    s.hold(PACE.after_tap)
    s.scroll(-260, y=500)
    s.hold(0.6)
    s.tap_text('Ver recibo', index=0, wait=PACE.read)
    s.scroll(500, y=500, seconds=0.9)
    s.hold(PACE.read)
    s.scroll(500, y=500, seconds=0.9)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/09-historico-e-recibo.mp4')
