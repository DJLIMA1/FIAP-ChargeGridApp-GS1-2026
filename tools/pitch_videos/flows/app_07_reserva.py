"""App · Reservar um horário: posto -> Reservar estação -> conector -> reserva (taxa) -> cobrança -> pagamento -> revisão -> confirmada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402


with AppSession(port=8965, route='stations', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Marginal Pinheiros', wait=PACE.after_tap)
    s.tap_text('Ver estação', exact=True, wait=0.25)
    s.pause()   # o detalhe carrega o mapa; só grava com a tela pronta
    try:
        s.find('Reservar estação', exact=True, timeout=6)
    except LookupError:
        s.tap_text('Ver estação', exact=True, wait=0.25)
        s.find('Reservar estação', exact=True, timeout=15)
    s.hold(2.5)
    s.resume()
    s.hold(PACE.after_tap)
    s.tap_text('Reservar estação', exact=True)
    s.tap_text('CCS2 - 60 kW', index=0)
    s.tap_text('Continuar', exact=True)
    s.tap_text('Continuar', exact=True)
    s.tap_text('Exemplo: 30', wait=0.3)
    s.type('30')
    s.hold(0.5)
    s.tap_text('Próximo Passo', exact=True, wait=1.2)
    if not any('Potência' in i['label'] for i in s.labels()):
        s.tap_text('Próximo Passo', exact=True, wait=1.2)
    s.tap_text('Até 60 kW')
    s.tap_text('Continuar', exact=True)
    s.tap_text('Saldo Disponível', index=0)
    s.tap_text('Continuar', exact=True, wait=1.5)
    s.hold(PACE.read)
    s.tap_text('Código do cupom', wait=0.3)
    s.type('BEMVINDO10')
    s.hold(0.4)
    s.tap_text('Aplicar', exact=True, wait=1.2)
    s.hold(PACE.read)
    s.tap_text('Confirmar reserva', exact=True, wait=2.0)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/07-reservar-horario.mp4')
