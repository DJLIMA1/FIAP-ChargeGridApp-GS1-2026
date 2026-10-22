"""App (vendedor) · Dados do posto: nome/endereço -> conector, potência, tarifa -> revisão -> publicar -> posto criado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

DEBUG = Path('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/a15')
DEBUG.mkdir(parents=True, exist_ok=True)

with AppSession(port=9005, route='operator', mode='vendor', params={'claim': True}) as s:
    # Fora de câmera: vincular o ponto (outro vídeo).
    s.pause()
    s.tap_text('Adicionar central simulada', wait=2.5)
    s.shot(DEBUG / 'step1.png')
    s.resume()
    s.hold(PACE.intro)
    s.tap_text('Ex.: Posto Centro', wait=0.3)
    s.type('Posto Paulista 1000')
    s.hold(0.4)
    s.tap_text('Rua, número, bairro', wait=0.3)
    s.type('Av. Paulista, 1000')
    s.hold(1.8)
    s.shot(DEBUG / 'addr.png')
    print([l['label'] for l in s.labels()])
    s.hold(PACE.outro)
    s.render(str(DEBUG / 'tmp.mp4'))
