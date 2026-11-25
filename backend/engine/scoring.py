"""Score de risque explicable (règles) + probabilité de défaut indicative (modèle).

Score = 25 % rentabilité + 20 % liquidité + 20 % endettement + 20 % stabilité + 15 % qualité des données.
Pondérations et seuils illustratifs (guide Finance) : à valider par l'équipe Finance.
Le score n'est pas un modèle prédictif et ne constitue pas une décision de crédit.
"""
from __future__ import annotations

import json
import statistics
from functools import lru_cache
from pathlib import Path

import numpy as np

from .finance import ml_features

WEIGHTS = {"rentabilite": 0.25, "liquidite": 0.20, "endettement": 0.20, "stabilite": 0.20, "qualite": 0.15}
LABELS = {"rentabilite": "Rentabilité", "liquidite": "Liquidité", "endettement": "Endettement et capacité de remboursement",
          "stabilite": "Stabilité de l'activité", "qualite": "Qualité des données"}
# Alertes qui mettent en doute la fiabilité des chiffres eux-mêmes
INTEGRITY_CODES = {"doublons", "ecart_grand_livre", "bilan_desequilibre", "aucune_donnee"}
MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


def lin(x, bad, good):
    """Note 0-100 interpolée entre une valeur « mauvaise » (0) et « bonne » (100)."""
    if x is None:
        return None
    t = (x - bad) / (good - bad)
    return round(100 * min(1.0, max(0.0, t)), 1)


def _combine(parts):
    """parts = [(note, poids, libellé, valeur affichée, règle)] ; ignore les notes absentes."""
    avail = [p for p in parts if p[0] is not None]
    details = [{"criterion": p[2], "value": p[3], "note": p[0], "rule": p[4], "weight": p[1]} for p in parts]
    if not avail:
        return None, details
    w = sum(p[1] for p in avail)
    return round(sum(p[0] * p[1] for p in avail) / w, 1), details


def fmt_pct(v):
    return None if v is None else f"{v:.1f} %".replace(".", ",")


def fmt_x(v):
    return None if v is None else f"{v:.2f}".replace(".", ",")


def rule_score(analysis: dict, alerts: list[dict]) -> dict:
    if analysis.get("empty"):
        return {"score": None, "category": "Non calculable", "dimensions": [], "explanations": ["Aucune donnée."]}
    R = {k: r["value"] for k, r in analysis["ratios_by_key"].items()}
    cov = analysis["coverage"]
    sales = [r["ventes"] for r in analysis["monthly"] if r["ventes"] is not None][-12:]

    dims = {}
    dims["rentabilite"] = _combine([
        (lin(R["marge_nette"], 0, 12), 0.5, "Marge nette", fmt_pct(R["marge_nette"]), "0 % : note 0 ; ≥ 12 % : note 100"),
        (lin(R["marge_exploitation"], 0, 15), 0.25, "Marge d'exploitation", fmt_pct(R["marge_exploitation"]), "0 % : note 0 ; ≥ 15 % : note 100"),
        (lin(R["roa"], 0, 15), 0.25, "ROA", fmt_pct(R["roa"]), "0 % : note 0 ; ≥ 15 % : note 100"),
    ])
    tn = R["tresorerie_nette"]
    dims["liquidite"] = _combine([
        (lin(R["liquidite_generale"], 0.8, 2.0), 0.5, "Liquidité générale", fmt_x(R["liquidite_generale"]), "≤ 0,8 : note 0 ; ≥ 2 : note 100"),
        (lin(R["liquidite_immediate"], 0.05, 0.5), 0.25, "Trésorerie immédiate", fmt_x(R["liquidite_immediate"]), "≤ 0,05 : note 0 ; ≥ 0,5 : note 100"),
        (None if tn is None else (100.0 if tn > 0 else 0.0), 0.25, "Trésorerie nette (FR - BFR)",
         None if tn is None else f"{tn:,.0f} FCFA".replace(",", " "), "> 0 : note 100 ; ≤ 0 : note 0"),
    ])
    dims["endettement"] = _combine([
        (lin(R["dettes_capitaux_propres"], 2.0, 0.3), 0.35, "Dettes financières / capitaux propres",
         fmt_x(R["dettes_capitaux_propres"]), "≥ 2 : note 0 ; ≤ 0,3 : note 100"),
        (lin(R["poids_dettes"], 80, 30), 0.15, "Poids des dettes", fmt_pct(R["poids_dettes"]), "≥ 80 % : note 0 ; ≤ 30 % : note 100"),
        (lin(R["dscr_avec_credit"], 1.0, 2.0), 0.5, "DSCR avec le crédit demandé", fmt_x(R["dscr_avec_credit"]),
         "≤ 1 : note 0 ; ≥ 2 : note 100"),
    ])
    cv = statistics.pstdev(sales) / statistics.mean(sales) if len(sales) >= 3 and statistics.mean(sales) > 0 else None
    slope = None
    if len(sales) >= 6:
        x = np.arange(len(sales))
        slope = float(np.polyfit(x, sales, 1)[0] / np.mean(sales) * 100)  # % du CA moyen par mois
    has_decline = any(a["code"] == "baisse_prolongee" for a in alerts)
    dims["stabilite"] = _combine([
        (lin(cv, 0.35, 0.05), 0.4, "Régularité des ventes (coef. de variation)", fmt_pct(cv and cv * 100),
         "≥ 35 % : note 0 ; ≤ 5 % : note 100"),
        (lin(slope, -5, 2), 0.4, "Tendance des ventes", None if slope is None else f"{slope:+.1f} % / mois".replace(".", ","),
         "≤ -5 %/mois : note 0 ; ≥ +2 %/mois : note 100"),
        (0.0 if has_decline else 100.0, 0.2, "Absence de baisse prolongée", "baisse détectée" if has_decline else "aucune",
         "baisse ≥ 3 mois consécutifs : note 0"),
    ])
    sc = cov["status_counts"]
    total = sum(sc.values()) or 1
    reliable = (sc.get("justifie", 0) + 0.85 * sc.get("verifie", 0) + 0.6 * sc.get("declare", 0) + 0.4 * sc.get("extrait", 0) + 0.3 * sc.get("estime", 0)) / total
    high = sum(1 for a in alerts if a["severity"] == "elevee")
    dims["qualite"] = _combine([
        (lin(cov["n_months_pnl"] - len(cov["missing_months"]), 3, 12), 0.4, "Mois couverts",
         f"{cov['n_months_pnl']} mois", "≤ 3 : note 0 ; ≥ 12 : note 100"),
        (round(100 * reliable, 1), 0.3, "Fiabilité des sources",
         f"{sc.get('justifie', 0)} justifiées / {sc.get('verifie', 0)} confirmées / {sc.get('declare', 0)} déclarées / {sc.get('extrait', 0)} extraites",
         "justifié 100 % · confirmé 85 % · déclaré 60 % · extrait 40 % · estimé 30 %"),
        (max(0.0, 100.0 - 35 * high), 0.3, "Alertes de sévérité élevée", f"{high}", "-35 points par alerte élevée"),
    ])

    dimensions, num, den = [], 0.0, 0.0
    for k, w in WEIGHTS.items():
        note, details = dims[k]
        dimensions.append({"key": k, "label": LABELS[k], "weight": w, "note": note, "details": details})
        if note is not None:
            num, den = num + note * w, den + w
    score = round(num / den, 1) if den else None
    if score is None:
        cat = "Non calculable"
    elif score >= 80:
        cat = "Profil présentant des indicateurs favorables"
    elif score >= 60:
        cat = "Profil à examiner avec attention"
    else:
        cat = "Profil présentant plusieurs facteurs de risque"
    integrity = [a["title"] for a in alerts if a["severity"] == "elevee" and a["code"] in INTEGRITY_CODES]
    capped = bool(integrity) and score is not None and score >= 80
    if capped:
        cat = "Profil à examiner avec attention"
    expl = []
    if capped:
        expl.append("Catégorie plafonnée à « à examiner » : alertes de fiabilité non résolues (" + " ; ".join(integrity) + ").")
    for d in sorted([d for d in dimensions if d["note"] is not None], key=lambda d: d["note"]):
        worst = min((x for x in d["details"] if x["note"] is not None), key=lambda x: x["note"], default=None)
        best = max((x for x in d["details"] if x["note"] is not None), key=lambda x: x["note"], default=None)
        if d["note"] < 50 and worst:
            expl.append(f"À surveiller : {d['label'].lower()} ({d['note']:.0f}/100) : {worst['criterion']} = {worst['value']}.")
        elif d["note"] >= 75 and best:
            expl.append(f"Atout : {d['label'].lower()} ({d['note']:.0f}/100) : {best['criterion']} = {best['value']}.")
    missing = [d["label"] for d in dimensions if d["note"] is None]
    if missing:
        expl.append("Non calculable (pondération redistribuée) : " + ", ".join(missing) + ".")
    return {"score": score, "category": cat, "capped": capped, "dimensions": dimensions, "explanations": expl,
            "weights_note": "Pondérations et seuils illustratifs, à valider par l'équipe Finance."}


@lru_cache(maxsize=1)
def _load_model():
    """Modèle exporté en JSON (ml/export_model.py) : aucune dépendance lourde en production."""
    path = MODEL_DIR / "pd_model.json"
    if not path.exists():
        return None, None
    return json.loads(path.read_text()), json.loads((MODEL_DIR / "model_card.json").read_text())


def recalibrate(pd: float, model_rate: float, local_rate: float) -> float:
    """Correction du taux de base : le modèle a appris sur un taux de défaut de model_rate ; on ramène
    ses probabilités au taux local observé par l'établissement (cotes multipliées par le rapport des cotes)."""
    odds = pd / (1 - pd) * (local_rate / (1 - local_rate)) / (model_rate / (1 - model_rate))
    return odds / (1 + odds)


def pd_estimate(analysis: dict, lgd: float = 0.45, local_default_rate: float | None = None) -> dict:
    bundle, card = _load_model()
    if bundle is None:
        return {"available": False, "reason": "Modèle non entraîné (lancer ml/train_pd.py)."}
    feats = ml_features(analysis)
    if not feats:
        return {"available": False, "reason": "Données insuffisantes."}
    variant = "complet" if feats.get("sales_growth") is not None else "sans_croissance"
    entry = bundle["variants"][variant]
    names = entry["features"]
    present = sum(feats.get(n) is not None for n in names)
    if present < 8:
        return {"available": False, "reason": f"Seulement {present}/{len(names)} ratios calculables : estimation non fiable."}
    from .pd_runtime import predict

    row, imputed = {}, []
    for n in names:
        v = feats.get(n)
        lo, hi = bundle["bounds"][n]
        if v is None:
            imputed.append(card["features"][n])
            v = bundle["medians"][n]  # valeur neutre : médiane d'entraînement
        row[n] = float(min(hi, max(lo, v)))
    pd_value, contribs = predict(entry, [row[n] for n in names])
    factors = []
    for i in np.argsort(-np.abs(contribs))[:5]:
        factors.append({"feature": names[i], "label": card["features"][names[i]],
                        "value": round(row[names[i]], 3), "imputed": feats.get(names[i]) is None,
                        "effect": "augmente le risque" if contribs[i] > 0 else "réduit le risque",
                        "contribution": round(float(contribs[i]), 3)})
    ead = (analysis.get("credit") or {}).get("request", {}).get("amount")
    base = card["dataset"]["base_rate"]
    pd_raw = pd_value
    local = local_default_rate if local_default_rate and 0 < local_default_rate < 0.5 else None
    if local:
        pd_value = recalibrate(pd_raw, base, local)
    return {
        "available": True, "pd": round(pd_value, 4), "pd_raw": round(pd_raw, 4), "recalibrated": bool(local),
        "local_default_rate": local, "base_rate": round(local or base, 4), "model_base_rate": round(base, 4),
        "relative_to_base": round(pd_value / (local or base), 2),
        "calibration_note": (f"Recalibrée sur le taux de défaut de votre portefeuille ({local * 100:.1f} %), "
                             f"au lieu du taux du jeu d'entraînement ({base * 100:.1f} %).".replace(".", ",", 2) if local else
                             "Non recalibrée : probabilité relative au jeu d'entraînement (entreprises polonaises). "
                             "Saisissez le taux de défaut observé sur votre portefeuille pour l'adapter à votre marché."),
        "features_used": present, "features_total": len(names), "variant": variant,
        "variant_label": card["variants"][variant], "imputed": imputed,
        "inputs": {n: round(row[n], 4) for n in names},
        "factors": factors,
        "expected_loss": None if not ead else {"pd": round(pd_value, 4), "lgd": lgd, "ead": ead,
                                               "el": round(pd_value * lgd * ead)},
        "model": card["selected_model"][variant], "metrics": card["metrics_test"][variant][card["selected_model"][variant]],
        "baseline_metrics": card["metrics_test"][variant]["logistic_regression"],
        "dataset": card["dataset"], "limits": card["limits"],
    }
