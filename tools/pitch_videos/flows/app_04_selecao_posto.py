"""App · Seleção de posto: lista/mapa -> Villa Lobos -> detalhe -> Reservar -> escolhe o conector (pronto p/ continuar)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402


def tap_settle(s, text, load=4.0, read=PACE.read, **kw):
    """Toque real; os tiles do mapa carregam fora de câmera (pause/resume) para nunca gravar 'carregando'."""
    s.tap_text(text, wait=0.35, **kw)
    s.pause()
    time.sleep(load)
    s.resume()
    s.hold(read)


with AppSession(port=8950, route='home') as s:
    s.hold(PACE.intro)
    tap_settle(s, 'Recarga', load=5, read=PACE.after_tap, exact=True)
    s.hold(PACE.read - PACE.after_tap)
    tap_settle(s, 'Villa Lobos Pinheiros - São Paulo', load=5)
    tap_settle(s, 'Ver estação', load=5, exact=True)
    s.tap_text('Reservar estação', exact=True, wait=PACE.after_tap)
    s.tap_text('CCS2 - 60 kW', wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/04-selecao-de-posto.mp4')
