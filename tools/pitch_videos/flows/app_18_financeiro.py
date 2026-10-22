"""App (vendedor) · Histórico financeiro: receita, sessões, resultado do período, gráfico, recargas -> detalhe financeiro."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

SETUP = [["POST", "stations/@owned_station/demo-traffic", {}]]

with AppSession(port=9020, route='home', mode='vendor', setup=SETUP) as s:
    s.hold(PACE.intro)
    s.tap_text('Histórico', exact=True, wait=PACE.read)       # receita, recargas, ticket médio
    s.scroll(560, x=200, y=500)                                # resultado do período + seletor
    s.hold(PACE.read)
    s.scroll(700, x=200, y=500)                                # gráfico de energia
    s.hold(PACE.read)
    s.scroll(900, x=200, y=500)                                # recargas recentes
    s.hold(PACE.read)
    s.scroll(-2600, x=200, y=500, seconds=0.8)                 # volta ao topo
    s.scroll(420, x=200, y=500)
    s.hold(0.4)
    card = next(l for l in s.labels() if l['role'] == 'button' and l['label'].startswith('Resultado do período'))
    s.tap(card['x'] + card['w'] / 2, card['y'] + 60, wait=PACE.read)   # detalhe financeiro (cascata)
    s.scroll(400, x=200, y=500)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/18-historico-financeiro.mp4')
