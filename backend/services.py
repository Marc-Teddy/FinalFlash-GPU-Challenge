"""Services applicatifs : import de documents, chargement des données, analyse complète."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import secrets
from datetime import date

from . import db
from .engine.anomalies import detect
from .engine.extract import extract
from .engine.finance import analyse
from .engine.items import ITEMS
from .engine.scoring import pd_estimate, rule_score

def _secret() -> bytes | None:
    if os.environ.get("CREDITWISE_SECRET"):
        return os.environ["CREDITWISE_SECRET"].encode()
    if db.ON_VERCEL:  # plusieurs instances : une clé aléatoire par instance casserait sessions et signatures
        return None
    path = db.DB_PATH.parent / ".secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


SECRET = _secret()
# Erreur de configuration affichée à la place du site (plutôt qu'un plantage au démarrage)
CONFIG_ERROR = None if SECRET else (
    "La variable d'environnement CREDITWISE_SECRET n'est pas définie. Dans Vercel : Settings, Environment Variables, "
    "ajoutez CREDITWISE_SECRET (une longue valeur aléatoire), puis relancez le déploiement (Deployments, Redeploy).")
DOSSIER_ATTACHMENT = "creditwise_dossier.json"


def sign(payload: bytes) -> str:
    return hmac.new(SECRET, payload, hashlib.sha256).hexdigest()


def _dossier_from_pdf(data: bytes):
    """Un dossier CreditWise exporté contient les données normalisées en pièce jointe, signées (HMAC)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        att = reader.attachments.get(DOSSIER_ATTACHMENT)
        if not att:
            return None
        payload = att[0]
        doc = json.loads(payload)
        body = json.dumps(doc["data"], sort_keys=True, ensure_ascii=False).encode()
        return doc, hmac.compare_digest(sign(body), doc.get("signature", ""))
    except Exception:
        return None


def import_document(con, company_id: int, user_id: int, filename: str, data: bytes) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    path = db.UPLOADS / f"{company_id}_{sha[:16]}_{os.path.basename(filename)}"
    path.write_bytes(data)
    already = con.execute("SELECT id FROM documents WHERE company_id=? AND sha256=?", (company_id, sha)).fetchone()

    dossier = _dossier_from_pdf(data) if filename.lower().endswith(".pdf") else None
    if dossier:
        doc, valid = dossier
        kind = "dossier_creditwise"
        values = []
        if valid:
            for v in doc["data"]["values"]:
                values.append({**v, "period_start": date.fromisoformat(v["period_start"]),
                               "period_end": date.fromisoformat(v["period_end"])})
        txs = [{**t, "date": date.fromisoformat(t["date"]) if t["date"] else None} for t in doc["data"].get("transactions", [])] if valid else []
        unmatched = []
        warnings = [] if valid else ["Signature du dossier invalide : le fichier a été modifié après son export. Données non importées."]
        if valid:
            warnings.append(f"Dossier CreditWise authentique (signé le {doc['data']['exported_at'][:10]}) : statuts d'origine conservés.")
    else:
        ex = extract(filename, data)
        kind, values, txs, unmatched, warnings = ex.kind, ex.values, ex.transactions, ex.unmatched, ex.warnings
    if already:
        warnings = warnings + ["Ce fichier a déjà été importé : doublon de document signalé."]

    cur = con.execute(
        "INSERT INTO documents(company_id, filename, kind, format, sha256, path, uploaded_by, n_values, n_transactions, unmatched, warnings)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (company_id, filename, kind, filename.rsplit(".", 1)[-1].lower(), sha, str(path), user_id,
         0 if already else len(values), 0 if already else len(txs), json.dumps(unmatched, ensure_ascii=False),
         json.dumps(warnings, ensure_ascii=False)))
    doc_id = cur.lastrowid
    if not already:
        con.executemany(
            "INSERT INTO fin_values(company_id, period_start, period_end, document_id, source_name, item, amount, status,"
            " source_label, confidence, comment) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(company_id, v["period_start"].isoformat(), v["period_end"].isoformat(), doc_id, filename, v["item"],
              v["amount"], v["status"], v.get("source_label"), v.get("confidence"), v.get("comment")) for v in values])
        con.executemany(
            "INSERT INTO transactions(company_id, document_id, date, raw_date, reference, counterparty, label, account, debit, credit)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(company_id, doc_id, t["date"].isoformat() if t["date"] else None, t.get("raw_date"), t["reference"],
              t["counterparty"], t["label"], t["account"], t["debit"], t["credit"]) for t in txs])
    db.log(con, user_id, company_id, "import_document", filename)
    periods = sorted({v["period_end"].isoformat()[:7] for v in values})
    return {"document_id": doc_id, "filename": filename, "kind": kind, "n_values": len(values), "n_transactions": len(txs),
            "periods": [periods[0], periods[-1]] if periods else None, "unmatched": unmatched, "warnings": warnings,
            "duplicate_document": bool(already),
            "status_summary": {s: sum(1 for v in values if v["status"] == s) for s in {v["status"] for v in values}}}


def load_values(con, company_id: int) -> list[dict]:
    rows = con.execute("SELECT * FROM fin_values WHERE company_id=? ORDER BY period_end, item", (company_id,)).fetchall()
    return [{**dict(r), "period_start": date.fromisoformat(r["period_start"]), "period_end": date.fromisoformat(r["period_end"])}
            for r in rows]


def public_documents(docs: list[dict]) -> list[dict]:
    """Retire les détails internes (chemin sur le serveur) avant envoi au navigateur."""
    return [{k: v for k, v in d.items() if k not in {"path", "uploaded_by"}} for d in docs]


def load_transactions(con, company_id: int) -> list[dict]:
    rows = con.execute("SELECT * FROM transactions WHERE company_id=?", (company_id,)).fetchall()
    return [{**dict(r), "date": date.fromisoformat(r["date"]) if r["date"] else None} for r in rows]


def load_documents(con, company_id: int) -> list[dict]:
    rows = con.execute("SELECT * FROM documents WHERE company_id=? ORDER BY uploaded_at, id", (company_id,)).fetchall()
    return [{**dict(r), "unmatched": json.loads(r["unmatched"] or "[]"), "warnings": json.loads(r["warnings"] or "[]")} for r in rows]


def proof(a: dict, txs: list[dict]) -> dict:
    """Rapprochement mois par mois : ventes déclarées face aux pièces (grand livre, relevé mobile money).
    Une vente est « justifiée » si le grand livre la retrouve à 2 % près."""
    from collections import defaultdict

    from .engine.finance import ym
    from .engine.items import match_account

    gl, mm_in, mm_out = defaultdict(float), defaultdict(float), defaultdict(float)
    for t in txs:
        if not t["date"]:
            continue
        m = ym(t["date"])
        if t["account"] == "MM":
            mm_in[m] += t["debit"]; mm_out[m] += t["credit"]
        elif match_account(t["account"]) == "ventes":
            gl[m] += t["credit"] - t["debit"]
    rows, justified = [], 0
    for r in a.get("monthly", []):
        m, v = r["month"], r["ventes"]
        if v is None:
            continue
        g = gl.get(m)
        ecart = None if g is None or not v else (g - v) / v * 100
        cover = None if m not in mm_in or not v else mm_in[m] / v * 100
        if ecart is not None and abs(ecart) <= 2:
            statut, ok = "Justifié par le grand livre", True
        elif ecart is not None:
            statut, ok = "Écart avec le grand livre", False
        elif cover is not None and cover >= 50:
            statut, ok = "Partiellement justifié (mobile money)", False
        else:
            statut, ok = "Déclaré, sans pièce", False
        justified += ok
        rows.append({"month": m, "ventes": v, "grand_livre": g and round(g), "ecart_pct": ecart and round(ecart, 1),
                     "mobile_money_entrees": round(mm_in[m]) if m in mm_in else None, "couverture_mm_pct": cover and round(cover),
                     "statut": statut, "justifie": ok})
    return {"rows": rows, "justified_months": justified, "months": len(rows),
            "sources": [s for s, c in (("grand livre", gl), ("relevé mobile money", mm_in)) if c]}


def full_analysis(con, company_id: int, request: dict | None = None, today: date | None = None,
                  local_default_rate: float | None = None) -> dict:
    values = load_values(con, company_id)
    txs = load_transactions(con, company_id)
    docs = load_documents(con, company_id)
    a = analyse(values, request)
    pr = proof(a, txs) if not a.get("empty") else {"rows": [], "justified_months": 0, "months": 0, "sources": []}
    if pr["justified_months"]:  # une vente retrouvée dans le grand livre compte comme justifiée
        sc = a["coverage"]["status_counts"]
        for _ in range(pr["justified_months"]):
            src = next((k for k in ("declare", "verifie", "extrait", "estime") if sc.get(k)), None)
            if src:
                sc[src] -= 1; sc["justifie"] = sc.get("justifie", 0) + 1
    alerts = detect(a, txs, docs, today)
    score = rule_score(a, alerts)
    pd = pd_estimate(a, local_default_rate=local_default_rate) if not a.get("empty") else {"available": False, "reason": "Aucune donnée."}
    company = dict(con.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone())
    doc_kinds = {d["kind"] for d in docs}
    checklist = [
        {"document": "Compte de résultat (mensuel ou trimestriel)", "ok": bool(a.get("pnl"))},
        {"document": "Bilan", "ok": bool(a.get("balances"))},
        {"document": "Grand livre / journal des opérations", "ok": bool(txs)},
        {"document": "Balance générale", "ok": "balance_generale" in doc_kinds},
        {"document": "Tableau des flux de trésorerie", "ok": False, "note": "Reconstitué à partir des bilans successifs"},
        {"document": "Historique de remboursement de crédits", "ok": False, "note": "Non disponible : à demander"},
    ]
    out = {k: v for k, v in a.items() if k not in {"pnl", "balances", "flows_raw", "stocks_raw", "conflicts", "ratios_by_key"}}
    out.update({"proof": pr, "company": company, "alerts": alerts, "score": score, "pd": pd, "documents": public_documents(docs),
                "n_transactions": len(txs), "checklist": checklist,
                "limits": [
                    "Les données de démonstration sont fictives ; le modèle PD est entraîné sur des données réelles d'entreprises polonaises.",
                    "Une anomalie est un signal à vérifier, pas la preuve d'une fraude.",
                    "Le score à base de règles n'est pas un modèle prédictif ; ses seuils sont à valider par l'équipe Finance.",
                    "Les valeurs « extraites automatiquement » non vérifiées ne sont pas certaines.",
                    "La décision de crédit appartient à un analyste habilité.",
                ]})
    return out


def dossier_payload(con, company_id: int) -> dict:
    from datetime import datetime

    values = load_values(con, company_id)
    txs = load_transactions(con, company_id)
    company = dict(con.execute("SELECT id, name, sector, city FROM companies WHERE id=?", (company_id,)).fetchone())
    data = {
        "format": "creditwise-dossier/1", "exported_at": datetime.now().isoformat(timespec="seconds"), "company": company,
        "values": [{"period_start": v["period_start"].isoformat(), "period_end": v["period_end"].isoformat(), "item": v["item"],
                    "amount": v["amount"], "status": v["status"], "source_label": v["source_label"] or v["source_name"],
                    "confidence": v["confidence"], "comment": (v["comment"] or "") + f" [source : {v['source_name']}]"} for v in values],
        "transactions": [{"date": t["date"].isoformat() if t["date"] else None, "raw_date": t["raw_date"], "reference": t["reference"],
                          "counterparty": t["counterparty"], "label": t["label"], "account": t["account"],
                          "debit": t["debit"], "credit": t["credit"]} for t in txs],
    }
    body = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return {"data": data, "signature": sign(body), "algorithm": "HMAC-SHA256"}


def item_label(item: str) -> str:
    return ITEMS.get(item, (item,))[0]
