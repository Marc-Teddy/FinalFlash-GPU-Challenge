"""Détection d'anomalies : règles explicables d'abord, statistiques ensuite.

Une anomalie est une donnée inhabituelle ou incohérente qui mérite une vérification.
Elle ne prouve pas une fraude : chaque alerte affiche la raison du signalement et une
explication possible à rechercher.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from .finance import STATUS_LABEL, ym, ym_add
from .items import ITEMS, match_account

SEV_ORDER = {"elevee": 0, "attention": 1, "info": 2}

# Seuils métier (à valider par l'équipe Finance)
THRESHOLDS = {
    "variation_mensuelle_pct": 40.0,   # variation du CA d'un mois à l'autre
    "baisse_consecutive_mois": 3,      # baisse prolongée
    "zscore": 3.0,                     # |Z| ≥ 3 sur les montants de transactions
    "zscore_min_obs": 30,
    "ecart_totaux_pct": 2.0,           # écart état financier / grand livre
    "ecart_bilan_pct": 1.0,            # actif ≠ passif
}


def fmt(x):
    return f"{x:,.0f}".replace(",", " ") + " FCFA" if isinstance(x, (int, float)) else str(x)


def alert(code, severity, title, reason, period=None, explanation=None, evidence=None, method="règle"):
    return {"code": code, "severity": severity, "title": title, "reason": reason, "period": period,
            "explanation": explanation, "evidence": evidence or {}, "method": method}


def detect(analysis: dict, transactions: list[dict], documents: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: list[dict] = []
    if analysis.get("empty"):
        return [alert("aucune_donnee", "elevee", "Aucune donnée financière exploitable",
                      "Aucun état financier ou balance n'a pu être lu pour cette entreprise.")]
    cov = analysis["coverage"]

    # 1. Périodes non couvertes et documents manquants
    if cov["missing_months"]:
        out.append(alert("periodes_manquantes", "attention", f"{len(cov['missing_months'])} mois sans compte de résultat",
                         "Les mois suivants n'ont aucune donnée de ventes : " + ", ".join(cov["missing_months"]),
                         explanation="Demander les justificatifs ; ne pas interpréter l'absence comme une activité nulle."))
    if cov["n_months_pnl"] < 12:
        out.append(alert("historique_court", "attention", "Historique inférieur à 12 mois",
                         f"Seulement {cov['n_months_pnl']} mois disponibles : les montants annuels sont annualisés (estimés)."))
    if cov["missing_items"]:
        out.append(alert("postes_manquants", "info", "Postes financiers non fournis",
                         "Non fournis : " + ", ".join(cov["missing_items_labels"]),
                         explanation="Les ratios qui en dépendent sont affichés « non calculable »."))
    flows = analysis["flows_raw"]
    pnl_months = sorted(analysis["pnl"])
    for item in ITEMS:
        if ITEMS[item][1] != "flux" or item in {"resultat_net", "variation_stocks"}:
            continue
        present = [m for m in pnl_months if item in flows.get(m, {})]
        absent = [m for m in pnl_months if item not in flows.get(m, {})]
        if absent and len(present) >= 0.5 * len(pnl_months):
            out.append(alert("poste_absent_mois", "attention", f"« {ITEMS[item][0]} » absent certains mois",
                             f"Présent {len(present)} mois sur {len(pnl_months)}, absent en : " + ", ".join(absent) + ".",
                             explanation="Poste oublié ? Le résultat de ces mois est probablement surestimé.", period=", ".join(absent)))
    if not cov["last_balance"]:
        out.append(alert("bilan_absent", "elevee", "Aucun bilan fourni",
                         "Liquidité, endettement et trésorerie ne peuvent pas être analysés sans bilan."))

    # 2. Données contradictoires entre documents
    for c in analysis["conflicts"]:
        out.append(alert("valeurs_contradictoires", "attention", f"Valeurs différentes pour « {ITEMS[c['item']][0]} »",
                         f"{c['a']['source_name']} : {fmt(c['a']['amount'])} ({STATUS_LABEL.get(c['a']['status'])}) ; "
                         f"{c['b']['source_name']} : {fmt(c['b']['amount'])} ({STATUS_LABEL.get(c['b']['status'])}).",
                         period=c["period"], explanation="La valeur au statut le plus fiable a été retenue."))

    # 3. Montants négatifs anormaux
    for m, f in analysis["flows_raw"].items():
        for item, v in f.items():
            if item not in {"variation_stocks", "resultat_net"} and v["amount"] < 0:
                out.append(alert("montant_negatif", "attention", f"Montant négatif : {ITEMS[item][0]}",
                                 f"{fmt(v['amount'])} déclaré pour {m} ({v['source_name']}).", period=m))
    for m, b in analysis["stocks_raw"].items():
        for item, v in b.items():
            if item not in {"capitaux_propres"} and v["amount"] < 0:
                out.append(alert("montant_negatif", "attention", f"Solde négatif : {ITEMS[item][0]}",
                                 f"{fmt(v['amount'])} au {m} ({v['source_name']}).", period=m,
                                 explanation="Un solde de trésorerie négatif est normalement un découvert à classer au passif."))
        cp = b.get("capitaux_propres")
        if cp and cp["amount"] < 0:
            out.append(alert("capitaux_negatifs", "elevee", "Capitaux propres négatifs",
                             f"{fmt(cp['amount'])} au {m} : les pertes cumulées dépassent les apports.", period=m))

    # 4. Cohérence interne : actif = passif ; résultat déclaré = résultat recalculé
    for m, b in analysis["balances"].items():
        a, p = b.get("total_actif_calc"), b.get("total_passif_calc")
        if a and p and abs(a - p) / max(abs(a), 1) * 100 > THRESHOLDS["ecart_bilan_pct"]:
            out.append(alert("bilan_desequilibre", "elevee", "Bilan non équilibré",
                             f"Total actif {fmt(a)} ≠ total passif {fmt(p)} (écart {fmt(a - p)}).", period=m,
                             explanation="Un poste manque ou est mal classé ; les ratios de structure sont fragiles."))
        for side, calc in (("total_actif", a), ("total_passif", p)):
            decl = b.get(side)
            if decl is not None and calc and abs(decl - calc) / max(abs(calc), 1) * 100 > THRESHOLDS["ecart_bilan_pct"]:
                out.append(alert("total_incoherent", "attention", f"{ITEMS[side][0]} différent de la somme des postes",
                                 f"Déclaré {fmt(decl)}, recalculé {fmt(calc)}.", period=m))
    for m, p in analysis["pnl"].items():
        d, c = p.get("resultat_net_declare"), p.get("resultat_net")
        if d is not None and c is not None and abs(d - c) > max(1000, 0.02 * abs(c)):
            out.append(alert("resultat_incoherent", "attention", "Résultat déclaré différent du résultat recalculé",
                             f"Déclaré {fmt(d)}, recalculé à partir des postes {fmt(c)}.", period=m,
                             explanation="Une charge ou un produit n'a peut-être pas été transmis."))
    # Trésorerie nette (FR – BFR) vs trésorerie réelle (caisse + banque – découverts)
    B = analysis["balance_last"]
    if B.get("tresorerie_nette") is not None and B.get("tresorerie") is not None:
        real = B["tresorerie"] - (B.get("dettes_financieres_ct") or 0)
        if abs(real - B["tresorerie_nette"]) > max(10000, 0.05 * abs(real)):
            out.append(alert("tresorerie_incoherente", "info", "Trésorerie nette théorique ≠ trésorerie constatée",
                             f"FR – BFR = {fmt(B['tresorerie_nette'])} ; caisse + banque – découverts = {fmt(real)}.",
                             period=cov["last_balance"], explanation="Écart lié à des postes non transmis (autres créances/dettes)."))

    # 5. Variations inhabituelles et baisse prolongée du CA
    series = [r for r in analysis["monthly"] if r["ventes"] is not None]
    for r in series:
        if r["var_mom"] is not None and abs(r["var_mom"]) >= THRESHOLDS["variation_mensuelle_pct"]:
            sens = "hausse" if r["var_mom"] > 0 else "baisse"
            out.append(alert("variation_forte", "attention", f"Forte {sens} du chiffre d'affaires",
                             f"{r['var_mom']:+.1f} % entre {ym_add(r['month'], -1)} et {r['month']} "
                             f"(seuil ±{THRESHOLDS['variation_mensuelle_pct']:.0f} %).", period=r["month"],
                             explanation="Saison, rupture de stock, fermeture, grosse commande ponctuelle ? À expliquer par le commerçant."))
    run, start = 0, None
    best_run = (0, None, None)
    for i in range(1, len(series)):
        if series[i]["ventes"] < series[i - 1]["ventes"]:
            run, start = run + 1, start or series[i - 1]["month"]
            if run > best_run[0]:
                best_run = (run, start, series[i]["month"])
        else:
            run, start = 0, None
    if best_run[0] >= THRESHOLDS["baisse_consecutive_mois"]:
        s0 = next(r for r in series if r["month"] == best_run[1])["ventes"]
        s1 = next(r for r in series if r["month"] == best_run[2])["ventes"]
        out.append(alert("baisse_prolongee", "elevee" if best_run[0] >= 5 else "attention",
                         f"Baisse du CA pendant {best_run[0]} mois consécutifs",
                         f"De {fmt(s0)} ({best_run[1]}) à {fmt(s1)} ({best_run[2]}), soit {(s1 - s0) / s0 * 100:+.1f} %.",
                         period=f"{best_run[1]}..{best_run[2]}",
                         explanation="Une baisse n'est pas automatiquement un signe d'insolvabilité : saison creuse, perte de clients ?"))
    # Trésorerie nette constatée = caisse + banque – découverts
    tr = [(m, b["tresorerie"] - (b.get("dettes_financieres_ct") or 0)) for m, b in sorted(analysis["balances"].items())
          if b.get("tresorerie") is not None]
    if tr:
        m_last, v_last = tr[-1]
        neg = [m for m, v in tr if v < 0]
        if v_last < 0:
            first = next(m for m, v in tr if v < 0 and all(x < 0 for mm, x in tr if mm >= m))
            out.append(alert("tresorerie_negative", "elevee", "Trésorerie nette négative (découvert bancaire)",
                             f"Caisse + banque – découverts = {fmt(v_last)} en {m_last} ; négative depuis {first} "
                             f"({len(neg)} mois sur {len(tr)}).", period=f"{first}..{m_last}",
                             explanation="L'activité est financée par le découvert : tension de trésorerie à expliquer."))
        elif len(tr) >= 6 and max(v for _, v in tr[-6:]) > 0 and v_last < 0.5 * max(v for _, v in tr[-6:]):
            out.append(alert("tension_tresorerie", "attention", "Trésorerie en forte diminution",
                             f"Trésorerie nette de {fmt(v_last)} en {m_last}, contre un maximum de "
                             f"{fmt(max(v for _, v in tr[-6:]))} sur les 6 derniers mois.", period=m_last))

    # 6. Contrôles sur les transactions (grand livre)
    out += _transaction_checks(analysis, transactions, today)

    # 7. Documents en double (même empreinte SHA-256)
    by_hash = defaultdict(list)
    for d in documents:
        by_hash[d["sha256"]].append(d["filename"])
    for h, names in by_hash.items():
        if len(names) > 1:
            out.append(alert("document_double", "info", "Document importé plusieurs fois",
                             f"Fichier identique importé {len(names)} fois : {', '.join(names)}.",
                             explanation="Les valeurs n'ont été comptées qu'une fois."))

    out.sort(key=lambda a: (SEV_ORDER[a["severity"]], a["code"]))
    return out


def _transaction_checks(analysis: dict, txs: list[dict], today: date) -> list[dict]:
    out = []
    if not txs:
        return out
    # Dates impossibles
    bad = [t for t in txs if t["date"] is None or t["date"] > today or t["date"].year < 2000]
    if bad:
        out.append(alert("date_impossible", "attention", f"{len(bad)} opération(s) avec une date impossible",
                         "Exemples : " + "; ".join(f"{t['reference']} « {t['raw_date']} »" for t in bad[:5]),
                         evidence={"references": [t["reference"] for t in bad]}))
    # Montants négatifs dans les écritures
    neg = [t for t in txs if t["debit"] < 0 or t["credit"] < 0]
    if neg:
        out.append(alert("ecriture_negative", "attention", f"{len(neg)} écriture(s) avec un montant négatif",
                         "Exemples : " + "; ".join(f"{t['reference']} ({fmt(t['debit'] or t['credit'])})" for t in neg[:5])))
    # Doublons : même référence, ou même date + tiers + montant + compte
    groups = defaultdict(list)
    for t in txs:
        if t["date"] is None:
            continue
        groups[(t["date"], t["counterparty"].strip().lower(), t["account"], round(t["debit"] - t["credit"], 2))].append(t)
    dups = [g for g in groups.values() if len(g) > 1]
    by_ref = defaultdict(list)
    for t in txs:
        if t["reference"]:
            by_ref[(t["reference"], t["account"])].append(t)
    ref_dups = [g for g in by_ref.values() if len(g) > 1]
    if dups or ref_dups:
        examples = [f"{g[0]['reference']} · {g[0]['date']} · {g[0]['counterparty']} · {fmt(g[0]['debit'] or g[0]['credit'])} ×{len(g)}"
                    for g in (dups or ref_dups)[:6]]
        amount = sum((g[0]["debit"] or g[0]["credit"]) * (len(g) - 1) for g in dups)
        out.append(alert("doublons", "elevee", f"{len(dups) or len(ref_dups)} transaction(s) potentiellement en double",
                         "Même date, même tiers, même compte et même montant (ou même référence) : " + " ; ".join(examples),
                         explanation=f"Montant concerné : {fmt(amount)}. Peut être une double saisie ou une facture dupliquée — à vérifier sur pièces.",
                         evidence={"groups": [[t["reference"] for t in g] for g in dups + ref_dups]}))
    # Z-score sur les montants, par poste, après désaisonnalisation (montant / moyenne du mois)
    by_acc = defaultdict(list)
    for t in txs:
        item = match_account(t["account"])
        if t["date"] and item in {"ventes", "achats_marchandises", "autres_charges_externes", "transport", "loyers"}:
            by_acc[item].append(t)
    for item, ts in by_acc.items():
        if len(ts) < THRESHOLDS["zscore_min_obs"]:
            continue
        month_mean = defaultdict(list)
        for t in ts:
            month_mean[ym(t["date"])].append(abs(t["debit"] - t["credit"]))
        month_mean = {m: statistics.median(v) for m, v in month_mean.items()}
        rel = [abs(t["debit"] - t["credit"]) / month_mean[ym(t["date"])] if month_mean[ym(t["date"])] else 0 for t in ts]
        mu, sd = statistics.mean(rel), statistics.pstdev(rel)
        if sd == 0:
            continue
        outl = [(t, (r - mu) / sd) for t, r in zip(ts, rel) if abs(r - mu) / sd >= THRESHOLDS["zscore"]]
        if outl:
            outl.sort(key=lambda x: -abs(x[1]))
            out.append(alert("montant_inhabituel", "attention",
                             f"{len(outl)} montant(s) inhabituel(s) — {ITEMS[item][0]}",
                             " ; ".join(f"{t['reference']} du {t['date']} : {fmt(abs(t['debit'] - t['credit']))}, soit "
                                        f"{abs(t['debit'] - t['credit']) / month_mean[ym(t['date'])]:.1f} fois le montant habituel du mois (Z = {z:.1f})"
                                        for t, z in outl[:5]),
                             explanation="Montant très éloigné des habitudes du commerçant : grosse commande ? erreur de saisie ? Justificatif à demander.",
                             method=f"Z-score |Z| ≥ {THRESHOLDS['zscore']:.0f} sur {len(ts)} opérations (montant rapporté à la médiane du mois)"))
    # Comparaison des totaux : ventes du grand livre vs ventes déclarées
    gl_sales = defaultdict(float)
    for t in txs:
        if t["date"] and match_account(t["account"]) == "ventes":
            gl_sales[ym(t["date"])] += t["credit"] - t["debit"]
    gaps = []
    for m, tot in sorted(gl_sales.items()):
        decl = analysis["pnl"].get(m, {}).get("ventes")
        if decl and abs(tot - decl) / decl * 100 > THRESHOLDS["ecart_totaux_pct"]:
            gaps.append((m, tot, decl, (tot - decl) / decl * 100))
    if gaps:
        worst = max(abs(g[3]) for g in gaps)
        out.append(alert("ecart_grand_livre", "elevee" if worst > 10 else "attention",
                         f"Ventes du grand livre ≠ ventes de l'état financier ({len(gaps)} mois)",
                         " ; ".join(f"{m} : grand livre {fmt(t)} vs état {fmt(d)} ({e:+.1f} %)" for m, t, d, e in gaps),
                         explanation="Doublons, opérations non justifiées ou état financier incomplet : rapprocher les pièces.",
                         method=f"Comparaison des totaux mensuels (seuil {THRESHOLDS['ecart_totaux_pct']:.0f} %)"))
    return out


# Isolation Forest : testé sur le jeu de démonstration, il ne séparait pas les opérations
# (scores quasi identiques) et ne produisait que du bruit. Conservé hors du prototype :
# à réévaluer avec un vrai volume de transactions (voir README, « Après le Challenge »).
