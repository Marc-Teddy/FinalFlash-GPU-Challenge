"""Moteur financier : consolidation des valeurs, ratios, analyse mensuelle et trimestrielle.

Principes (guide Finance CreditWise) :
  * un ratio n'est pas calculé si son numérateur ou son dénominateur est absent, nul ou incohérent ;
  * on ne compare jamais des périodes de durées différentes sans les ramener à une base comparable ;
  * chaque valeur garde sa source et son statut (déclaré, extrait, vérifié, estimé).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .items import CONTROL_ITEMS, ITEMS

STATUS_RANK = {"justifie": 4, "verifie": 3, "declare": 2, "extrait": 1, "estime": 0}
STATUS_LABEL = {"justifie": "justifié par une pièce", "verifie": "confirmé par le commerçant", "declare": "déclaré", "extrait": "extrait automatiquement", "estime": "estimé"}

CHARGE_ITEMS = ["transport", "loyers", "autres_charges_externes", "impots_taxes", "charges_personnel",
                "dotations_amortissements"]
CURRENT_ASSETS = ["stocks", "creances_clients", "autres_creances", "tresorerie"]
OPERATING_LIABS = ["dettes_fournisseurs", "dettes_fiscales_sociales", "autres_dettes"]
CURRENT_LIABS = OPERATING_LIABS + ["dettes_financieres_ct"]
LIABS = CURRENT_LIABS + ["dettes_financieres_lt"]


def ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def ym_add(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:7]) - 1 + k
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


def months_between(a: str, b: str) -> list[str]:
    out, m = [], a
    while m <= b:
        out.append(m)
        m = ym_add(m, 1)
    return out


def quarter_of(m: str) -> str:
    return f"{m[:4]}-T{(int(m[5:7]) - 1) // 3 + 1}"


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def pct_change(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100


# ---------------------------------------------------------------- consolidation
def consolidate(values: list[dict]) -> tuple[dict, dict, list[dict], dict]:
    """Retourne (flux_mensuels, bilans_mensuels, conflits, flux_pluri_mensuels).

    Plusieurs documents peuvent fournir le même poste pour la même période : on retient la
    valeur au meilleur statut (vérifié > déclaré > extrait > estimé) et on signale l'écart.
    Les flux couvrant plusieurs mois (états annuels/trimestriels) sont conservés à part.
    """
    best: dict[tuple, dict] = {}
    conflicts = []
    for v in values:
        ps, pe = v["period_start"], v["period_end"]
        nature = ITEMS[v["item"]][1]
        single_month = (ps.year, ps.month) == (pe.year, pe.month)
        if nature == "flux" and not single_month:
            key = ("long", f"{ym(ps)}..{ym(pe)}", v["item"])
        else:
            key = ("m", ym(pe), v["item"])
        cur = best.get(key)
        if cur is None:
            best[key] = v
            continue
        if abs(cur["amount"] - v["amount"]) > max(1.0, 0.01 * abs(cur["amount"])):
            conflicts.append({"item": v["item"], "period": key[1], "a": cur, "b": v})
        if STATUS_RANK.get(v["status"], 0) > STATUS_RANK.get(cur["status"], 0):
            best[key] = v
    flows: dict[str, dict] = defaultdict(dict)
    stocks: dict[str, dict] = defaultdict(dict)
    longs: dict[str, dict] = defaultdict(dict)
    for (kind, per, item), v in best.items():
        if kind == "long":
            longs[per][item] = v
        elif ITEMS[item][1] == "flux":
            flows[per][item] = v
        else:
            stocks[per][item] = v
    return dict(flows), dict(stocks), conflicts, dict(longs)


def _amt(d: dict, item: str):
    v = d.get(item)
    return None if v is None else v["amount"]


def month_pnl(f: dict) -> dict:
    """Compte de résultat recalculé d'un mois (montants FCFA)."""
    ventes = _amt(f, "ventes")
    cogs = _amt(f, "cout_ventes")
    if cogs is None and _amt(f, "achats_marchandises") is not None:
        cogs = _amt(f, "achats_marchandises") + (_amt(f, "variation_stocks") or 0.0)
    charges = {k: _amt(f, k) or 0.0 for k in CHARGE_ITEMS}
    if ventes is None:
        return {"ventes": None}
    produits = ventes + (_amt(f, "autres_produits") or 0.0)
    rex = None if cogs is None else produits - cogs - sum(charges.values())
    res = None if rex is None else rex + (_amt(f, "produits_financiers") or 0.0) \
        - (_amt(f, "charges_financieres") or 0.0) - (_amt(f, "impot_resultat") or 0.0)
    return {
        "ventes": ventes, "cout_ventes": cogs,
        "marge_commerciale": None if cogs is None else ventes - cogs,
        "charges_exploitation": None if cogs is None else cogs + sum(charges.values()),
        "resultat_exploitation": rex,
        "ebitda": None if rex is None else rex + charges["dotations_amortissements"],
        "charges_financieres": _amt(f, "charges_financieres") or 0.0,
        "impot_resultat": _amt(f, "impot_resultat") or 0.0,
        "remboursement_emprunts": _amt(f, "remboursement_emprunts") or 0.0,
        "resultat_net": res,
        "resultat_net_declare": _amt(f, "resultat_net"),
    }


def balance(b: dict) -> dict:
    g = {k: _amt(b, k) for k in ITEMS if ITEMS[k][1] == "stock"}
    known = lambda ks: [g[k] for k in ks if g[k] is not None]  # noqa: E731
    out = dict(g)
    out["actif_circulant"] = sum(known(CURRENT_ASSETS)) if known(CURRENT_ASSETS) else None
    out["passif_circulant"] = sum(known(CURRENT_LIABS)) if known(CURRENT_LIABS) else None
    out["total_actif_calc"] = None if out["actif_circulant"] is None else out["actif_circulant"] + (g["immobilisations"] or 0)
    dettes = known(LIABS)
    out["total_dettes"] = sum(dettes) if dettes else None
    out["total_passif_calc"] = None if g["capitaux_propres"] is None or not dettes else g["capitaux_propres"] + sum(dettes)
    out["dettes_financieres"] = None if g["dettes_financieres_lt"] is None and g["dettes_financieres_ct"] is None \
        else (g["dettes_financieres_lt"] or 0) + (g["dettes_financieres_ct"] or 0)
    rs = None if g["capitaux_propres"] is None else g["capitaux_propres"] + (g["dettes_financieres_lt"] or 0)
    out["fonds_roulement"] = None if rs is None or g["immobilisations"] is None else rs - g["immobilisations"]
    ops = known(OPERATING_LIABS)
    out["bfr"] = None if g["stocks"] is None and g["creances_clients"] is None else \
        (g["stocks"] or 0) + (g["creances_clients"] or 0) + (g["autres_creances"] or 0) - sum(ops)
    out["tresorerie_nette"] = None if out["fonds_roulement"] is None or out["bfr"] is None \
        else out["fonds_roulement"] - out["bfr"]
    return out


def annuity(amount: float, annual_rate: float, months: int) -> float:
    r = annual_rate / 12
    if months <= 0:
        return 0.0
    return amount / months if r == 0 else amount * r / (1 - (1 + r) ** -months)


# ---------------------------------------------------------------- analyse
def ratio(key, label, value, unit, formula, inputs, interpretation, reason=None, fmt=None):
    return {"key": key, "label": label, "value": None if value is None else round(value, 4), "unit": unit,
            "formula": formula, "inputs": inputs, "interpretation": interpretation,
            "status": "ok" if value is not None else "non_calculable",
            "reason": None if value is not None else (reason or "Donnée absente, nulle ou incohérente")}


def analyse(values: list[dict], request: dict | None = None) -> dict:
    flows, stocks, conflicts, longs = consolidate(values)
    pnl = {m: month_pnl(f) for m, f in flows.items()}
    pnl = {m: p for m, p in pnl.items() if p["ventes"] is not None}
    bal = {m: balance(b) for m, b in stocks.items()}

    all_months = sorted(set(pnl) | set(bal))
    if not all_months:
        return {"empty": True, "conflicts": conflicts, "coverage": {"months": [], "missing_months": []}}
    span = months_between(all_months[0], all_months[-1])
    missing_pnl = [m for m in span if m not in pnl]
    missing_bal = [m for m in span if m not in bal]

    last = max(pnl) if pnl else None
    ttm_months = [m for m in months_between(ym_add(last, -11), last) if m in pnl] if last else []
    prev_ttm = [m for m in months_between(ym_add(last, -23), ym_add(last, -12)) if m in pnl] if last else []
    n = len(ttm_months)
    factor = 12 / n if n else None  # annualisation si moins de 12 mois

    def ttm_sum(key, months=ttm_months):
        vals = [pnl[m][key] for m in months]
        return None if not vals or any(v is None for v in vals) else sum(vals)

    T = {k: ttm_sum(k) for k in ["ventes", "cout_ventes", "marge_commerciale", "resultat_exploitation", "ebitda",
                                 "resultat_net", "charges_financieres", "impot_resultat", "remboursement_emprunts"]}
    annualised = n < 12
    if annualised and factor:
        T = {k: (None if v is None else v * factor) for k, v in T.items()}

    bal_last_m = max(bal) if bal else None
    B = bal.get(bal_last_m, {}) if bal_last_m else {}
    bal_start_m = max([m for m in bal if m <= ym_add(last, -12)], default=None) if last and bal else None
    B0 = bal.get(bal_start_m) if bal_start_m else None
    avg_assets = None
    if B.get("total_actif_calc") is not None:
        avg_assets = B["total_actif_calc"] if not B0 or B0.get("total_actif_calc") is None \
            else (B["total_actif_calc"] + B0["total_actif_calc"]) / 2

    # Évolutions
    def q_sum(q):
        ms = [m for m in pnl if quarter_of(m) == q]
        return (sum(pnl[m]["ventes"] for m in ms), len(ms))

    quarters = sorted({quarter_of(m) for m in span})
    q_table = []
    for q in quarters:
        s, k = q_sum(q)
        q_table.append({"quarter": q, "ventes": s if k == 3 else None, "months": k, "complete": k == 3})
    complete_q = [q for q in q_table if q["complete"]]
    for i, q in enumerate(q_table):
        prev = q_table[i - 1] if i > 0 else None
        q["var_vs_prev"] = pct_change(q["ventes"], prev["ventes"]) if prev and prev["complete"] and q["complete"] else None
        yq = f"{int(q['quarter'][:4]) - 1}{q['quarter'][4:]}"
        ly = next((x for x in q_table if x["quarter"] == yq), None)
        q["var_yoy"] = pct_change(q["ventes"], ly["ventes"]) if ly and ly["complete"] and q["complete"] else None

    monthly = []
    for m in span:
        p = pnl.get(m)
        b = bal.get(m, {})
        prev = pnl.get(ym_add(m, -1))
        ly = pnl.get(ym_add(m, -12))
        monthly.append({
            "month": m, "has_pnl": p is not None, "has_balance": m in bal,
            "ventes": p and p["ventes"], "marge_commerciale": p and p["marge_commerciale"],
            "resultat_exploitation": p and p["resultat_exploitation"], "resultat_net": p and p["resultat_net"],
            "tresorerie": b.get("tresorerie"), "dettes_financieres": b.get("dettes_financieres"),
            "tresorerie_nette_constatee": None if b.get("tresorerie") is None else b["tresorerie"] - (b.get("dettes_financieres_ct") or 0),
            "var_mom": pct_change(p and p["ventes"], prev and prev["ventes"]),
            "var_yoy": pct_change(p and p["ventes"], ly and ly["ventes"]),
        })

    # Service de la dette
    req = request or {}
    new_annual_service = None
    if req.get("amount"):
        inst = annuity(req["amount"], req.get("annual_rate", 0.0), int(req.get("duration_months", 12)))
        new_annual_service = inst * min(12, int(req.get("duration_months", 12)))
    existing_service = None if T["remboursement_emprunts"] is None else T["remboursement_emprunts"] + (T["charges_financieres"] or 0)
    cfads = None if T["ebitda"] is None else T["ebitda"] - (T["impot_resultat"] or 0)
    total_service = None if existing_service is None or new_annual_service is None else existing_service + new_annual_service

    ann = " (annualisé)" if annualised else ""
    last_q, prev_q = (complete_q[-1], complete_q[-2]) if len(complete_q) >= 2 else (None, None)
    R = [
        ratio("evol_ca_mensuelle", "Évolution du CA (dernier mois)", pct_change(pnl[last]["ventes"], pnl.get(ym_add(last, -1), {}).get("ventes")) if last else None,
              "%", "((CA mois - CA mois précédent) / CA mois précédent) × 100",
              {"mois": last}, "Hausse ou baisse des ventes d'un mois à l'autre.", "Mois précédent absent ou nul"),
        ratio("evol_ca_trimestrielle", "Évolution du CA (dernier trimestre complet)",
              pct_change(last_q["ventes"], prev_q["ventes"]) if last_q else None, "%",
              "((CA trimestre - CA trimestre précédent) / CA trimestre précédent) × 100",
              {"trimestre": last_q and last_q["quarter"]}, "Compare deux trimestres complets.",
              "Moins de deux trimestres complets"),
        ratio("evol_ca_annuelle", "Évolution du CA sur 12 mois glissants",
              pct_change(ttm_sum("ventes"), ttm_sum("ventes", prev_ttm)) if len(prev_ttm) == 12 and n == 12 else None, "%",
              "((CA 12 derniers mois - CA 12 mois précédents) / CA 12 mois précédents) × 100", {},
              "Neutralise la saisonnalité en comparant deux années complètes.", "Moins de 24 mois de données"),
        ratio("taux_marge_commerciale", "Taux de marge commerciale", div(T["marge_commerciale"], T["ventes"]) and div(T["marge_commerciale"], T["ventes"]) * 100,
              "%", "((Ventes - Coût d'achat des marchandises vendues) / Ventes) × 100",
              {"ventes": T["ventes"], "cout_ventes": T["cout_ventes"]}, "Ce qui reste des ventes après le coût des marchandises.",
              "Coût des marchandises vendues absent"),
        ratio("marge_nette", "Taux de marge nette" + ann, (div(T["resultat_net"], T["ventes"]) or 0) * 100 if div(T["resultat_net"], T["ventes"]) is not None else None,
              "%", "(Résultat net / Chiffre d'affaires) × 100", {"resultat_net": T["resultat_net"], "ventes": T["ventes"]},
              "Part du chiffre d'affaires qui reste en résultat net."),
        ratio("resultat_exploitation", "Résultat d'exploitation (12 mois)" + ann, T["resultat_exploitation"], "FCFA",
              "Produits d'exploitation - Charges d'exploitation", {}, "Résultat de l'activité courante."),
        ratio("marge_exploitation", "Marge d'exploitation", (div(T["resultat_exploitation"], T["ventes"]) or 0) * 100 if div(T["resultat_exploitation"], T["ventes"]) is not None else None,
              "%", "(Résultat d'exploitation / Chiffre d'affaires) × 100", {}, "Part des ventes conservée après les charges d'exploitation."),
        ratio("roa", "Rentabilité des actifs (ROA)", (div(T["resultat_net"], avg_assets) or 0) * 100 if div(T["resultat_net"], avg_assets) is not None else None,
              "%", "(Résultat net / Total actif moyen) × 100",
              {"total_actif_moyen": avg_assets, "actif_moyen": B0 is not None},
              "Résultat généré par les actifs." + ("" if B0 else " Actif de fin de période utilisé (pas d'actif d'ouverture)."),
              "Bilan absent"),
        ratio("liquidite_generale", "Ratio de liquidité générale", div(B.get("actif_circulant"), B.get("passif_circulant")), "x",
              "Actif circulant / Passif circulant", {"actif_circulant": B.get("actif_circulant"), "passif_circulant": B.get("passif_circulant")},
              "Ressources à court terme comparées aux dettes à court terme (> 1 : couverture)."),
        ratio("liquidite_immediate", "Ratio de trésorerie immédiate", div(B.get("tresorerie"), B.get("passif_circulant")), "x",
              "Trésorerie / Passif circulant", {}, "Capacité à payer les dettes court terme avec l'argent disponible."),
        ratio("fonds_roulement", "Fonds de roulement (FR)", B.get("fonds_roulement"), "FCFA",
              "Ressources stables (capitaux propres + dettes LT) - Emplois stables (immobilisations)", {},
              "Ressources durables restant pour financer le cycle d'exploitation."),
        ratio("bfr", "Besoin en fonds de roulement (BFR)", B.get("bfr"), "FCFA",
              "Stocks + Créances d'exploitation - Dettes d'exploitation", {}, "Argent immobilisé dans le fonctionnement courant."),
        ratio("tresorerie_nette", "Trésorerie nette", B.get("tresorerie_nette"), "FCFA", "Fonds de roulement - BFR", {},
              "Excédent (> 0) ou besoin (< 0) de trésorerie théorique."),
        ratio("dettes_capitaux_propres", "Dettes financières / Capitaux propres", div(B.get("dettes_financieres"), B.get("capitaux_propres")) if (B.get("capitaux_propres") or 0) > 0 else None,
              "x", "Total des dettes financières / Capitaux propres",
              {"dettes_financieres": B.get("dettes_financieres"), "capitaux_propres": B.get("capitaux_propres")},
              "Financement par la dette comparé au financement par les propriétaires.", "Capitaux propres absents, nuls ou négatifs"),
        ratio("poids_dettes", "Poids des dettes", (div(B.get("total_dettes"), B.get("total_passif_calc")) or 0) * 100 if div(B.get("total_dettes"), B.get("total_passif_calc")) is not None else None,
              "%", "(Total dettes / Total passif) × 100", {}, "Part des ressources provenant des dettes (financières, fournisseurs, fiscales et sociales)."),
        ratio("dscr_actuel", "DSCR (échéances actuelles)", div(cfads, existing_service) if existing_service else None, "x",
              "(EBE - impôt) / (Principal remboursé + intérêts) sur 12 mois", {"flux_disponible": cfads, "service_dette": existing_service},
              "> 1 : les flux couvrent théoriquement les échéances. Définition du flux à valider avec Finance.",
              "Aucune échéance de dette enregistrée" if existing_service == 0 else None),
        ratio("dscr_avec_credit", "DSCR avec le crédit demandé", div(cfads, total_service), "x",
              "(EBE - impôt) / (Échéances actuelles + échéances du nouveau crédit sur 12 mois)",
              {"flux_disponible": cfads, "service_dette_total": total_service, "nouvelle_echeance_mensuelle": new_annual_service and new_annual_service / min(12, int(req.get("duration_months", 12)))},
              "Couverture des échéances si le crédit est accordé. Ne suffit pas seul à approuver un crédit.",
              "Aucune demande de crédit ou flux disponible absent"),
        ratio("delai_stocks", "Rotation des stocks", div(B.get("stocks"), T["cout_ventes"]) and div(B.get("stocks"), T["cout_ventes"]) * 365, "jours",
              "Stocks × 365 / Coût des marchandises vendues", {}, "Nombre de jours de ventes en stock."),
        ratio("delai_clients", "Délai de paiement clients", div(B.get("creances_clients"), T["ventes"]) and div(B.get("creances_clients"), T["ventes"]) * 365, "jours",
              "Créances clients × 365 / Chiffre d'affaires", {}, "Délai moyen d'encaissement des ventes à crédit."),
        ratio("delai_fournisseurs", "Délai de paiement fournisseurs", div(B.get("dettes_fournisseurs"), T["cout_ventes"]) and div(B.get("dettes_fournisseurs"), T["cout_ventes"]) * 365, "jours",
              "Dettes fournisseurs × 365 / Coût des marchandises vendues", {}, "Délai moyen de paiement des fournisseurs."),
    ]
    # Valeurs FCFA à arrondir
    for r in R:
        if r["unit"] == "FCFA" and r["value"] is not None:
            r["value"] = round(r["value"])

    # Provenance des données retenues
    used = [v for d in list(flows.values()) + list(stocks.values()) for v in d.values()]
    status_counts = defaultdict(int)
    for v in used:
        status_counts[v["status"]] += 1
    items_seen = {v["item"] for v in used}
    missing_items = [k for k in ["ventes", "cout_ventes", "charges_personnel", "loyers", "tresorerie", "stocks",
                                 "creances_clients", "dettes_fournisseurs", "capitaux_propres", "remboursement_emprunts"]
                     if k not in items_seen and not (k == "cout_ventes" and "achats_marchandises" in items_seen)]

    return {
        "empty": False,
        "coverage": {
            "first_month": span[0], "last_month": span[-1], "months": span, "n_months_pnl": len(pnl),
            "missing_months": missing_pnl, "missing_balance_months": missing_bal,
            "ttm_months": ttm_months, "annualised": annualised, "last_balance": bal_last_m,
            "status_counts": dict(status_counts), "n_values": len(used), "missing_items": missing_items,
            "missing_items_labels": [ITEMS[k][0] for k in missing_items],
            "long_period_statements": sorted(longs),
        },
        "ttm": {k: (None if v is None else round(v)) for k, v in T.items()},
        "balance_last": {k: (None if v is None else round(v)) for k, v in B.items()},
        "ratios": R,
        "ratios_by_key": {r["key"]: r for r in R},
        "monthly": monthly,
        "quarterly": q_table,
        "pnl": pnl, "balances": bal, "conflicts": conflicts,
        "flows_raw": flows, "stocks_raw": stocks,
        "credit": {
            "request": req, "cfads_annual": cfads and round(cfads), "existing_service_annual": existing_service and round(existing_service),
            "new_installment": round(annuity(req["amount"], req.get("annual_rate", 0.0), int(req.get("duration_months", 12)))) if req.get("amount") else None,
            "new_service_annual": new_annual_service and round(new_annual_service),
            "max_installment_dscr_1_25": None if cfads is None or existing_service is None else round(max(0.0, (cfads / 1.25 - existing_service) / 12)),
        },
        "control_items": sorted(CONTROL_ITEMS),
    }


def ml_features(a: dict) -> dict:
    """Ratios au format du modèle PD (mêmes définitions que le jeu UCI)."""
    if a.get("empty"):
        return {}
    T, B = a["ttm"], a["balance_last"]
    ta, pc, ac = B.get("total_actif_calc"), B.get("passif_circulant"), B.get("actif_circulant")
    sales = T.get("ventes")
    prev_growth = a["ratios_by_key"]["evol_ca_annuelle"]["value"]
    return {
        "roa": div(T.get("resultat_net"), ta),
        "debt_ratio": div(B.get("total_dettes"), ta),
        "wc_assets": div(None if ac is None or pc is None else ac - pc, ta),
        "current_ratio": div(ac, pc),
        "asset_turnover": div(sales, ta),
        "equity_assets": div(B.get("capitaux_propres"), ta),
        "inventory_days": None if div(B.get("stocks"), sales) is None else div(B.get("stocks"), sales) * 365,
        "sales_growth": None if prev_growth is None else 1 + prev_growth / 100,
        "net_margin": div(T.get("resultat_net"), sales),
        "cash_ratio": div(B.get("tresorerie"), pc),
        "operating_margin": div(T.get("resultat_exploitation"), sales),
        "receivable_days": None if div(B.get("creances_clients"), sales) is None else div(B.get("creances_clients"), sales) * 365,
        "quick_ratio": div(None if ac is None else ac - (B.get("stocks") or 0), pc),
        "st_liabilities_assets": div(pc, ta),
        "gross_margin": div(T.get("marge_commerciale"), sales),
    }
