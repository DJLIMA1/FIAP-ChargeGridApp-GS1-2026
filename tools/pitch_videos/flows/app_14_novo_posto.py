"""App (vendedor) · Criar novo posto: Início -> Estações -> Adicionar nova estação -> Vincular Central
-> Adicionar central simulada -> primeiro formulário do posto (nome/endereço)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder import PACE, AppSession  # noqa: E402

with AppSession(port=9000, route='home', mode='vendor') as s:
    s.hold(PACE.intro)
    print([l for l in s.labels()][:60] if '--labels' in sys.argv else '')
    s.tap_text('Estações', exact=True)
    s.hold(PACE.read)
    s.tap_text('Adicionar nova estação')
    s.hold(PACE.read)
    s.tap_text('Adicionar central simulada', exact=True)
    s.hold(PACE.read)
    s.hold(PACE.outro)
    s.render('output/pitch-videos/app/14-criar-novo-posto.mp4')
