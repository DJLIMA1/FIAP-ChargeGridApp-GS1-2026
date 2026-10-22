"""Totem · Encerrar e recibo: recarga em andamento -> encerrar -> confirmar -> recibo com QR -> volta para Pronto."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE  # noqa: E402
from totem import Step, build  # noqa: E402

F = 'tmp/pitch-totem-frames/kiosk-{}.ppm'.format
build([
    Step(F('live'), hold=PACE.intro, tap=(594, 220)),             # Encerrar
    Step(F('confirm-stop'), hold=PACE.read, tap=(594, 296)),      # Sim, encerrar
    Step(F('receipt'), hold=PACE.read, tap=(584, 420)),           # Concluir
    Step(F('back-to-ready'), hold=PACE.read),
], 'output/pitch-videos/totem/02-encerrar-e-recibo.mp4')
