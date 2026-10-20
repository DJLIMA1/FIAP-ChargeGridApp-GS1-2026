"""Treina o modelo de ocupação (gradient boosting) no histórico sintético e exporta o artefato.

Uso (dependências só de desenvolvimento, fora da API):

    python -m venv .venv-ml && .venv-ml/bin/pip install -r tools/requirements-ml.txt
    .venv-ml/bin/python tools/forecast/train_occupancy.py            # treina e grava o artefato
    .venv-ml/bin/python tools/forecast/train_occupancy.py --check    # só confere o artefato atual

Protocolo (``chargegrid_core.forecast.offline``): treino nos dias 28–139 dos postos de treino,
validação nos dias 140–174 (escolhe taxa de aprendizado e número de árvores), reajuste em
treino + validação e **teste único** nos dias 175–209 de todos os postos, inclusive os não
vistos. O artefato é um módulo Python puro (``model_v1.py``) avaliado sem scikit-learn em
produção; ``--check`` e os testes do core recalculam as métricas e conferem as previsões.
Depois de treinar, rode ``python tools/sync_core.py``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "packages" / "chargegrid_core"
sys.path.insert(0, str(CORE))

from chargegrid_core.forecast import offline  # noqa: E402
from chargegrid_core.forecast.features import FEATURES  # noqa: E402
from chargegrid_core.forecast.gbm import raw_predict  # noqa: E402

ARTIFACT = CORE / "chargegrid_core" / "forecast" / "model_v1.py"
VERSION = "occ-gbm-v1"
LEARNING_RATES = (0.1,)
MAX_TREES = 400
LOSS = "absolute_error"  # otimiza o MAE (e o WAPE), a métrica de comparação com o baseline
TOLERANCE = 1e-9
DEPTH = 3
MIN_LEAF = 40
SUBSAMPLE = 0.8
RANDOM_STATE = 7


def rows_for(stations, days):
    x, y, base = [], [], []
    for index in stations:
        _, series, ratios = offline.station(index)
        for features, b, actual, _ in offline.split_rows(series, ratios, days):
            x.append(features)
            y.append(actual - b)  # o modelo aprende o resíduo em relação ao baseline
            base.append(b)
    return x, y, base


def export_tree(tree, scale: float):
    left, right = tree.children_left, tree.children_right
    feature, threshold, value = tree.feature, tree.threshold, tree.value

    def node(i):
        if left[i] == -1:
            return float(scale * float(value[i][0][0]))
        return (int(feature[i]), float(threshold[i]), node(left[i]), node(right[i]))

    return node(0)


def fit(x, y, rate, trees):
    from sklearn.ensemble import GradientBoostingRegressor

    model = GradientBoostingRegressor(loss=LOSS, learning_rate=rate, n_estimators=trees, max_depth=DEPTH,
                                      min_samples_leaf=MIN_LEAF, subsample=SUBSAMPLE, random_state=RANDOM_STATE)
    return model.fit(x, y)


def train():
    import numpy as np
    import sklearn

    train_stations = [i for i in range(offline.STATIONS) if i not in offline.UNSEEN]
    x_train, y_train, _ = rows_for(train_stations, offline.TRAIN_DAYS)
    x_valid, y_valid, base_valid = rows_for(train_stations, offline.VALID_DAYS)
    print(f"treino: {len(x_train)} linhas; validação: {len(x_valid)} linhas")
    actual_valid = np.array(y_valid) + np.array(base_valid)
    best = None
    for rate in LEARNING_RATES:
        model = fit(x_train, y_train, rate, MAX_TREES)
        for trees, residual in enumerate(model.staged_predict(x_valid), start=1):
            guess = np.clip(np.array(base_valid) + residual, 0, 1)
            mae = float(np.mean(np.abs(actual_valid - guess)))
            if best is None or mae < best[0]:
                best = (mae, rate, trees)
    mae, rate, trees = best
    print(f"validação: melhor taxa {rate}, {trees} árvores, MAE {100 * mae:.2f} p.p.")
    x_all, y_all, _ = rows_for(train_stations, (offline.TRAIN_DAYS[0], offline.VALID_DAYS[1]))
    final = fit(x_all, y_all, rate, trees)
    exported = {
        "init": float(final.init_.constant_[0][0]),
        "trees": [export_tree(stage[0].tree_, rate) for stage in final.estimators_],
    }
    # Previsões de referência: o avaliador em Python puro deve reproduzir o scikit-learn.
    _, series, ratios = offline.station(offline.UNSEEN[0])
    golden_x = [features for features, _, _, _ in offline.split_rows(series, ratios, offline.TEST_DAYS, (0,))[:24]]
    golden = [[list(map(float, features)), float(value)] for features, value in zip(golden_x, final.predict(golden_x),
                                                                                       strict=True)]
    for features, value in golden:
        # Mesmas folhas; só a ordem de arredondamento da soma pode diferir (FMA no código compilado).
        assert abs(raw_predict(exported, features) - value) <= TOLERANCE, "avaliador puro diverge do scikit-learn"
    test = offline.evaluate(exported)
    verify = offline.verification(exported)
    print("teste:", test["baseline"], test["gbm"], "→", test["selected"])
    return {
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "trained_on": f"histórico sintético {offline.synthetic.VERSION} (semente {offline.SEED}, "
                      f"{offline.STATIONS} postos, {offline.DAYS} dias)",
        "library": f"scikit-learn {sklearn.__version__} GradientBoostingRegressor",
        "params": {"learning_rate": rate, "n_estimators": trees, "max_depth": DEPTH, "min_samples_leaf": MIN_LEAF,
                   "subsample": SUBSAMPLE, "random_state": RANDOM_STATE, "loss": LOSS,
                   "target": "ocupação − baseline"},
        "features": list(FEATURES),
        "split": {"train_days": list(offline.TRAIN_DAYS), "valid_days": list(offline.VALID_DAYS),
                  "test_days": list(offline.TEST_DAYS), "unseen_stations": list(offline.UNSEEN),
                  "origin_hours": list(offline.ORIGIN_HOURS), "horizon_hours": 36},
        "validation_mae_pp": round(100 * mae, 2),
        "offline_test": {key: value for key, value in test.items() if key != "selected"},
        "selected": test["selected"],
        "verification": verify,
        "golden": golden,
        **exported,
    }


def write(model: dict):
    lines = ['"""Modelo de ocupação exportado — GERADO por tools/forecast/train_occupancy.py; não editar."""', "",
             "# fmt: off", "MODEL = {"]
    for key, value in model.items():
        if key == "trees":
            lines.append('    "trees": [')
            lines.extend(f"        {tree!r}," for tree in value)
            lines.append("    ],")
        elif key == "golden":
            lines.append('    "golden": [')
            lines.extend(f"        {item!r}," for item in value)
            lines.append("    ],")
        else:
            lines.append(f"    {key!r}: {value!r},")
    lines.append("}")
    ARTIFACT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"artefato gravado: {ARTIFACT.relative_to(ROOT)} ({ARTIFACT.stat().st_size // 1024} KB)")


def check() -> int:
    from chargegrid_core.forecast.model_v1 import MODEL

    problems = []
    for features, value in MODEL["golden"]:
        if abs(raw_predict(MODEL, features) - value) > TOLERANCE:
            problems.append("previsão de referência divergente")
            break
    if offline.verification(MODEL) != MODEL["verification"]:
        problems.append("métricas de verificação divergentes")
    print("\n".join(problems) or "artefato confere")
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Só confere o artefato atual (sem scikit-learn).")
    args = parser.parse_args()
    if args.check:
        return check()
    write(train())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
