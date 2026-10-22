"""App · Carteira: Início -> + Adicionar saldo -> valor -> Pix -> confirmar -> saldo atualizado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8970, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Adicionar saldo')
    s.tap_text('R$260,00', wait=0.3)
    s.type('50')
    s.hold(0.4)
    s.tap_text('Prosseguir para o pagamento')
    s.tap_text('Pix', exact=True)
    s.tap_text('Continuar', exact=True)
    s.hold(PACE.read)
    s.tap_text('Já paguei')
    s.hold(PACE.read)
    s.tap_text('Verificar Saldo', wait=PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/08-adicionar-saldo.mp4')
