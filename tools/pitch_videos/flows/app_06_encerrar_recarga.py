"""App · Encerrar recarga: recarga ao vivo -> Encerrar -> resumo/recibo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

START = ['POST', 'charging-sessions', {'public_code': 'DEMO-2', 'presence_code': '#F12345',
                                        'max_duration_minutes': 30, 'soc_percent': 30, 'battery_kwh': 60}]
SCR = '/private/tmp/claude-501/s6'

with AppSession(port=8960, route='charging', setup=[START]) as s:
    s.pause()
    s.hold(6)  # fora de câmera: recarga evolui (kWh/valor > 0)
    s.shot(f'{SCR}/live.png')
    print([l['label'] for l in s.labels() if l['role'] == 'button'])
    s.resume()
    s.hold(PACE.intro + 0.8)
    s.tap_text('Encerrar recarga', exact=True, wait=PACE.after_tap)
    s.hold(PACE.after_tap + 0.5)  # "Encerrando..." -> "Recarga concluída"
    s.hold(PACE.read)
    s.tap_text('Ver recibo', exact=True, wait=PACE.after_tap)
    s.shot(f'{SCR}/receipt.png')
    s.hold(PACE.read + 1)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/06-encerrar-recarga-e-recibo.mp4')
