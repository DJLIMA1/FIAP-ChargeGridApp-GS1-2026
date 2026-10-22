"""App (vendedor) · Operação ao vivo: posto -> carregadores GoodWe (status) -> potência ao vivo -> conector."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

SETUP = [["POST", "stations/@owned_station/demo-traffic", {}]]

with AppSession(port=9035, route='home', mode='vendor', setup=SETUP) as s:
    s.hold(PACE.intro)
    s.tap_text('Estações', exact=True, wait=1.5)
    s.tap_text('Marginal Pinheiros', wait=1.8)
    s.tap_text('Carregadores', wait=PACE.read)          # status online/offline de cada GoodWe
    s.tap_text('Voltar', exact=True, index=0, wait=1.8)
    s.tap_text('Potência', wait=PACE.read)              # potência ao vivo + carros agora
    s.tap_text('Carregador 1', wait=PACE.read)          # abre o conector: configurada x efetiva
    s.tap_text('Voltar', exact=True, index=0, wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/21-operacao-ao-vivo.mp4')
