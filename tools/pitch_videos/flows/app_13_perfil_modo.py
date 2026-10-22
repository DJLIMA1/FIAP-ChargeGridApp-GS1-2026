"""App · Conta: perfil/veículo do motorista -> alternar para operador -> Início do vendedor."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8995, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    s.hold(PACE.read)                      # Início do motorista: carro do perfil no anel
    s.tap_text('Conta', exact=True, index=1, wait=PACE.read)
    s.hold(PACE.read)
    s.tap_text('Usar como operador', wait=PACE.read)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/13-perfil-e-modo-vendedor.mp4')
