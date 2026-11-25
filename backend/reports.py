"""Génération des PDF : rapport d'analyse (institution) et dossier financier sécurisé (commerçant)."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .engine.items import ITEMS

NAVY = colors.HexColor("#0b2545")
ORANGE = colors.HexColor("#f26a00")
LOGO = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "logo-report.jpg"


def _logo():
    """Logo CreditWise en tête de document (largeur 4,2 cm)."""
    if not LOGO.exists():
        return Spacer(1, 1)
    img = Image(str(LOGO), width=4.2 * cm, height=4.2 * cm * 337 / 600)
    img.hAlign = "LEFT"
    return img
SEV = {"elevee": ("Élevée", colors.HexColor("#b42318")), "attention": ("Attention", colors.HexColor("#b54708")),
       "info": ("Info", colors.HexColor("#475467"))}
SS = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=SS["Heading1"], textColor=NAVY, fontSize=17, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=SS["Heading2"], textColor=NAVY, fontSize=12.5, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("p", parent=SS["BodyText"], fontSize=9, leading=12)
SMALL = ParagraphStyle("s", parent=P, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#475467"))
CELL = ParagraphStyle("c", parent=P, fontSize=8, leading=10)


def money(x):
    return "-" if x is None else f"{x:,.0f}".replace(",", " ") + " FCFA"


def fmt_ratio(r):
    v = r["value"]
    if v is None:
        return "Non calculable"
    if r["unit"] == "FCFA":
        return money(v)
    if r["unit"] == "%":
        return f"{v:.1f} %".replace(".", ",")
    if r["unit"] == "jours":
        return f"{v:.0f} jours"
    return f"{v:.2f}".replace(".", ",")


def _table(rows, widths, header=True, zebra=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd")),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    if zebra:
        st += [("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")])]
    t.setStyle(TableStyle(st))
    return t


def _chart(a) -> Drawing:
    """Graphique mensuel dessiné avec reportlab : CA en barres, résultat net et trésorerie nette en lignes."""
    ms = a["monthly"][-24:]
    W, H, left, bottom, top = 17.5 * cm, 6.3 * cm, 38, 30, 22
    pw, ph = W - left - 8, H - bottom - top
    series = [r["ventes"] or 0 for r in ms] + [r["resultat_net"] or 0 for r in ms] + \
             [r["tresorerie_nette_constatee"] or 0 for r in ms]
    lo, hi = min(0, min(series)), max(series) or 1
    y = lambda v: bottom + (v - lo) / (hi - lo) * ph  # noqa: E731
    d = Drawing(W, H)
    step = pw / max(len(ms), 1)
    for k in range(5):  # graduations en millions
        v = lo + (hi - lo) * k / 4
        d.add(Line(left, y(v), left + pw, y(v), strokeColor=colors.HexColor("#e3e6ea"), strokeWidth=0.5))
        d.add(String(left - 4, y(v) - 3, f"{v / 1e6:.1f}".replace(".", ","), fontSize=6.5, textAnchor="end", fillColor=colors.HexColor("#555")))
    d.add(Line(left, y(0), left + pw, y(0), strokeColor=colors.HexColor("#888"), strokeWidth=0.7))
    for i, r in enumerate(ms):
        x0 = left + i * step + step * 0.18
        if r["ventes"]:
            d.add(Rect(x0, y(0), step * 0.64, y(r["ventes"]) - y(0), fillColor=colors.HexColor("#1d4e89"), strokeColor=None))
        if i % max(1, len(ms) // 12) == 0:
            d.add(String(left + i * step + step / 2, bottom - 11, r["month"][2:], fontSize=6, textAnchor="middle", fillColor=colors.HexColor("#555")))
    for key, col, dash in (("resultat_net", "#e06000", None), ("tresorerie_nette_constatee", "#0f7a55", (3, 2))):
        pts = [(left + i * step + step / 2, y(r[key])) for i, r in enumerate(ms) if r[key] is not None]
        if len(pts) > 1:
            d.add(PolyLine([c for p in pts for c in p], strokeColor=colors.HexColor(col), strokeWidth=1.4, strokeDashArray=dash))
    legend = [("Chiffre d'affaires (millions FCFA)", "#1d4e89"), ("Résultat net", "#e06000"), ("Trésorerie nette (caisse + banque - découverts)", "#0f7a55")]
    x = left
    for label, col in legend:
        d.add(Rect(x, H - 12, 8, 6, fillColor=colors.HexColor(col), strokeColor=None))
        d.add(String(x + 11, H - 11.5, label, fontSize=7, fillColor=colors.HexColor("#333")))
        x += 22 + len(label) * 3.4
    return d


def _footer(text):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(1.6 * cm, 1.0 * cm, text)
        canvas.drawRightString(A4[0] - 1.6 * cm, 1.0 * cm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def analysis_report(a: dict, request: dict | None, analyst: str, decision: dict | None) -> bytes:
    buf = io.BytesIO()
    fingerprint = hashlib.sha256(json.dumps({"ratios": a["ratios"], "alerts": a["alerts"]}, sort_keys=True, default=str)
                                 .encode()).hexdigest()[:16]
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm,
                            title=f"CreditWise, rapport d'analyse : {a['company']['name']}")
    c, cov, s, pdm = a["company"], a["coverage"], a["score"], a["pd"]
    el = [_logo(), Spacer(1, 6)]
    el.append(Paragraph("Rapport d'analyse de crédit", H1))
    el.append(Paragraph(f"<b>{c['name']}</b>, {c.get('sector') or ''}, {c.get('city') or ''}. "
                        f"Généré le {datetime.now():%d/%m/%Y à %H:%M} pour {analyst}. Empreinte de l'analyse : {fingerprint}.", P))
    if request:
        el.append(Paragraph(f"Demande : <b>{money(request['amount'])}</b> sur {request['duration_months']} mois au taux annuel de "
                            f"{request['annual_rate'] * 100:.1f} %. Objet : {request.get('purpose') or 'non précisé'}. "
                            f"Échéance mensuelle estimée : {money(a['credit']['new_installment'])}.", P))
    # Synthèse
    el.append(Paragraph("1. Synthèse", H2))
    R = {r["key"]: r for r in a["ratios"]}
    syn = [["Indicateur", "Valeur", "Lecture"],
           ["Score de risque (règles)", "-" if s["score"] is None else f"{s['score']:.0f} / 100", Paragraph(s["category"], CELL)],
           ["PD indicative (modèle)", f"{pdm['pd'] * 100:.1f} %" if pdm.get("available") else "Non disponible",
            Paragraph(f"{pdm['relative_to_base']:.2f} × le taux de défaut moyen du jeu d'entraînement" if pdm.get("available")
                      else pdm.get("reason", ""), CELL)]]
    for k in ["evol_ca_trimestrielle", "marge_nette", "liquidite_generale", "dettes_capitaux_propres", "dscr_avec_credit"]:
        syn.append([Paragraph(R[k]["label"], CELL), fmt_ratio(R[k]), Paragraph(R[k]["interpretation"] if R[k]["value"] is not None else R[k]["reason"], CELL)])
    el.append(_table(syn, [5.4 * cm, 3.2 * cm, 9.2 * cm]))
    for e in s["explanations"]:
        el.append(Paragraph("• " + e, P))
    el.append(Paragraph("Ces éléments éclairent la décision ; ils ne la remplacent pas. Aucune décision automatique de crédit.", SMALL))

    # Couverture
    el.append(Paragraph("2. Période couverte et documents", H2))
    el.append(Paragraph(f"Données de {cov['first_month']} à {cov['last_month']}, {cov['n_months_pnl']} mois de compte de résultat, "
                        f"dernier bilan : {cov['last_balance'] or 'aucun'}. Mois manquants : {', '.join(cov['missing_months']) or 'aucun'}. "
                        + ("Montants annuels <b>annualisés</b> (moins de 12 mois). " if cov["annualised"] else "")
                        + "Statut des valeurs utilisées : " + ", ".join(f"{k} {v}" for k, v in cov["status_counts"].items()) + ".", P))
    rows = [["Document attendu", "Reçu", "Remarque"]] + [[x["document"], "Oui" if x["ok"] else "Non", Paragraph(x.get("note", ""), CELL)]
                                                         for x in a["checklist"]]
    el.append(_table(rows, [7.5 * cm, 1.6 * cm, 8.7 * cm]))
    docs = [["Fichier importé", "Type", "Valeurs", "Opérations", "Importé le"]] + [
        [Paragraph(d["filename"], CELL), d["kind"], str(d["n_values"]), str(d["n_transactions"]), d["uploaded_at"][:16]] for d in a["documents"]]
    el.append(Spacer(1, 4))
    el.append(_table(docs, [6.5 * cm, 3.6 * cm, 1.8 * cm, 2.1 * cm, 3.8 * cm]))

    # Évolution
    el.append(Paragraph("3. Évolution mensuelle et trimestrielle", H2))
    el.append(_chart(a))
    qrows = [["Trimestre", "Chiffre d'affaires", "vs trimestre préc.", "vs même trimestre N-1"]]
    for q in a["quarterly"]:
        qrows.append([q["quarter"] + ("" if q["complete"] else f" (incomplet : {q['months']} mois)"), money(q["ventes"]),
                      "-" if q["var_vs_prev"] is None else f"{q['var_vs_prev']:+.1f} %".replace(".", ","),
                      "-" if q["var_yoy"] is None else f"{q['var_yoy']:+.1f} %".replace(".", ",")])
    el.append(_table(qrows, [5 * cm, 4.4 * cm, 4 * cm, 4.4 * cm]))
    el.append(Paragraph("Les trimestres incomplets ne sont pas comparés (périodes de durées différentes).", SMALL))

    # Ratios
    el.append(Paragraph("4. Ratios financiers et formules", H2))
    rr = [["Ratio", "Valeur", "Formule"]] + [[Paragraph(r["label"], CELL), fmt_ratio(r), Paragraph(r["formula"] + (
        f". <i>{r['reason']}</i>" if r["value"] is None else ""), CELL)] for r in a["ratios"]]
    el.append(_table(rr, [5.4 * cm, 3.2 * cm, 9.2 * cm]))

    # Alertes
    el.append(Paragraph(f"5. Anomalies et points de vigilance ({len(a['alerts'])})", H2))
    if not a["alerts"]:
        el.append(Paragraph("Aucune anomalie détectée par les contrôles programmés.", P))
    ar = [["Sévérité", "Alerte", "Raison du signalement"]]
    for x in a["alerts"]:
        lab, col = SEV[x["severity"]]
        ar.append([Paragraph(f"<font color='{col.hexval()}'><b>{lab}</b></font>", CELL), Paragraph(x["title"], CELL),
                   Paragraph(x["reason"] + (f"<br/><i>{x['explanation']}</i>" if x.get("explanation") else "")
                             + f"<br/><font size=6.5 color='#667085'>Méthode : {x['method']}</font>", CELL)])
    if a["alerts"]:
        el.append(_table(ar, [1.9 * cm, 4.6 * cm, 11.3 * cm]))
    el.append(Paragraph("Une anomalie mérite une vérification ; elle ne prouve pas une fraude.", SMALL))

    # Score
    el.append(Paragraph("6. Détail du score de risque (règles explicables)", H2))
    sr = [["Dimension (poids)", "Critère", "Valeur", "Note", "Règle"]]
    for d in s["dimensions"]:
        note = "-" if d["note"] is None else f"{d['note']:.0f}"
        for i, x in enumerate(d["details"]):
            sr.append([Paragraph(f"<b>{d['label']}</b> ({d['weight'] * 100:.0f} %) : {note}/100", CELL) if i == 0 else "",
                       Paragraph(x["criterion"], CELL), x["value"] or "n.c.", "-" if x["note"] is None else f"{x['note']:.0f}",
                       Paragraph(x["rule"], CELL)])
    el.append(_table(sr, [4.6 * cm, 4.2 * cm, 2.9 * cm, 1.2 * cm, 4.9 * cm], zebra=False))
    el.append(Paragraph(s["weights_note"], SMALL))

    # PD
    el.append(Paragraph("7. Probabilité de défaut indicative (modèle statistique)", H2))
    if pdm.get("available"):
        ds, m, b = pdm["dataset"], pdm["metrics"], pdm["baseline_metrics"]
        el.append(Paragraph(f"PD estimée : <b>{pdm['pd'] * 100:.1f} %</b> à un an ({pdm['variant_label']}). Modèle {pdm['model']} entraîné sur "
                            f"<b>données réelles</b> : {ds['name']} ({ds['rows']} entreprises, licence {ds['license']}). "
                            f"Test : ROC-AUC {m['roc_auc']:.3f}, PR-AUC {m['pr_auc']:.3f} (régression logistique de référence : "
                            f"{b['roc_auc']:.3f} / {b['pr_auc']:.3f}).", P))
        fr = [["Facteur principal", "Valeur", "Effet"]] + [[Paragraph(f["label"], CELL), f"{f['value']}" + (" (imputé)" if f["imputed"] else ""),
                                                            f["effect"]] for f in pdm["factors"]]
        el.append(_table(fr, [9 * cm, 3.5 * cm, 5.3 * cm]))
        if pdm.get("expected_loss"):
            e = pdm["expected_loss"]
            el.append(Paragraph(f"Perte attendue indicative EL = PD × LGD × EAD = {e['pd'] * 100:.1f} % × {e['lgd'] * 100:.0f} % × "
                                f"{money(e['ead'])} = <b>{money(e['el'])}</b> (LGD de 45 % : hypothèse de travail).", P))
        for lim in pdm["limits"]:
            el.append(Paragraph("• " + lim, SMALL))
    else:
        el.append(Paragraph(pdm.get("reason", "Non disponible."), P))

    # Limites et décision
    el.append(Paragraph("8. Limites de l'analyse", H2))
    for lim in a["limits"]:
        el.append(Paragraph("• " + lim, P))
    el.append(Paragraph("9. Décision de l'analyste", H2))
    if decision:
        el.append(KeepTogether([Paragraph(f"<b>{decision['decision']}</b>, par {decision['analyst']} le {decision['decided_at'][:16]}.", P),
                                Paragraph("Motif : " + decision["comment"], P)]))
    else:
        el.append(Paragraph("Aucune décision enregistrée à la date du rapport. Décision réservée à un analyste habilité.", P))
    doc.build(el, onFirstPage=_footer(f"CreditWise, document confidentiel : {c['name']}"),
              onLaterPages=_footer(f"CreditWise, document confidentiel : {c['name']}"))
    return buf.getvalue()


def dossier_pdf(a: dict, payload: dict, password: str | None = None) -> bytes:
    """Dossier financier du commerçant : synthèse lisible + données normalisées signées en pièce jointe."""
    from pypdf import PdfReader, PdfWriter

    buf = io.BytesIO()
    c, cov = a["company"], a["coverage"]
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm,
                            title=f"Dossier financier : {c['name']}")
    el = [_logo(), Spacer(1, 6), Paragraph("Dossier financier", H1),
          Paragraph(f"<b>{c['name']}</b>, {c.get('sector') or ''}, {c.get('city') or ''}. Exporté le {datetime.now():%d/%m/%Y à %H:%M}.", P),
          Paragraph(f"Période : {cov['first_month']} à {cov['last_month']} ({cov['n_months_pnl']} mois). Signature HMAC-SHA256 : "
                    f"{payload['signature'][:24]}...", P),
          Paragraph("Ce PDF contient en pièce jointe les données normalisées signées (fichier creditwise_dossier.json). "
                    "Une institution financière peut le téléverser dans CreditWise : toute modification invalide la signature.", SMALL),
          Paragraph("Comptes de résultat mensuels (12 derniers mois)", H2)]
    ms = [r for r in a["monthly"] if r["has_pnl"]][-12:]
    rows = [["Mois", "Chiffre d'affaires", "Marge commerciale", "Résultat d'exploitation", "Résultat net", "Trésorerie"]]
    for r in ms:
        rows.append([r["month"], money(r["ventes"]), money(r["marge_commerciale"]), money(r["resultat_exploitation"]),
                     money(r["resultat_net"]), money(r["tresorerie"])])
    el.append(_table(rows, [1.8 * cm, 3.2 * cm, 3.2 * cm, 3.4 * cm, 3.1 * cm, 3.1 * cm]))
    el.append(Paragraph(f"Bilan au {cov['last_balance'] or 'non fourni'}", H2))
    B = a["balance_last"]
    brows = [["Poste", "Montant"]] + [[ITEMS[k][0], money(B.get(k))] for k in
                                      ["immobilisations", "stocks", "creances_clients", "autres_creances", "tresorerie", "capitaux_propres",
                                       "dettes_financieres_lt", "dettes_financieres_ct", "dettes_fournisseurs", "dettes_fiscales_sociales", "autres_dettes"]]
    el.append(_table(brows, [10 * cm, 7.8 * cm]))
    el.append(Paragraph("Provenance des données", H2))
    el.append(_table([["Fichier source", "Type", "Valeurs", "Importé le"]] +
                     [[Paragraph(d["filename"], CELL), d["kind"], str(d["n_values"]), d["uploaded_at"][:16]] for d in a["documents"]],
                     [7.5 * cm, 4 * cm, 2.3 * cm, 4 * cm]))
    el.append(Paragraph("Statuts : " + ", ".join(f"{k} {v}" for k, v in cov["status_counts"].items())
                        + ". Les valeurs extraites automatiquement et non vérifiées ne sont pas certaines.", SMALL))
    doc.build(el, onFirstPage=_footer(f"Dossier confidentiel, partage soumis à l'autorisation de {c['name']}"),
              onLaterPages=_footer(f"Dossier confidentiel, partage soumis à l'autorisation de {c['name']}"))
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    writer.add_attachment("creditwise_dossier.json", json.dumps(payload, ensure_ascii=False).encode())
    if password:
        writer.encrypt(user_password=password, owner_password=None, algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
