"""App · Login: e-mail + senha da conta demo -> Início."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8931) as s:
    s.hold(PACE.intro)
    s.tap_text('voce@email.com', wait=0.3)
    s.type('demo@chargegrid.example')
    s.hold(0.4)
    s.tap_text('••••••••', wait=0.3)
    s.type('demo1234')
    s.hold(0.5)
    s.tap_text('Entrar', exact=True, wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/01-login.mp4')
