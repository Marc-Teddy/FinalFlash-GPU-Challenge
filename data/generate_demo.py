"""Générateur du jeu de démonstration : trois commerçants FICTIFS, données cohérentes.

  A — Boutique de vêtements (Cotonou) : ventes stables et saisonnières, trésorerie positive,
      endettement maîtrisé. 24 mois. Logiciel comptable → export XLSX + grand livre CSV.
  B — Quincaillerie (Porto-Novo) : baisse progressive du CA, tension de trésorerie, découvert.
      12 mois. États financiers transmis en PDF par un cabinet → extraction automatique.
  C — Alimentation générale (Parakou) : pas de logiciel. Journal de caisse / mobile money CSV
      avec doublons, montant inhabituel et date impossible + balance mensuelle CSV.

Les bilans sont reconstruits mois par mois (actif = passif par construction) : la trésorerie
est le solde des flux. Graine fixe : le jeu est reproductible.
Usage : python data/generate_demo.py
"""
from __future__ import annotations

import calendar
import csv
import random
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent / "demo"

PNL_ROWS = [
    ("ventes", "Chiffre d'affaires"),
    ("achats_marchandises", "Achats de marchandises"),
    ("variation_stocks", "Variation des stocks de marchandises"),
    ("transport", "Transports"),
    ("loyers", "Loyers"),
    ("autres_charges_externes", "Autres charges externes"),
    ("impots_taxes", "Impôts et taxes"),
    ("charges_personnel", "Charges de personnel"),
    ("dotations_amortissements", "Dotations aux amortissements"),
    ("charges_financieres", "Charges financières"),
    ("impot_resultat", "Impôt sur le résultat"),
    ("resultat_net", "Résultat net"),
    ("remboursement_emprunts", "Remboursement des emprunts"),
]
BAL_ROWS = [
    ("immobilisations", "Immobilisations nettes"),
    ("stocks", "Stocks de marchandises"),
    ("creances_clients", "Créances clients"),
    ("tresorerie", "Trésorerie (caisse + banque)"),
    ("total_actif", "Total actif"),
    ("capitaux_propres", "Capitaux propres"),
    ("dettes_financieres_lt", "Emprunts et dettes financières"),
    ("dettes_financieres_ct", "Découverts bancaires"),
    ("dettes_fournisseurs", "Dettes fournisseurs"),
    ("dettes_fiscales_sociales", "Dettes fiscales et sociales"),
    ("total_passif", "Total passif"),
]


def months(start: tuple[int, int], n: int) -> list[str]:
    y, m = start
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def simulate(cfg: dict, rng: random.Random) -> tuple[list[str], dict, dict]:
    ms = months(cfg["start"], cfg["n"])
    pnl, bal = {}, {}
    I, S, C, cash = cfg["immo"], cfg["stock0"], cfg["cred0"], cfg["cash0"]
    D, F, X = cfg["debt0"], cfg["fourn0"], cfg["fisc0"]
    E = I + S + C + cash - D - F - X  # capitaux propres d'ouverture (équilibre)
    for i, m in enumerate(ms):
        mo = int(m[5:7])
        v = cfg["sales"](i, mo) * rng.uniform(0.96, 1.04)
        v = round(v, -3)
        cogs = v * (1 - cfg["gm"])
        # Stock lissé : le commerçant réapprovisionne progressivement (pas d'achats négatifs)
        S_new = 0.6 * S + 0.4 * cfg["stock_days"](i) / 30 * cogs
        achats = cogs + (S_new - S)
        var = S - S_new
        C_new = v * cfg["cred_ratio"]
        F_new = achats * cfg["fourn_ratio"]
        X_new = v * 0.02
        dep = cfg["dep"]
        interest = D * cfg["rate"] / 12
        principal = min(D, cfg["principal"])
        charges = {"transport": v * 0.025, "loyers": cfg["rent"], "autres_charges_externes": v * 0.02 + 15000,
                   "impots_taxes": v * 0.01, "charges_personnel": cfg["staff"]}
        rex = v - cogs - sum(charges.values()) - dep
        tax = max(0.0, (rex - interest) * 0.25) if cfg.get("tax", True) else 0.0
        rn = rex - interest - tax
        W = cfg["withdrawal"]  # prélèvements de l'exploitant
        cash = cash + rn + dep - (S_new - S) - (C_new - C) + (F_new - F) + (X_new - X) - principal - W
        I, S, C, F, X, D, E = I - dep, S_new, C_new, F_new, X_new, D - principal, E + rn - W
        overdraft = 0.0
        if cash < 0:
            overdraft, cash_pos = -cash, 0.0
        else:
            cash_pos = cash
        r = lambda x: round(x)  # noqa: E731
        p = {"ventes": r(v), "achats_marchandises": r(achats), "variation_stocks": r(var), **{k: r(x) for k, x in charges.items()},
             "dotations_amortissements": r(dep), "charges_financieres": r(interest), "impot_resultat": r(tax),
             "remboursement_emprunts": r(principal)}
        p["resultat_net"] = p["ventes"] - p["achats_marchandises"] - p["variation_stocks"] - sum(p[k] for k in charges) \
            - p["dotations_amortissements"] - p["charges_financieres"] - p["impot_resultat"]
        b = {"immobilisations": r(I), "stocks": r(S), "creances_clients": r(C), "tresorerie": r(cash_pos),
             "dettes_financieres_lt": r(D), "dettes_financieres_ct": r(overdraft), "dettes_fournisseurs": r(F),
             "dettes_fiscales_sociales": r(X)}
        b["total_actif"] = b["immobilisations"] + b["stocks"] + b["creances_clients"] + b["tresorerie"]
        # Capitaux propres = solde (absorbe les arrondis, comme une écriture d'écart d'arrondi)
        b["capitaux_propres"] = b["total_actif"] - b["dettes_financieres_lt"] - b["dettes_financieres_ct"] \
            - b["dettes_fournisseurs"] - b["dettes_fiscales_sociales"]
        b["total_passif"] = b["total_actif"]
        pnl[m], bal[m] = p, b
    return ms, pnl, bal


SEASON_CLOTHES = {1: 0.85, 2: 0.9, 3: 1.0, 4: 1.0, 5: 0.95, 6: 1.05, 7: 0.95, 8: 0.9, 9: 1.15, 10: 1.0, 11: 1.05, 12: 1.35}

COMPANIES = {
    "A": dict(name="Boutique Akwaba Mode", sector="Commerce de vêtements", city="Cotonou",
              start=(2024, 11), n=24, gm=0.38, immo=5_500_000, stock0=5_000_000, cred0=400_000, cash0=1_500_000,
              debt0=4_800_000, fourn0=1_800_000, fisc0=120_000, rate=0.14, principal=110_000, dep=60_000,
              rent=180_000, staff=320_000, withdrawal=150_000, cred_ratio=0.10, fourn_ratio=0.9,
              sales=lambda i, mo: 3_000_000 * SEASON_CLOTHES[mo] * (1 + 0.006 * i), stock_days=lambda i: 75),
    "B": dict(name="Quincaillerie La Solidité", sector="Quincaillerie", city="Porto-Novo",
              start=(2025, 11), n=12, gm=0.27, immo=4_000_000, stock0=5_500_000, cred0=900_000, cash0=1_400_000,
              debt0=3_600_000, fourn0=1_900_000, fisc0=60_000, rate=0.16, principal=125_000, dep=45_000,
              rent=150_000, staff=260_000, withdrawal=150_000, cred_ratio=0.35, fourn_ratio=0.9,
              sales=lambda i, mo: [2_600_000, 2_750_000, 2_500_000, 2_450_000, 2_300_000, 2_150_000, 2_000_000,
                                   1_900_000, 1_750_000, 1_650_000, 1_550_000, 1_500_000][i],
              stock_days=lambda i: 85 + 4 * i),
    "C": dict(name="Alimentation Générale Le Bon Prix", sector="Alimentation générale", city="Parakou",
              start=(2025, 11), n=12, gm=0.18, immo=1_200_000, stock0=2_600_000, cred0=0, cash0=900_000,
              debt0=0, fourn0=600_000, fisc0=30_000, rate=0.0, principal=0, dep=20_000,
              rent=90_000, staff=150_000, withdrawal=180_000, cred_ratio=0.0, fourn_ratio=0.15,
              sales=lambda i, mo: 4_200_000 * (1.12 if mo in (12, 3, 4) else 1.0), stock_days=lambda i: 22),
}


def fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def write_xlsx(path: Path, cfg: dict, ms: list[str], pnl: dict, bal: dict) -> None:
    wb = Workbook()
    for title, rows, data in (("Compte de résultat", PNL_ROWS, pnl), ("Bilan", BAL_ROWS, bal)):
        ws = wb.active if title == "Compte de résultat" else wb.create_sheet()
        ws.title = title
        ws.append([f"{cfg['name']} — {title} mensuel (export logiciel comptable, montants en FCFA)"])
        ws["A1"].font = Font(bold=True)
        ws.append([])
        ws.append(["Poste"] + ms)
        for c in ws[3]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E79")
        for key, label in rows:
            ws.append([label] + [data[m][key] for m in ms])
        ws.column_dimensions["A"].width = 38
    wb.save(path)


def ledger_rows(cfg_key: str, ms: list[str], pnl: dict, rng: random.Random) -> list[dict]:
    """Grand livre simplifié : ventes journalières (701/571 ou 521 mobile money), achats, charges."""
    rows, n = [], 0
    tiers_sales = ["Client comptant", "Client mobile money", "Client comptant"]
    suppliers = ["Grossiste Dantokpa", "Import Lomé SARL", "Fournisseur Cotonou Textiles"] if cfg_key == "A" else \
        ["Grossiste Parakou Vivres", "Brasserie distribution", "Huilerie du Nord", "Sucrerie distribution"]
    for m in ms:
        y, mo = int(m[:4]), int(m[5:7])
        ndays = calendar.monthrange(y, mo)[1]
        days = [d for d in range(1, ndays + 1) if date(y, mo, d).weekday() != 6]
        # ventes : répartir exactement le CA du mois
        weights = [rng.uniform(0.6, 1.4) for _ in days]
        total = pnl[m]["ventes"]
        amounts = [int(round(total * w / sum(weights), -2)) for w in weights]
        amounts[-1] += total - sum(amounts)
        for d, a in zip(days, amounts):
            n += 1
            rows.append({"date": f"{d:02d}/{mo:02d}/{y}", "reference": f"VT-{m.replace('-', '')}-{n:05d}",
                         "tiers": rng.choice(tiers_sales), "libelle": "Ventes du jour", "compte": "701",
                         "debit": "", "credit": a})
        # achats : 4 factures par mois
        ach = pnl[m]["achats_marchandises"]
        parts = [int(round(ach * w, -2)) for w in (0.3, 0.25, 0.25)]
        parts.append(ach - sum(parts))
        for k, a in enumerate(parts):
            n += 1
            rows.append({"date": f"{min(ndays, 3 + 7 * k):02d}/{mo:02d}/{y}", "reference": f"FA-{m.replace('-', '')}-{k + 1:02d}",
                         "tiers": rng.choice(suppliers), "libelle": "Achat de marchandises", "compte": "601",
                         "debit": a, "credit": ""})
        for acc, key, lib, tiers in (("622", "loyers", "Loyer boutique", "Bailleur"),
                                     ("661", "charges_personnel", "Salaires du mois", "Personnel"),
                                     ("618", "transport", "Transport marchandises", "Transporteur zem / camion")):
            n += 1
            rows.append({"date": f"{min(ndays, 28):02d}/{mo:02d}/{y}", "reference": f"CH-{m.replace('-', '')}-{acc}",
                         "tiers": tiers, "libelle": lib, "compte": acc, "debit": pnl[m][key], "credit": ""})
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str], sep: str = ";") -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=sep)
        w.writeheader()
        w.writerows(rows)


def write_pdf(path: Path, cfg: dict, ms: list[str], pnl: dict, bal: dict) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=24)
    story = []
    y0, m0 = int(ms[0][:4]), int(ms[0][5:7])
    y1, m1 = int(ms[-1][:4]), int(ms[-1][5:7])
    period = f"du 01/{m0:02d}/{y0} au {calendar.monthrange(y1, m1)[1]}/{m1:02d}/{y1}"
    for title, rows, data in (("Compte de résultat mensuel", PNL_ROWS, pnl), ("Bilan mensuel (fin de mois)", BAL_ROWS, bal)):
        for half in (ms[:6], ms[6:]):
            story.append(Paragraph(f"<b>{cfg['name']}</b> — {cfg['city']} · Cabinet comptable (fictif)", styles["Normal"]))
            story.append(Paragraph(f"{title} — période {period} — montants en FCFA", styles["Heading3"]))
            tbl = [["Poste"] + half] + [[label] + [fmt(data[m][key]) for m in half] for key, label in rows]
            t = Table(tbl, colWidths=[200] + [92] * len(half))
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
            story += [t, Spacer(1, 10), Paragraph("Document fictif généré pour la démonstration CreditWise.", styles["Italic"]), PageBreak()]
    doc.build(story[:-1])


def main() -> None:
    rng = random.Random(2026)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}
    for key, cfg in COMPANIES.items():
        ms, pnl, bal = simulate(cfg, rng)
        d = OUT / key
        d.mkdir(exist_ok=True)
        for f in d.iterdir():
            f.unlink()
        if key == "A":
            write_xlsx(d / "A_etats_financiers_mensuels.xlsx", cfg, ms, pnl, bal)
            write_csv(d / "A_grand_livre.csv", ledger_rows(key, ms, pnl, rng),
                      ["date", "reference", "tiers", "libelle", "compte", "debit", "credit"])
        elif key == "B":
            write_pdf(d / "B_etats_financiers_cabinet.pdf", cfg, ms, pnl, bal)
        else:
            # Balance mensuelle (comptes SYSCOHADA-like) issue du cahier de caisse
            accounts = [("701", "Ventes de marchandises", "ventes", -1), ("601", "Achats de marchandises", "achats_marchandises", 1),
                        ("6031", "Variation des stocks", "variation_stocks", 1), ("618", "Transports", "transport", 1),
                        ("622", "Loyers", "loyers", 1), ("638", "Autres charges externes", "autres_charges_externes", 1),
                        ("641", "Impôts et taxes", "impots_taxes", 1), ("661", "Salaires", "charges_personnel", 1),
                        ("681", "Dotations aux amortissements", "dotations_amortissements", 1),
                        ("891", "Impôt sur le résultat", "impot_resultat", 1)]
            bal_acc = [("244", "Matériel et mobilier", "immobilisations", 1), ("311", "Marchandises", "stocks", 1),
                       ("571", "Caisse", "tresorerie", 1), ("101", "Capital et compte de l'exploitant", "capitaux_propres", -1),
                       ("401", "Fournisseurs", "dettes_fournisseurs", -1), ("441", "État, impôts", "dettes_fiscales_sociales", -1)]
            rows = []
            for m in ms:
                for acc, lib, k, sgn in accounts:
                    a = pnl[m][k]
                    rows.append({"periode": m, "compte": acc, "intitule": lib,
                                 "debit": a if (sgn > 0) == (a >= 0) else "", "credit": abs(a) if (sgn > 0) != (a >= 0) else ""})
                for acc, lib, k, sgn in bal_acc:
                    a = bal[m][k]
                    rows.append({"periode": m, "compte": acc, "intitule": lib,
                                 "debit": a if sgn > 0 else "", "credit": a if sgn < 0 else ""})
            # Anomalie volontaire : loyer du 6e mois non transmis (poste oublié)
            rows = [r for r in rows if not (r["periode"] == ms[5] and r["compte"] == "622")]
            write_csv(d / "C_balance_mensuelle.csv", rows, ["periode", "compte", "intitule", "debit", "credit"])
            led = ledger_rows(key, ms, pnl, rng)
            # Anomalies volontaires : doublons, montant inhabituel, date impossible
            sales = [r for r in led if r["compte"] == "701"]
            for r in rng.sample(sales, 4):
                led.append(dict(r))  # double saisie exacte
            purchases = [r for r in led if r["compte"] == "601"]
            dup = dict(rng.choice(purchases))
            dup["reference"] = dup["reference"] + "-bis"  # facture fournisseur dupliquée sous une autre référence
            led.append(dup)
            big = rng.choice([r for r in sales if r["date"].endswith("2026")])
            led.append({**big, "reference": "VT-EXC-0001", "credit": 2_850_000, "libelle": "Vente en gros (non justifiée)"})
            led.append({"date": "31/02/2026", "reference": "CH-ERR-0001", "tiers": "Transporteur zem / camion",
                        "libelle": "Transport marchandises", "compte": "618", "debit": 45_000, "credit": ""})
            led.sort(key=lambda r: (r["date"][6:], r["date"][3:5], r["date"][:2]))
            write_csv(d / "C_journal_caisse_mobile_money.csv", led,
                      ["date", "reference", "tiers", "libelle", "compte", "debit", "credit"])
        meta[key] = {"name": cfg["name"], "months": f"{ms[0]} → {ms[-1]}",
                     "ventes_total": sum(pnl[m]["ventes"] for m in ms[-12:]),
                     "tresorerie_fin": bal[ms[-1]]["tresorerie"], "decouvert_fin": bal[ms[-1]]["dettes_financieres_ct"]}
    for k, v in meta.items():
        print(k, v)


if __name__ == "__main__":
    main()
