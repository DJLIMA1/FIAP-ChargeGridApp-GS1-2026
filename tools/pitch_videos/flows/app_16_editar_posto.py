"""App (vendedor) · Editar dados do posto: Estações -> posto -> Dados da estação -> novo nome -> salvo -> lista."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=9010, route='operator', mode='vendor') as s:
    s.hold(PACE.intro)
    s.tap_text('Marginal Pinheiros', wait=PACE.after_tap)
    s.tap_text('Dados da estação', wait=PACE.after_tap)
    s.pause(); s.hold(2.5); s.resume()  # deixa a operação de abertura acabar fora de câmera
    s.tap(300, 211, wait=0.4)           # campo Nome da estação (cursor no fim)
    s.key('End', 'End', 35)
    s.type(' Premium')
    s.hold(0.5)
    s.key('Enter', 'Enter', 13)
    s.hold(PACE.read)                   # aviso "Dados da estação salvos."
    s.tap_text('Voltar', exact=True, wait=PACE.read)   # menu do posto já com o novo nome
    s.tap_text('Voltar', exact=True, wait=PACE.read)   # lista Suas Estações
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/16-editar-dados-do-posto.mp4')
