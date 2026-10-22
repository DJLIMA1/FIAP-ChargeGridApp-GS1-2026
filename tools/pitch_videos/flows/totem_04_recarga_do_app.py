"""Totem · Recarga do app: uma recarga iniciada pelo app aparece no totem, acompanha e encerra, com recibo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE  # noqa: E402
from totem import Step, build  # noqa: E402

F = 'tmp/pitch-totem-frames/kiosk-{}.ppm'.format
build([
    Step(F('notice-app-started'), hold=PACE.intro + PACE.read, tap=(584, 420)),   # Concluir
    Step(F('shared-app-live'), hold=PACE.read, tap=(594, 298)),                   # Encerrar
    Step(F('confirm-app-stop'), hold=PACE.read, tap=(594, 296)),                  # Sim, encerrar
    Step(F('shared-app-receipt'), hold=PACE.read),
], 'output/pitch-videos/totem/04-recarga-do-app-no-totem.mp4')
