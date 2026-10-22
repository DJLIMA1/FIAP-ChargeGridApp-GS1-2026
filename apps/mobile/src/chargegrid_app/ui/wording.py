"""Texto visível sem marcas de simulação, demonstração ou pagamento de teste.

O núcleo (``chargegrid_core.receipt``/``billing``) ainda rotula alguns textos como "simulado" ou
"(teste)"; a tela e o PDF passam o recibo por ``clean_receipt`` antes de desenhar. Flags internas
(``environment``, ``source``, ``demo``) continuam intactas: só o texto que a pessoa lê muda.
"""

import re

# Palavras que não podem aparecer no que a pessoa lê (também usada pelos testes de varredura).
FORBIDDEN = re.compile(r'simulad|simulaç|\bdemo\b|demonstra|modo teste|\bteste\b|modo apresenta|ilustrativ',
                       re.IGNORECASE)

_SUFFIX = re.compile(r'\s*\((?:teste|simulad[oa]s?|sandbox|demo)\)', re.IGNORECASE)
_EXACT = {
    'Energia simulada pelo equipamento (não é medição de medidor)': 'Energia calculada pelo equipamento',
    'simulador local': 'equipamento',
    'Pagamento simulado': 'Pagamento',
    'Pagamento de teste (sandbox)': 'Pagamento',
}
_PARTS = ((' na simulação', ' pelo ponto'),)


def visible(text):
    """``text`` sem os rótulos de simulação/teste do núcleo (outros valores passam como vieram)."""
    if not isinstance(text, str):
        return text
    if text in _EXACT:
        return _EXACT[text]
    for old, new in _PARTS:
        text = text.replace(old, new)
    return _SUFFIX.sub('', text)


def visible_notes(notes):
    """Notas legíveis: as que só existem para avisar "demo/simulado/teste" saem da lista."""
    result = []
    for note in notes or []:
        note = visible(note)
        if isinstance(note, str) and note and not FORBIDDEN.search(note):
            result.append(note)
    return result


def clean_receipt(receipt):
    """Cópia do recibo (``chargegrid.receipt``) com os textos neutros; chaves e flags iguais."""
    def walk(value, key=None):
        if isinstance(value, dict):
            return {name: walk(item, name) for name, item in value.items()}
        if isinstance(value, list):
            if key == 'notes':
                return visible_notes(value)
            return [walk(item) for item in value]
        return visible(value)

    return walk(receipt) if isinstance(receipt, dict) else receipt
