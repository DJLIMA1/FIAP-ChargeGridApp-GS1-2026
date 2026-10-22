"""Totem · Conta e saldo: entrar com a conta ChargeGrid, autonomia e pagamento com saldo do app -> revisão."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE  # noqa: E402
from totem import Step, build  # noqa: E402

F = 'tmp/pitch-totem-frames/kiosk-{}.ppm'.format
build([
    Step(F('ready'), hold=PACE.intro, tap=(234, 292)),            # Iniciar autoatendimento
    Step(F('welcome'), tap=(584, 188)),                           # Entrar na minha conta
    Step(F('login-email'), hold=PACE.read),                       # e-mail da conta (digitado pelo teclado)
    Step(F('login-password'), hold=PACE.read, tap=(696, 200)),    # Entrar (senha mascarada)
    Step(F('choose-account'), tap=(584, 328)),                    # Por autonomia (BYD Dolphin da conta)
    Step(F('autonomy'), tap=(670, 213)),                          # 60 km
    Step(F('payment-balance'), tap=(586, 329)),                   # Saldo do app - R$ 214,80
    Step(F('review-balance'), hold=PACE.read + 1.0),
], 'output/pitch-videos/totem/03-entrar-com-conta-e-saldo.mp4')
