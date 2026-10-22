"""Totem · Pagar e iniciar: autoatendimento sem app (valor, potência, cartão, revisão, pagamento) -> recarga em andamento."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE  # noqa: E402
from totem import Step, build  # noqa: E402

F = 'tmp/pitch-totem-frames/kiosk-{}.ppm'.format
build([
    Step(F('ready'), hold=PACE.intro, tap=(234, 292)),            # Iniciar autoatendimento
    Step(F('welcome'), tap=(584, 258)),                           # Continuar sem login
    Step(F('connector'), tap=(642, 420)),                         # Próximo passo
    Step(F('choose'), tap=(584, 188)),                            # Por valor
    Step(F('amount'), tap=(670, 213)),                            # R$ 20,00
    Step(F('power'), tap=(584, 190)),                             # Máxima
    Step(F('payment-method'), tap=(584, 258)),                    # Cartão
    Step(F('review'), hold=PACE.read, tap=(642, 420)),            # Aceitar e pagar
    Step(F('pay-simulated'), tap=(642, 422)),                     # Já efetuei o pagamento
    Step(F('starting'), hold=PACE.after_tap),
    Step(F('live'), hold=PACE.read),
], 'output/pitch-videos/totem/01-pagar-e-iniciar.mp4')
