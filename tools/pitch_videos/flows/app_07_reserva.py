"""App · Reservar um horário: posto -> Reservar estação -> conector -> reserva (taxa) -> cobrança -> pagamento -> revisão -> confirmada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

DBG = Path('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/r07')
DBG.mkdir(exist_ok=True)
n = 0


def look(s, tag):
    global n
    n += 1
    s.shot(DBG / f'{n:02d}-{tag}.png')
    print(n, tag, sorted({i['label'][:45].replace('\n', ' ') for i in s.labels()}))


with AppSession(port=8965, route='stations', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Villa Lobos Pinheiros', wait=PACE.after_tap)
    s.tap_text('Ver estação', exact=True, wait=1.5)
    try:
        s.find('Reservar estação', exact=True, timeout=3)
    except LookupError:
        s.tap_text('Ver estação', exact=True, wait=1.5)
    look(s, 'detail')
    s.tap_text('Reservar estação', exact=True)
    look(s, 'step1')
    s.tap_text('CCS2 - 60 kW', index=0)
    s.tap_text('Continuar', exact=True)
    look(s, 'step2')
    s.tap_text('Continuar', exact=True)
    look(s, 'step3')
    s.tap_text('Exemplo: 30', wait=0.3)
    s.type('30')
    s.tap_text('Próximo Passo', exact=True)
    look(s, 'step4')
    s.tap_text('Até 60 kW')
    s.tap_text('Continuar', exact=True)
    look(s, 'step5')
