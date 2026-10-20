"""Avaliação em Python puro de um gradient boosting exportado do scikit-learn.

Formato do artefato (``model_v1.MODEL``): ``init`` (constante inicial), ``trees`` (cada
árvore aninhada: folha = ``float`` já multiplicado pela taxa de aprendizado; nó =
``(variável, limiar, esquerda, direita)``, com ``x[variável] <= limiar`` indo à
esquerda, como no scikit-learn). A soma segue a mesma ordem do scikit-learn
(``init`` e depois cada árvore); as folhas escolhidas são as mesmas e o resultado só
difere no último dígito (o código compilado pode fundir multiplicação e soma).
O scikit-learn converte as variáveis para ``float32`` antes de comparar com os
limiares; ``as_float32`` reproduz isso. O modelo prevê o **resíduo** em relação ao
baseline.
"""

from __future__ import annotations

import struct

_F32 = struct.Struct("f")


def as_float32(x) -> list[float]:
    return [_F32.unpack(_F32.pack(value))[0] for value in x]


def tree_value(node, x) -> float:
    while not isinstance(node, float):
        feature, threshold, left, right = node
        node = left if x[feature] <= threshold else right
    return node


def raw_predict(model: dict, x) -> float:
    x = as_float32(x)
    value = model["init"]
    for tree in model["trees"]:
        value += tree_value(tree, x)
    return value


def predict_occupancy(model: dict, x, base: float) -> float:
    """Ocupação prevista (0–1) = baseline + resíduo previsto, limitada ao intervalo."""
    return min(1.0, max(0.0, base + raw_predict(model, x)))
