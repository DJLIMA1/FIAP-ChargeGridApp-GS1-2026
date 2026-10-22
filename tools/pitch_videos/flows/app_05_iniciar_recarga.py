"""App · Iniciar recarga: conector -> quanto (valor) -> potência -> pagamento (saldo) -> revisar -> recarga ao vivo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

DEBUG = '--debug' in sys.argv
S = '/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad'

with AppSession(port=8955, route='booking', mode='consumer',
                params={'station_id': '@first_station', 'kind': 'now'}) as s:
    def dbg(name):
        if DEBUG:
            s.shot(f'{S}/{name}.png')
            print(name, [(l['label'][:30], int(l['x']), int(l['y'])) for l in s.labels()], flush=True)

    s.hold(PACE.intro)
    s.tap_text('CCS2 - 60 kW', wait=0.6)            # conector
    s.tap_text('Continuar', exact=True)
    dbg('p3')
    s.tap_text('Por valor', wait=0.6)
    dbg('p3b')
    s.tap_text('Exemplo', wait=0.3)
    s.type('50')
    s.hold(0.5)
    s.tap_text('Próximo Passo', wait=PACE.after_tap)
    dbg('p4')
    s.tap_text('Continuar', exact=True)
    dbg('p5')
    s.tap_text('Continuar', exact=True)
    dbg('p6')
    s.hold(PACE.read)
    s.tap_text('Confirmar e iniciar', wait=PACE.after_tap)
    dbg('p7')
    s.tap_text('Continuar', exact=True, wait=1.5)
    dbg('p8')
    s.hold(PACE.read)
    s.tap_text('Solicitar início', wait=2.0)
    dbg('p9')
    s.hold(4)
    dbg('p10')
    s.hold(PACE.outro)
    if not DEBUG:
        s.render('output/pitch-videos/app/05-iniciar-recarga.mp4')
