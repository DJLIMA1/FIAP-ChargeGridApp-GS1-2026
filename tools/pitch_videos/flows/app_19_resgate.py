"""App (vendedor) · Resgate de dinheiro: Início -> saldo -> modalidade -> confirmação -> resultado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=9025, route='home', mode='vendor') as s:
    s.hold(PACE.intro)
    if '--labels' in sys.argv:
        for l in s.labels():
            print(l)
        s.shot('/tmp/x.png')
    s.tap_text('SALDO A RECEBER', wait=PACE.read)
    s.tap_text('Resgatar saldo', exact=True, wait=PACE.read)
    s.tap_text('Receber agora', wait=PACE.read)
    s.tap_text('Confirmar resgate', wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/19-resgate-de-dinheiro.mp4')
