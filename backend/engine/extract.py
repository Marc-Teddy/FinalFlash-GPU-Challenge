"""Extraction et normalisation des documents importés (CSV, XLSX, PDF).

Formats reconnus automatiquement :
  * état financier « large »  : 1re colonne = poste, colonnes suivantes = périodes
  * état financier « long »   : colonnes periode_debut, periode_fin, poste, montant
  * balance générale mensuelle : periode, compte, intitule, debit, credit
  * grand livre / journal     : date, reference, tiers, libelle, compte, debit, credit
  * PDF texte                 : tableaux (pdfplumber), ou lignes « libellé  montant »

Les données venant d'un CSV/XLSX exporté sont « déclarées » ; celles lues dans un PDF sont
« extraites automatiquement » et doivent être vérifiées par l'utilisateur.
"""
from __future__ import annotations

import calendar
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from .items import ITEMS, account_sign, clean_label, match_account, match_label, strip_accents

MONTHS_FR = {
    "janv": 1, "janvier": 1, "jan": 1, "fevr": 2, "fevrier": 2, "fev": 2, "feb": 2, "mars": 3, "mar": 3,
    "avr": 4, "avril": 4, "apr": 4, "mai": 5, "may": 5, "juin": 6, "jun": 6, "juil": 7, "juillet": 7,
    "jul": 7, "aout": 8, "aug": 8, "sept": 9, "septembre": 9, "sep": 9, "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11, "dec": 12, "decembre": 12,
}


@dataclass
class Extraction:
    kind: str = "inconnu"
    values: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def parse_period(v) -> tuple[date, date] | None:
    """Interprète un en-tête de période. Retourne (début, fin) ou None."""
    if isinstance(v, (datetime, pd.Timestamp)):
        return date(v.year, v.month, 1), month_end(v.year, v.month)
    if isinstance(v, date):
        return date(v.year, v.month, 1), month_end(v.year, v.month)
    s = strip_accents(str(v)).lower().strip().replace("\n", " ")
    if not s or s in {"nan", "none"}:
        return None
    if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?(?: 00:00:00)?", s):
        y, mo = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2})[-/](\d{4})", s):
        y, mo = int(m[2]), int(m[1])
    elif m := re.fullmatch(r"(?:t|q)([1-4])[\s\-/]*(\d{4})|(\d{4})[\s\-/]*(?:t|q)([1-4])", s):
        q, y = (int(m[1]), int(m[2])) if m[1] else (int(m[4]), int(m[3]))
        return date(y, 3 * q - 2, 1), month_end(y, 3 * q)
    elif m := re.fullmatch(r"(?:exercice\s*)?(\d{4})", s):
        y = int(m[1])
        return date(y, 1, 1), date(y, 12, 31)
    elif m := re.fullmatch(r"([a-z]+)\.?\s*(\d{2}|\d{4})", s):
        mo = MONTHS_FR.get(m[1]) or MONTHS_FR.get(m[1][:4]) or MONTHS_FR.get(m[1][:3])
        if not mo:
            return None
        y = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
    else:
        return None
    if not 1 <= mo <= 12:
        return None
    return date(y, mo, 1), month_end(y, mo)


def parse_amount(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else float(v)
    s = str(v).strip().replace(" ", " ").replace("\xa0", " ")
    s = re.sub(r"(?i)\s*(f\s*cfa|xof|fcfa|f)\s*$", "", s)
    if not s or s in {"-", "–", "nan"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(" ", "")
    if s.startswith("-") or s.startswith("−"):
        neg, s = True, s[1:]
    if not re.fullmatch(r"[\d.,]+", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif s.count(",") > 1 or s.count(".") > 1:
        s = s.replace(",", "").replace(".", "")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        tail = s.split(sep)[1]
        s = s.replace(sep, "") if len(tail) == 3 else s.replace(sep, ".")
    val = float(s)
    return -val if neg else val


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_label(c).replace(" ", "_") if not isinstance(c, (datetime, pd.Timestamp)) else c
                  for c in df.columns]
    return df


def _from_wide(rows: list[list], status: str, source_conf: float, ex: Extraction, context_period=None) -> None:
    """rows[0] = en-tête. 1re colonne = libellé, autres = périodes (ou une colonne montant)."""
    header = rows[0]
    periods = [parse_period(h) for h in header[1:]]
    if not any(periods) and context_period:
        # Tableau à une colonne « Montant » : la période vient du titre du document
        periods = [context_period] + [None] * (len(header) - 2)
    if not any(periods):
        ex.warnings.append("Aucune période reconnue dans l'en-tête du tableau.")
        return
    for r in rows[1:]:
        if not r or r[0] is None or str(r[0]).strip() == "":
            continue
        label = str(r[0]).strip()
        item, conf = match_label(label)
        amounts = [parse_amount(x) for x in r[1:]]
        if item is None:
            if any(a is not None for a in amounts) and clean_label(label) not in {"poste", "libelle", "rubrique"}:
                ex.unmatched.append(label)
            continue
        for p, a in zip(periods, amounts):
            if p is None or a is None:
                continue
            ex.values.append({
                "period_start": p[0], "period_end": p[1], "item": item, "amount": a,
                "status": status, "source_label": label, "confidence": round(conf * source_conf, 2),
                "comment": None if conf == 1 else f"Libellé « {label} » rapproché de « {ITEMS[item][0]} »",
            })


def _from_dataframe(df: pd.DataFrame, status: str, ex: Extraction) -> None:
    cols = set(_norm_cols(df).columns)
    n = _norm_cols(df)
    if {"compte", "debit", "credit"} <= cols and "date" in cols:
        ex.kind = "grand_livre"
        for _, r in n.iterrows():
            d = pd.to_datetime(r["date"], errors="coerce", dayfirst=True)
            debit, credit = parse_amount(r.get("debit")) or 0.0, parse_amount(r.get("credit")) or 0.0
            ex.transactions.append({
                "date": None if pd.isna(d) else d.date(), "raw_date": str(r["date"]),
                "reference": str(r.get("reference", r.get("piece", "")) or ""),
                "counterparty": str(r.get("tiers", "") or ""), "label": str(r.get("libelle", "") or ""),
                "account": str(r["compte"]).split(".")[0], "debit": debit, "credit": credit,
            })
        return
    if "compte" in cols and ({"debit", "credit"} <= cols or "solde" in cols) and "periode" in cols:
        ex.kind = "balance_generale"
        agg: dict[tuple, float] = {}
        for _, r in n.iterrows():
            p = parse_period(r["periode"])
            item = match_account(r["compte"])
            if p is None:
                ex.warnings.append(f"Période illisible : {r['periode']}")
                continue
            if item is None:
                ex.unmatched.append(f"Compte {r['compte']} {r.get('intitule', '')}".strip())
                continue
            raw = (parse_amount(r.get("debit")) or 0.0) - (parse_amount(r.get("credit")) or 0.0) \
                if "debit" in cols else parse_amount(r["solde"]) or 0.0
            agg[(p, item)] = agg.get((p, item), 0.0) + raw * account_sign(r["compte"])
        for (p, item), a in agg.items():
            ex.values.append({"period_start": p[0], "period_end": p[1], "item": item, "amount": round(a, 2),
                              "status": status, "source_label": "balance générale", "confidence": 1.0,
                              "comment": None})
        # Une balance liste tous les comptes de bilan mouvementés : un compte absent a un solde nul.
        # (Pas pour les comptes de gestion : un poste de charge absent doit rester visible.)
        for p in {p for p, _ in agg}:
            for item, (_, nature) in ITEMS.items():
                if nature == "stock" and item not in {"total_actif", "total_passif"} and (p, item) not in agg:
                    ex.values.append({"period_start": p[0], "period_end": p[1], "item": item, "amount": 0.0,
                                      "status": status, "source_label": "balance générale", "confidence": 1.0,
                                      "comment": "Compte absent de la balance : solde nul"})
        return
    if {"poste", "montant"} <= cols:
        ex.kind = "etat_financier_long"
        for _, r in n.iterrows():
            ps = parse_period(r.get("periode_debut", r.get("periode")))
            pe = parse_period(r.get("periode_fin", r.get("periode_debut", r.get("periode"))))
            item, conf = match_label(r["poste"])
            a = parse_amount(r["montant"])
            if item is None:
                ex.unmatched.append(str(r["poste"]))
                continue
            if ps is None or pe is None or a is None:
                ex.warnings.append(f"Ligne incomplète ignorée : {r['poste']}")
                continue
            st = str(r.get("statut", status) or status)
            ex.values.append({"period_start": ps[0], "period_end": pe[1], "item": item, "amount": a,
                              "status": st if st in {"declare", "extrait", "verifie", "estime"} else status,
                              "source_label": str(r["poste"]), "confidence": conf,
                              "comment": None if conf == 1 else f"Libellé rapproché de « {ITEMS[item][0]} »"})
        return
    ex.kind = "etat_financier"
    rows = [list(df.columns)] + df.astype(object).where(df.notna(), None).values.tolist()
    _from_wide(rows, status, 1.0, ex)


def _read_excel_all(data: bytes) -> list[pd.DataFrame]:
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None)
    out = []
    for raw in sheets.values():
        raw = raw.dropna(how="all").dropna(axis=1, how="all")
        if raw.empty:
            continue
        # La ligne d'en-tête est la première qui contient au moins 2 cellules non vides
        hdr = next(i for i, (_, r) in enumerate(raw.iterrows()) if r.notna().sum() >= 2)
        df = raw.iloc[hdr + 1:].copy()
        df.columns = [c if not pd.isna(c) else f"col{j}" for j, c in enumerate(raw.iloc[hdr])]
        out.append(df.reset_index(drop=True))
    return out


def _pdf_context_period(text: str):
    t = strip_accents(text).lower()
    if m := re.search(r"du\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+au\s+(\d{1,2})/(\d{1,2})/(\d{4})", t):
        return date(int(m[3]), int(m[2]), int(m[1])), date(int(m[6]), int(m[5]), int(m[4]))
    if m := re.search(r"au\s+(\d{1,2})/(\d{1,2})/(\d{4})", t):
        d = date(int(m[3]), int(m[2]), int(m[1]))
        return date(d.year, d.month, 1), d
    return None


def _from_pdf(data: bytes, ex: Extraction) -> None:
    import pdfplumber

    ex.kind = "etat_financier_pdf"
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            ctx = _pdf_context_period(text)
            tables = page.extract_tables()
            if tables:
                for t in tables:
                    if len(t) >= 2:
                        _from_wide(t, "extrait", 0.95, ex, ctx)
                continue
            # Repli : lignes « libellé  montant » avec la période trouvée dans le titre
            if ctx is None:
                continue
            for line in text.splitlines():
                if m := re.match(r"^(.*?[A-Za-zÀ-ÿ].*?)\s+(\(?-?[\d][\d\s.,]*\)?)\s*(?:F\s*CFA|FCFA|XOF)?$", line.strip()):
                    item, conf = match_label(m[1])
                    a = parse_amount(m[2])
                    if item and a is not None:
                        ex.values.append({"period_start": ctx[0], "period_end": ctx[1], "item": item, "amount": a,
                                          "status": "extrait", "source_label": m[1], "confidence": round(conf * 0.9, 2),
                                          "comment": "Lu dans le texte du PDF : à vérifier"})
    if not ex.values:
        ex.warnings.append("Aucune donnée exploitable dans ce PDF (document scanné ? l'OCR est prévu après le prototype).")


def extract(filename: str, data: bytes) -> Extraction:
    ex = Extraction()
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            _from_pdf(data, ex)
        elif name.endswith((".xlsx", ".xlsm", ".xls")):
            for df in _read_excel_all(data):
                _from_dataframe(df, "declare", ex)
        elif name.endswith((".csv", ".txt")):
            text = data.decode("utf-8-sig", errors="replace")
            sep = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
            df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
            _from_dataframe(df, "declare", ex)
        else:
            ex.warnings.append("Format non pris en charge (PDF, XLSX ou CSV attendus).")
    except Exception as e:  # le document est conservé, l'erreur est remontée à l'utilisateur
        ex.warnings.append(f"Lecture impossible : {e}")
    ex.unmatched = sorted(set(ex.unmatched))
    return ex
