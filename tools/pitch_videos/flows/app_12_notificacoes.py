"""App · Notificações: Início -> sino -> central -> abre uma notificação (marca como lida)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8990, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Notificações', exact=True, wait=PACE.read)
    s.tap_text('Meta de bateria atingida', wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/12-notificacoes.mp4')
