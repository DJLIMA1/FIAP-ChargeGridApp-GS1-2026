"""App · Busca de postos: Início -> aba Recarga -> mapa/lista -> busca "Pinheiros" -> filtros -> resultados."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8945, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Recarga', exact=True, index=0, wait=PACE.read)
    s.tap(190, 45, wait=0.5)
    s.type('Pinheiros')
    s.hold(0.4)
    s.shot('/private/tmp/claude-501/s03/t.png')
    s.key('Enter')
    s.hold(2.5)
    s.shot('/private/tmp/claude-501/s03/b.png')
    s.tap_text('Filtros', exact=True, wait=1.5)
    s.shot('/private/tmp/claude-501/s03/c.png')
    s.render('/private/tmp/claude-501/s03/draft.mp4')
