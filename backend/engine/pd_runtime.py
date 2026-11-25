"""Calcul de la probabilité de défaut à partir du modèle exporté (models/pd_model.json), avec numpy seul.

Pour chaque modèle du jeu de validation croisée : somme des feuilles des arbres (marge), conversion en
probabilité, calibration isotonique, puis moyenne des modèles. Les contributions par variable suivent la
méthode « approchée » de xgboost : variation de la valeur moyenne du nœud à chaque division franchie.
"""
from __future__ import annotations

import numpy as np


def _tree(t: dict, x, contrib):
    i = 0
    while t["l"][i] != -1:
        f = t["f"][i]
        v = x[f]
        nxt = (t["l"][i] if t["d"][i] else t["r"][i]) if v != v else (t["l"][i] if v < t["c"][i] else t["r"][i])
        contrib[f] += t["m"][nxt] - t["m"][i]
        i = nxt
    return t["c"][i]


def predict(variant: dict, x) -> tuple[float, np.ndarray]:
    """Retourne (probabilité calibrée, contributions moyennes par variable, en marge logit)."""
    x = [float(v) for v in x]
    n = len(variant["features"])
    probs, contribs = [], np.zeros(n)
    for fold in variant["folds"]:
        c = np.zeros(n)
        margin = fold["base"] + sum(_tree(t, x, c) for t in fold["trees"])
        p = 1.0 / (1.0 + np.exp(-margin))
        probs.append(float(np.interp(p, fold["iso_x"], fold["iso_y"])))
        contribs += c
    return float(np.mean(probs)), contribs / len(variant["folds"])
