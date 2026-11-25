"""Tests du moteur financier — dont l'exemple chiffré du guide Finance (section 9)."""
from datetime import date

import pytest

from backend.engine.anomalies import detect
from backend.engine.extract import extract, parse_amount, parse_period
from backend.engine.finance import analyse
from backend.engine.items import match_account, match_label
from backend.engine.scoring import rule_score


def v(item, amount, y=2026, m=1, status="declare"):
    import calendar
    return {"period_start": date(y, m, 1), "period_end": date(y, m, calendar.monthrange(y, m)[1]), "item": item,
            "amount": amount, "status": status, "source_name": "test", "source_label": item, "confidence": 1.0}


def test_exemple_du_guide_finance():
    """CA 3 000 000, charges 2 600 000, AC 2 000 000, PC 1 000 000, dettes fin. 1 500 000, CP 2 000 000."""
    vals = [v("ventes", 3_000_000), v("cout_ventes", 2_000_000), v("charges_personnel", 600_000),
            v("stocks", 1_200_000), v("tresorerie", 800_000), v("dettes_fournisseurs", 1_000_000),
            v("dettes_financieres_lt", 1_500_000), v("capitaux_propres", 2_000_000), v("immobilisations", 2_500_000)]
    a = analyse(vals)
    R = a["ratios_by_key"]
    # Résultat 400 000 sur un mois, annualisé ×12 → la marge reste 13,33 %
    assert R["marge_nette"]["value"] == pytest.approx(13.3333, abs=1e-3)
    assert R["liquidite_generale"]["value"] == pytest.approx(2.0)
    assert R["dettes_capitaux_propres"]["value"] == pytest.approx(0.75)
    assert a["coverage"]["annualised"] is True


def test_evolution_non_calculable_si_periode_precedente_nulle():
    a = analyse([v("ventes", 0, m=1), v("cout_ventes", 0, m=1), v("ventes", 1000, m=2), v("cout_ventes", 500, m=2)])
    r = a["ratios_by_key"]["evol_ca_mensuelle"]
    assert r["value"] is None and r["status"] == "non_calculable"


def test_trimestre_incomplet_non_compare():
    vals = []
    for m in range(1, 6):  # T1 complet, T2 incomplet (2 mois)
        vals += [v("ventes", 1000, m=m), v("cout_ventes", 600, m=m)]
    q = {x["quarter"]: x for x in analyse(vals)["quarterly"]}
    assert q["2026-T1"]["complete"] and q["2026-T1"]["ventes"] == 3000
    assert not q["2026-T2"]["complete"] and q["2026-T2"]["ventes"] is None and q["2026-T2"]["var_vs_prev"] is None


def test_ratio_non_calcule_sans_bilan():
    a = analyse([v("ventes", 1000), v("cout_ventes", 600)])
    assert a["ratios_by_key"]["liquidite_generale"]["value"] is None


def test_valeur_verifiee_prioritaire_et_conflit_signale():
    a = analyse([v("ventes", 1000, status="extrait"), v("ventes", 1200, status="verifie"), v("cout_ventes", 500)])
    assert a["ttm"]["ventes"] == 1200 * 12
    assert len(a["conflicts"]) == 1


def test_parse_amount_formats():
    assert parse_amount("1 234 567") == 1234567
    assert parse_amount("1.234.567") == 1234567
    assert parse_amount("(12 000)") == -12000
    assert parse_amount("-45 000 FCFA") == -45000
    assert parse_amount("1 234,50") == 1234.5
    assert parse_amount("abc") is None


def test_parse_period_formats():
    assert parse_period("2026-03") == (date(2026, 3, 1), date(2026, 3, 31))
    assert parse_period("févr. 2026") == (date(2026, 2, 1), date(2026, 2, 28))
    assert parse_period("T2 2026") == (date(2026, 4, 1), date(2026, 6, 30))
    assert parse_period("Poste") is None


def test_normalisation_libelles_et_comptes():
    assert match_label("Chiffre d'affaires")[0] == "ventes"
    assert match_label("Trésorerie (caisse + banque)")[0] == "tresorerie"
    assert match_label("Dépenses diverses non classées")[0] is None  # jamais additionné
    assert match_account("6031") == "variation_stocks"
    assert match_account("601") == "achats_marchandises"
    assert match_account("701") == "ventes"


def test_doublons_et_date_impossible():
    csv = ("date;reference;tiers;libelle;compte;debit;credit\n"
           "02/01/2026;VT-1;Client;Vente;701;;150000\n02/01/2026;VT-1;Client;Vente;701;;150000\n"
           "31/02/2026;CH-1;Transport;Transport;618;45000;\n").encode()
    ex = extract("journal.csv", csv)
    assert ex.kind == "grand_livre" and len(ex.transactions) == 3
    a = analyse([v("ventes", 300_000), v("cout_ventes", 200_000), v("tresorerie", 100_000)])
    codes = {x["code"] for x in detect(a, ex.transactions, [], date(2026, 11, 25))}
    assert {"doublons", "date_impossible"} <= codes


def test_baisse_prolongee_et_score_explique():
    vals = []
    for i, m in enumerate(range(1, 7)):
        vals += [v("ventes", 2_500_000 - 200_000 * i, m=m), v("cout_ventes", 1_800_000 - 150_000 * i, m=m)]
    a = analyse(vals)
    alerts = detect(a, [], [], date(2026, 11, 25))
    assert any(x["code"] == "baisse_prolongee" for x in alerts)
    s = rule_score(a, alerts)
    assert s["score"] is not None and s["explanations"]
    assert any(d["note"] is None for d in s["dimensions"])  # liquidité sans bilan : non calculable, signalé


def test_releve_mobile_money_justifie_le_solde():
    csv = ("date;type;montant;solde\n05/03/2026 10:12;Paiement reçu;150000;450000\n"
           "20/03/2026;Retrait;-50000;400000\n02/04/2026;Paiement reçu;80000;480000\n").encode()
    ex = extract("releve_momo.csv", csv)
    assert ex.kind == "releve_mobile_money" and len(ex.transactions) == 3
    soldes = {v["period_end"].month: (v["amount"], v["status"]) for v in ex.values}
    assert soldes == {3: (400000, "justifie"), 4: (480000, "justifie")}


def test_tresorerie_en_hausse_quand_les_ventes_baissent():
    vals = []
    for i, m in enumerate(range(1, 7)):
        vals += [v("ventes", 3_000_000 - 300_000 * i, m=m), v("cout_ventes", 2_000_000 - 200_000 * i, m=m),
                 v("tresorerie", 500_000 + 400_000 * i, m=m)]
    alerts = detect(analyse(vals), [], [], date(2026, 11, 25))
    a = next(x for x in alerts if x["code"] == "tresorerie_vs_ventes")
    assert a["questions"] and "trésorerie" in a["title"].lower()


def test_recalibrage_sur_le_taux_local():
    from backend.engine.scoring import recalibrate
    assert recalibrate(0.2, 0.069, 0.069) == pytest.approx(0.2)
    assert recalibrate(0.2, 0.069, 0.03) < 0.2 < recalibrate(0.2, 0.069, 0.12)
