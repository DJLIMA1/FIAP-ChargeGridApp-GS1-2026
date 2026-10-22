"""App · Chat: assistente com IA — duas perguntas, respostas completas."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402


def wait_answer(s, shown=3.0, limit=90):
    """Mostra o indicador de digitação por `shown` s; o resto da espera fica fora de câmera."""
    time.sleep(0.8)
    t0 = time.time()
    paused = False
    while time.time() - t0 < limit:
        names = ' '.join(str(l.get('label', '')) for l in s.labels())
        if 'digitando' not in names:
            break
        if not paused and time.time() - t0 > shown:
            s.pause()
            paused = True
        time.sleep(0.5)
    time.sleep(0.5)
    if paused:
        s.resume()


with AppSession(port=8985, route='home', mode='consumer', ai=True) as s:
    s.hold(PACE.intro)
    s.tap_text('Chat', exact=True, wait=PACE.read)
    s.tap_text('Quanto custa carregar de 20% a 80%?', wait=0.2)
    wait_answer(s)
    s.hold(PACE.read + 1)
    s.tap_text('Digite sua mensagem', wait=0.3)
    s.type('Qual o posto mais barato perto de mim?')
    s.hold(0.4)
    s.key('Enter', 'Enter', 13)
    wait_answer(s)
    s.hold(PACE.read + 1)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/11-chatbot.mp4')
