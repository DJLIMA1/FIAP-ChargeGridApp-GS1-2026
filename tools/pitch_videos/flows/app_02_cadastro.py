"""App · Criar conta: login -> Criar conta -> preenche nome, e-mail e senha (motorista).
O envio não é gravado: na conta demo o cadastro real devolve erro, então o vídeo termina com o formulário preenchido."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8940) as s:
    s.hold(PACE.intro)
    s.tap_text('Criar conta', exact=True, wait=PACE.after_tap)
    s.tap_text('Seu nome', wait=0.3)
    s.type('Ana Souza')
    s.hold(0.4)
    s.tap_text('voce@email.com', wait=0.3)
    s.type('ana.souza@email.com')
    s.hold(0.4)
    s.tap_text('••••••••', wait=0.3)
    s.type('ChargeGrid2026')
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/02-criar-conta.mp4')
