"""Entraînement du modèle indicatif de probabilité de défaut (PD).

Données RÉELLES : UCI "Polish Companies Bankruptcy" (Tomczak, 2016), licence CC BY 4.0.
https://archive.ics.uci.edu/dataset/365/polish+companies+bankruptcy+data
Fichier 5year.arff : ratios financiers d'une année et statut de faillite UN AN plus tard
(5 910 entreprises polonaises, période 2000-2013).

Seuls les ratios que CreditWise sait recalculer à partir des états d'un commerçant sont
utilisés (voir FEATURES). Base de référence : régression logistique. Modèle principal :
XGBoost (GPU si disponible : `--device cuda`). Le modèle GPU n'est conservé que s'il bat
la base de référence sur le jeu de test (règle "un modèle simple d'abord").

Usage : python ml/train_pd.py [--device cuda]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "polish" / "5year.arff"
OUT = ROOT / "models"
SEED = 42

# Attribut UCI -> (nom CreditWise, libellé français)
FEATURES = {
    "Attr1": ("roa", "Résultat net / Total actif"),
    "Attr2": ("debt_ratio", "Total dettes / Total actif"),
    "Attr3": ("wc_assets", "Fonds de roulement net / Total actif"),
    "Attr4": ("current_ratio", "Actif circulant / Passif circulant"),
    "Attr9": ("asset_turnover", "Chiffre d'affaires / Total actif"),
    "Attr10": ("equity_assets", "Capitaux propres / Total actif"),
    "Attr20": ("inventory_days", "Stocks × 365 / Chiffre d'affaires"),
    "Attr21": ("sales_growth", "CA(n) / CA(n-1)"),
    "Attr23": ("net_margin", "Résultat net / Chiffre d'affaires"),
    "Attr40": ("cash_ratio", "Trésorerie / Passif circulant"),
    "Attr42": ("operating_margin", "Résultat d'exploitation / Chiffre d'affaires"),
    "Attr44": ("receivable_days", "Créances clients × 365 / Chiffre d'affaires"),
    "Attr46": ("quick_ratio", "(Actif circulant - Stocks) / Passif circulant"),
    "Attr51": ("st_liabilities_assets", "Passif circulant / Total actif"),
    "Attr56": ("gross_margin", "(CA - Coût des ventes) / CA"),
}
FEATURE_NAMES = [v[0] for v in FEATURES.values()]


def load_arff(path: Path) -> pd.DataFrame:
    cols, rows, in_data = [], [], False
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        low = line.lower()
        if low.startswith("@attribute"):
            cols.append(line.split()[1])
        elif low.startswith("@data"):
            in_data = True
        elif in_data:
            rows.append([np.nan if v == "?" else float(v) for v in line.split(",")])
    return pd.DataFrame(rows, columns=cols)


def clip_quantiles(df: pd.DataFrame, bounds: dict) -> pd.DataFrame:
    """Les ratios réels comportent des valeurs extrêmes (dénominateurs proches de 0)."""
    out = df.copy()
    for c, (lo, hi) in bounds.items():
        out[c] = out[c].clip(lo, hi)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cpu", help="cpu ou cuda")
    args = ap.parse_args()

    df = load_arff(RAW)
    y = df["class"].astype(int).values
    X = df[list(FEATURES)].rename(columns={k: v[0] for k, v in FEATURES.items()})
    print(f"{len(df)} entreprises, {y.sum()} faillites ({y.mean():.1%})")

    idx_tr, idx_te = train_test_split(np.arange(len(y)), test_size=0.25, stratify=y, random_state=SEED)
    bounds = {c: (float(X.iloc[idx_tr][c].quantile(0.01)), float(X.iloc[idx_tr][c].quantile(0.99))) for c in FEATURE_NAMES}
    Xc = clip_quantiles(X, bounds)
    medians = {c: float(Xc.iloc[idx_tr][c].median()) for c in FEATURE_NAMES}

    # Deux variantes : avec la croissance annuelle du CA (≥ 24 mois d'historique) et sans.
    variants = {"complet": FEATURE_NAMES, "sans_croissance": [f for f in FEATURE_NAMES if f != "sales_growth"]}
    bundle_models, all_results, importances, selected = {}, {}, {}, {}
    for vname, feats in variants.items():
        X_tr, X_te = Xc.iloc[idx_tr][feats], Xc.iloc[idx_te][feats]
        y_tr, y_te = y[idx_tr], y[idx_te]
        results = {}
        t0 = time.perf_counter()
        logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                              LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED))
        logit_cal = CalibratedClassifierCV(logit, method="isotonic", cv=5).fit(X_tr, y_tr)
        p = logit_cal.predict_proba(X_te)[:, 1]
        results["logistic_regression"] = {
            "roc_auc": roc_auc_score(y_te, p), "pr_auc": average_precision_score(y_te, p),
            "brier": brier_score_loss(y_te, p), "train_seconds": time.perf_counter() - t0}
        t0 = time.perf_counter()
        booster = xgb.XGBClassifier(
            n_estimators=600, max_depth=4, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8,
            min_child_weight=3, reg_lambda=1.0, tree_method="hist", device=args.device,
            eval_metric="aucpr", random_state=SEED)
        xgb_cal = CalibratedClassifierCV(booster, method="isotonic", cv=5).fit(X_tr, y_tr)
        p = xgb_cal.predict_proba(X_te)[:, 1]
        results["xgboost"] = {
            "roc_auc": roc_auc_score(y_te, p), "pr_auc": average_precision_score(y_te, p),
            "brier": brier_score_loss(y_te, p), "train_seconds": time.perf_counter() - t0, "device": args.device}
        gains = np.zeros(len(feats))
        for cc in xgb_cal.calibrated_classifiers_:
            imp = cc.estimator.get_booster().get_score(importance_type="gain")
            gains += np.array([imp.get(f, 0.0) for f in feats])
        importances[vname] = dict(sorted(zip(feats, (gains / gains.sum()).round(4).tolist()), key=lambda kv: -kv[1]))
        best = "xgboost" if results["xgboost"]["pr_auc"] > results["logistic_regression"]["pr_auc"] else "logistic_regression"
        selected[vname] = best
        bundle_models[vname] = {"model": xgb_cal if best == "xgboost" else logit_cal, "features": feats, "selected": best}
        all_results[vname] = {k: {m: (round(v, 4) if isinstance(v, float) else v) for m, v in r.items()} for k, r in results.items()}
        print(vname, json.dumps(all_results[vname], indent=1))

    # Prévalence de référence (pour lire une PD relativement au portefeuille d'entraînement)
    OUT.mkdir(exist_ok=True)
    joblib.dump({"models": bundle_models, "bounds": bounds, "medians": medians}, OUT / "pd_model.joblib")
    card = {
        "name": "CreditWise PD indicative",
        "selected_model": selected,
        "dataset": {
            "name": "UCI Polish Companies Bankruptcy (5year.arff)",
            "url": "https://archive.ics.uci.edu/dataset/365/polish+companies+bankruptcy+data",
            "license": "CC BY 4.0",
            "citation": "Zieba, Tomczak & Tomczak (2016), Expert Systems with Applications 58",
            "rows": int(len(df)), "positives": int(y.sum()), "base_rate": float(y.mean()),
            "target": "Faillite dans l'année suivant les états financiers",
            "real_data": True,
        },
        "features": {v[0]: v[1] for v in FEATURES.values()},
        "split": "Stratifié 75/25, graine 42 (jeu de test mis de côté avant tout réglage)",
        "variants": {"complet": "15 ratios dont la croissance annuelle du CA (≥ 24 mois d'historique)",
                     "sans_croissance": "14 ratios, utilisé quand l'historique fait moins de 24 mois"},
        "missing_values": "Ratio non calculable remplacé par la médiane d'entraînement (neutre) et signalé",
        "metrics_test": all_results,
        "feature_importance": importances,
        "limits": [
            "Entreprises polonaises 2000-2013 (industrie), pas des commerçants de l'UEMOA.",
            "La PD est un indicateur relatif ; elle n'est pas calibrée pour un portefeuille béninois.",
            "Aucune donnée de remboursement de crédit UEMOA : ce n'est pas une PD réglementaire.",
            "Ratios calculés sur 12 mois glissants à partir de données en partie déclaratives.",
            "Décision de crédit toujours prise par un analyste habilité.",
        ],
    }
    (OUT / "model_card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False))
    print("Modèles retenus :", selected)
    print("Importance :", json.dumps(importances, indent=1))


if __name__ == "__main__":
    main()
