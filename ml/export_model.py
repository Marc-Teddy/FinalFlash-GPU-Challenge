"""Exporte le modèle PD (XGBoost calibré) dans un JSON lisible par numpy seul.

En production (Vercel), xgboost, scikit-learn et scipy ne sont pas installés : ils dépassent la taille
autorisée pour une fonction. Ce script convertit chaque arbre et chaque calibration isotonique, puis
vérifie que les probabilités et les contributions recalculées sont identiques à celles du modèle d'origine.

Usage : python ml/export_model.py   (après ml/train_pd.py)
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


def _base_margin(booster: xgb.Booster) -> float:
    cfg = json.loads(booster.save_config())
    raw = cfg["learner"]["learner_model_param"]["base_score"]
    p = float(str(raw).strip("[]"))
    return float(np.log(p / (1 - p)))


def _trees(booster: xgb.Booster) -> list[dict]:
    model = json.loads(booster.save_raw("json"))
    out = []
    for t in model["learner"]["gradient_booster"]["model"]["trees"]:
        left, right = t["left_children"], t["right_children"]
        cond, hess = t["split_conditions"], t["sum_hessian"]
        # Valeur moyenne de chaque nœud (pondérée par la hessienne), comme xgboost pour les contributions approchées
        mean = [0.0] * len(left)

        def fill(i):
            if left[i] == -1:
                mean[i] = cond[i]
            else:
                fill(left[i]), fill(right[i])
                h = hess[left[i]] + hess[right[i]]
                mean[i] = (mean[left[i]] * hess[left[i]] + mean[right[i]] * hess[right[i]]) / h if h else 0.0
        fill(0)
        out.append({"l": left, "r": right, "f": t["split_indices"], "c": cond,
                    "d": [bool(x) for x in t["default_left"]], "m": mean})
    return out


def main() -> None:
    bundle = joblib.load(MODELS / "pd_model.joblib")
    out = {"bounds": bundle["bounds"], "medians": bundle["medians"], "variants": {}}
    from backend.engine.pd_runtime import predict  # même code qu'en production

    for name, entry in bundle["models"].items():
        if entry["selected"] != "xgboost":
            raise SystemExit(f"Variante {name} : seul un modèle XGBoost peut être exporté.")
        folds = []
        for cc in entry["model"].calibrated_classifiers_:
            booster = cc.estimator.get_booster()
            iso = cc.calibrators[0]
            folds.append({"base": _base_margin(booster), "trees": _trees(booster),
                          "iso_x": iso.X_thresholds_.tolist(), "iso_y": iso.y_thresholds_.tolist()})
        out["variants"][name] = {"features": entry["features"], "folds": folds}

        # Contrôle : mêmes probabilités et mêmes contributions que le modèle d'origine
        rng = np.random.default_rng(0)
        feats = entry["features"]
        X = np.array([[rng.uniform(*bundle["bounds"][f]) for f in feats] for _ in range(200)])
        import pandas as pd
        ref = entry["model"].predict_proba(pd.DataFrame(X, columns=feats))[:, 1]
        got = np.array([predict(out["variants"][name], x)[0] for x in X])
        gap = float(np.max(np.abs(ref - got)))
        ref_c = np.mean([cc.estimator.get_booster().predict(xgb.DMatrix(pd.DataFrame(X[:20], columns=feats)), pred_contribs=True,
                                                            approx_contribs=True)[:, :-1] for cc in entry["model"].calibrated_classifiers_], axis=0)
        got_c = np.array([predict(out["variants"][name], x)[1] for x in X[:20]])
        gap_c = float(np.max(np.abs(ref_c - got_c)))
        print(f"{name}: écart max probabilité {gap:.2e}, contributions {gap_c:.2e}")
        if gap > 1e-5 or gap_c > 1e-4:
            raise SystemExit("Export incohérent avec le modèle d'origine.")
    (MODELS / "pd_model.json").write_text(json.dumps(out, separators=(",", ":")))
    print("Écrit :", MODELS / "pd_model.json", f"{(MODELS / 'pd_model.json').stat().st_size / 1e6:.1f} Mo")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    main()
