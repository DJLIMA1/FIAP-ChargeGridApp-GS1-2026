"""App · Chat: assistente — sugestão + pergunta digitada, respostas locais da conta demo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=8985, route='home', mode='consumer') as s:
    s.hold(PACE.intro)
    s.tap_text('Chat', exact=True, wait=PACE.read)
    s.tap_text('Resumo da última recarga', wait=PACE.read)
    s.tap_text('Digite sua mensagem', wait=0.3)
    s.type('Quanto custa o valor da recarga?')
    s.hold(0.4)
    s.key('Enter', 'Enter', 13)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/11-chatbot.mp4')
