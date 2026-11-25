"""Génération des PDF : rapport d'analyse (institution) et dossier financier sécurisé (commerçant)."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from .engine.items import ITEMS  # noqa: E402

NAVY = colors.HexColor("#14324f")
SEV = {"elevee": ("Élevée", colors.HexColor("#b42318")), "attention": ("Attention", colors.HexColor("#b54708")),
       "info": ("Info", colors.HexColor("#475467"))}
SS = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=SS["Heading1"], textColor=NAVY, fontSize=17, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=SS["Heading2"], textColor=NAVY, fontSize=12.5, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("p", parent=SS["BodyText"], fontSize=9, leading=12)
SMALL = ParagraphStyle("s", parent=P, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#475467"))
CELL = ParagraphStyle("c", parent=P, fontSize=8, leading=10)


def money(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", " ") + " FCFA"


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


def _chart(a) -> Image:
    ms = [r for r in a["monthly"]][-24:]
    x = [r["month"][2:] for r in ms]
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=150)
    ax.bar(x, [(r["ventes"] or 0) / 1e6 for r in ms], color="#2e6da4", label="Chiffre d'affaires")
    ax.plot(x, [(r["resultat_net"] / 1e6) if r["resultat_net"] is not None else None for r in ms], color="#e8833a",
            marker="o", ms=3, label="Résultat net")
    tr = [(r["tresorerie_nette_constatee"] / 1e6) if r["tresorerie_nette_constatee"] is not None else None for r in ms]
    if any(v is not None for v in tr):
        ax.plot(x, tr, color="#2b9348", ls="--", marker="s", ms=2.5, label="Trésorerie nette (caisse + banque – découverts)")
    ax.axhline(0, color="#999", lw=0.6)
    ax.set_ylabel("millions FCFA", fontsize=7)
    ax.tick_params(labelsize=6)
    plt.xticks(rotation=60)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(fontsize=6.5, frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=17.5 * cm, height=6.3 * cm)


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
                            title=f"CreditWise — Rapport d'analyse — {a['company']['name']}")
    c, cov, s, pdm = a["company"], a["coverage"], a["score"], a["pd"]
    el = []
    el.append(Paragraph("CreditWise · Rapport d'analyse de crédit", H1))
    el.append(Paragraph(f"<b>{c['name']}</b> — {c.get('sector') or ''}, {c.get('city') or ''}. "
                        f"Généré le {datetime.now():%d/%m/%Y à %H:%M} pour {analyst}. Empreinte de l'analyse : {fingerprint}.", P))
    if request:
        el.append(Paragraph(f"Demande : <b>{money(request['amount'])}</b> sur {request['duration_months']} mois au taux annuel de "
                            f"{request['annual_rate'] * 100:.1f} % — objet : {request.get('purpose') or '—'}. "
                            f"Échéance mensuelle estimée : {money(a['credit']['new_installment'])}.", P))
    # Synthèse
    el.append(Paragraph("1. Synthèse", H2))
    R = {r["key"]: r for r in a["ratios"]}
    syn = [["Indicateur", "Valeur", "Lecture"],
           ["Score de risque (règles)", "—" if s["score"] is None else f"{s['score']:.0f} / 100", Paragraph(s["category"], CELL)],
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
    el.append(Paragraph(f"Données de {cov['first_month']} à {cov['last_month']} — {cov['n_months_pnl']} mois de compte de résultat, "
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
                      "—" if q["var_vs_prev"] is None else f"{q['var_vs_prev']:+.1f} %", "—" if q["var_yoy"] is None else f"{q['var_yoy']:+.1f} %"])
    el.append(_table(qrows, [5 * cm, 4.4 * cm, 4 * cm, 4.4 * cm]))
    el.append(Paragraph("Les trimestres incomplets ne sont pas comparés (périodes de durées différentes).", SMALL))

    # Ratios
    el.append(Paragraph("4. Ratios financiers et formules", H2))
    rr = [["Ratio", "Valeur", "Formule"]] + [[Paragraph(r["label"], CELL), fmt_ratio(r), Paragraph(r["formula"] + (
        f" — <i>{r['reason']}</i>" if r["value"] is None else ""), CELL)] for r in a["ratios"]]
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
        note = "—" if d["note"] is None else f"{d['note']:.0f}"
        for i, x in enumerate(d["details"]):
            sr.append([Paragraph(f"<b>{d['label']}</b> ({d['weight'] * 100:.0f} %) : {note}/100", CELL) if i == 0 else "",
                       Paragraph(x["criterion"], CELL), x["value"] or "n.c.", "—" if x["note"] is None else f"{x['note']:.0f}",
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
        el.append(KeepTogether([Paragraph(f"<b>{decision['decision']}</b> — par {decision['analyst']} le {decision['decided_at'][:16]}.", P),
                                Paragraph("Motif : " + decision["comment"], P)]))
    else:
        el.append(Paragraph("Aucune décision enregistrée à la date du rapport. Décision réservée à un analyste habilité.", P))
    doc.build(el, onFirstPage=_footer(f"CreditWise — confidentiel — {c['name']}"),
              onLaterPages=_footer(f"CreditWise — confidentiel — {c['name']}"))
    return buf.getvalue()


def dossier_pdf(a: dict, payload: dict, password: str | None = None) -> bytes:
    """Dossier financier du commerçant : synthèse lisible + données normalisées signées en pièce jointe."""
    from pypdf import PdfReader, PdfWriter

    buf = io.BytesIO()
    c, cov = a["company"], a["coverage"]
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm,
                            title=f"Dossier financier — {c['name']}")
    el = [Paragraph("Dossier financier CreditWise", H1),
          Paragraph(f"<b>{c['name']}</b> — {c.get('sector') or ''}, {c.get('city') or ''}. Exporté le {datetime.now():%d/%m/%Y à %H:%M}.", P),
          Paragraph(f"Période : {cov['first_month']} à {cov['last_month']} ({cov['n_months_pnl']} mois). Signature HMAC-SHA256 : "
                    f"{payload['signature'][:24]}…", P),
          Paragraph("Ce PDF contient en pièce jointe les données normalisées signées (fichier creditwise_dossier.json). "
                    "Une institution financière peut le téléverser dans CreditWise : toute modification invalide la signature.", SMALL),
          Paragraph("Comptes de résultat mensuels (12 derniers mois)", H2)]
    ms = [r for r in a["monthly"] if r["has_pnl"]][-12:]
    rows = [["Mois", "Chiffre d'affaires", "Marge commerciale", "Résultat d'exploitation", "Résultat net", "Trésorerie"]]
    for r in ms:
        rows.append([r["month"], money(r["ventes"]), money(r["marge_commerciale"]), money(r["resultat_exploitation"]),
                     money(r["resultat_net"]), money(r["tresorerie"])])
    el.append(_table(rows, [1.8 * cm, 3.2 * cm, 3.2 * cm, 3.4 * cm, 3.1 * cm, 3.1 * cm]))
    el.append(Paragraph(f"Bilan au {cov['last_balance'] or '—'}", H2))
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
    doc.build(el, onFirstPage=_footer(f"Dossier confidentiel — partage soumis à l'autorisation de {c['name']}"),
              onLaterPages=_footer(f"Dossier confidentiel — partage soumis à l'autorisation de {c['name']}"))
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    writer.add_attachment("creditwise_dossier.json", json.dumps(payload, ensure_ascii=False).encode())
    if password:
        writer.encrypt(user_password=password, owner_password=None, algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
