"""App (vendedor) · Dados do posto: nome/endereço -> conector, potência, tarifa -> revisão -> publicar -> posto criado."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

DEBUG = Path('/private/tmp/claude-501/-Users-djmurillo-Desktop-Aulas-FIAP-ChargeGridApp/fb852e86-52d3-4198-9af2-ada7797c0750/scratchpad/a15')
DEBUG.mkdir(parents=True, exist_ok=True)


def fill(s, label, text, erase, dy=44):
    """Toca o campo logo abaixo do rótulo, apaga o valor de exemplo e digita."""
    x, y = s.find(label, exact=True)
    s.tap(x, y + dy, wait=0.3)
    for mod in (4, 2):   # selecionar tudo (Cmd/Ctrl+A) e apagar
        s.cdp.call('Input.dispatchKeyEvent', type='keyDown', key='a', code='KeyA', modifiers=mod,
                   windowsVirtualKeyCode=65, commands=['selectAll'])
        s.cdp.call('Input.dispatchKeyEvent', type='keyUp', key='a', code='KeyA', modifiers=mod, windowsVirtualKeyCode=65)
    time.sleep(0.2)
    s.key('Backspace', 'Backspace', 8)
    time.sleep(0.3)
    s.key('End', 'End', 35)
    for _ in range(erase):
        s.key('Backspace', 'Backspace', 8)
        time.sleep(0.02)
    time.sleep(0.3)
    s.type(text)
    s.hold(0.2)


def press(s, text, wait=None):
    x, y = s.find(text, exact=True)
    if y > 780:
        s.scroll(300, y=500)
        time.sleep(0.4)
    s.tap_text(text, exact=True, wait=wait)


with AppSession(port=9005, route='operator', mode='vendor', params={'claim': True}) as s:
    # Fora de câmera: vincular a central (outro vídeo); os avisos somem antes de gravar.
    s.pause()
    s.tap_text('Adicionar central', exact=True, wait=5.5)
    s.resume(clear=True)
    s.hold(PACE.intro)

    # Etapa 1 · Localização: nome e endereço
    fill(s, 'Nome da estação', 'Posto Paulista 1000', 26)
    fill(s, 'Endereço', 'Av. Paulista, 1000, São Paulo', 31)
    s.hold(0.8)
    s.shot(DEBUG / 'addr.png')
    print('ADDR', [l['label'] for l in s.labels()], flush=True)
    for item in s.labels():
        if 'Paulista' in item['label'] and item['y'] > 300 and item['role'] != 'textbox':
            print('SUG', item, flush=True)
    press(s, 'Salvar e continuar', wait=PACE.after_tap)
    s.shot(DEBUG / 'step2.png')
    print('S2', [l['label'] for l in s.labels()], flush=True)

    # Etapa 2 · Ponto e tarifa
    s.hold(0.5)
    fill(s, 'Potência (kW)', '22', 8)
    fill(s, 'Tarifa por kWh (R$)', '1.89', 9)
    s.shot(DEBUG / 'step2b.png')
    press(s, 'Salvar e revisar', wait=PACE.after_tap)

    # Etapa 3 · Revisão e publicação
    s.hold(PACE.after_tap)
    s.scroll(260, y=500)
    s.hold(PACE.after_tap)
    press(s, 'Publicar ponto', wait=PACE.read)
    s.shot(DEBUG / 'end.png')
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/15-preencher-dados-do-posto.mp4')
