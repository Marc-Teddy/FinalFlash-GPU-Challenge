"""API CreditWise (FastAPI). Lancer : uvicorn backend.app:app --reload"""
from __future__ import annotations

import json
import math
import re
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Annotated

from pydantic import BaseModel, Field

from . import db, otp, reports, services

from contextlib import asynccontextmanager  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SESSION_HOURS = 8
MAX_UPLOAD = 15 * 1024 * 1024
MAX_FILES = 10


_ready = threading.Lock()
_initialised = False


def ensure_ready() -> None:
    """Crée la base au premier appel et charge la démonstration si elle est vide.
    Sur Vercel, chaque démarrage à froid repart d'une base neuve dans /tmp."""
    global _initialised
    if _initialised:
        return
    with _ready:
        if _initialised:
            return
        db.init()
        if db.is_empty() and os.environ.get("CREDITWISE_AUTOSEED", "1") != "0":
            from . import seed
            seed.populate()
        _initialised = True


@asynccontextmanager
async def lifespan(_app):
    ensure_ready()
    yield


# Pas de documentation d'API publique : elle exposerait la structure interne.
app = FastAPI(title="CreditWise", version="0.1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

SECURITY_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; "
                               "script-src 'self' https://accounts.google.com/gsi/client; frame-src https://accounts.google.com; "
                               "connect-src 'self' https://accounts.google.com; object-src 'none'; frame-ancestors 'none'",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if services.CONFIG_ERROR:  # configuration incomplète : page explicative au lieu d'une erreur 500
        page = ("<!doctype html><meta charset='utf-8'><title>CreditWise : configuration</title>"
                "<body style='font-family:sans-serif;max-width:640px;margin:60px auto;padding:0 16px;line-height:1.6'>"
                f"<h1 style='font-size:22px'>Configuration à terminer</h1><p>{services.CONFIG_ERROR}</p></body>")
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": services.CONFIG_ERROR}, status_code=503)
        return HTMLResponse(page, status_code=503)
    if request.url.path.startswith("/api"):
        ensure_ready()
    resp = await call_next(request)
    resp.headers.update(SECURITY_HEADERS)
    return resp


def attachment(name: str) -> dict:
    from urllib.parse import quote

    from .engine.items import strip_accents

    ascii_name = strip_accents(name).encode("ascii", "ignore").decode()
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"}


def clean(o):
    """JSON strict : dates en ISO, NaN/inf en null."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


# ------------------------------------------------------------------ auth
ROLE_LABEL = {"merchant": "commerçant", "institution": "établissement de crédit"}


class Login(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=128)
    role: str | None = Field(default=None, pattern="^(merchant|institution)$")  # espace de connexion utilisé


Text = Annotated[str | None, Field(max_length=120)]
EMAIL = r"^[^@\s]{1,64}@[^@\s]{1,180}\.[a-zA-Z]{2,24}$"
CATEGORIES = {"Vêtements et mode", "Alimentation", "Quincaillerie", "Cosmétiques", "Téléphonie", "Restauration",
              "Pièces auto", "Autre commerce"}
FUNCTIONS = {"Analyste crédit", "Responsable crédit", "Direction", "Autre"}


class Profile(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    company_name: Text = None      # commerçant : nom du commerce
    category: Text = None          # commerçant : catégorie principale
    organisation: Text = None      # établissement de crédit
    function: Text = None          # établissement de crédit : fonction
    city: Text = None


class CodeRequest(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    role: str = Field(pattern="^(merchant|institution)$")
    mode: str = Field(pattern="^(signup|login)$")
    profile: Profile | None = None
    accept_terms: bool = False


class CodeCheck(BaseModel):
    challenge: str = Field(max_length=4000)
    code: str = Field(max_length=12)


class GoogleAuth(BaseModel):
    credential: str = Field(max_length=5000)
    role: str = Field(pattern="^(merchant|institution)$")
    mode: str = Field(pattern="^(signup|login)$")
    profile: Profile | None = None
    accept_terms: bool = False


def _check_profile(role: str, p: Profile | None, accept_terms: bool) -> dict:
    if not accept_terms:
        raise HTTPException(400, "Acceptez les conditions générales et la politique de confidentialité.")
    if p is None:
        raise HTTPException(400, "Complétez le formulaire.")
    if role == "merchant" and (not p.company_name or p.category not in CATEGORIES):
        raise HTTPException(400, "Indiquez le nom du commerce et sa catégorie principale.")
    if role == "institution" and (not p.organisation or (p.function and p.function not in FUNCTIONS)):
        raise HTTPException(400, "Indiquez le nom de l'établissement.")
    return p.model_dump()


def _create_account(con, email: str, role: str, p: dict) -> int:
    unusable = f"{secrets.token_hex(16)}$connexion-par-code"  # aucun mot de passe : connexion par code ou Google
    uid = con.execute("INSERT INTO users(username, password_hash, role, display_name, organisation, accepted_terms_at) "
                      "VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                      (email, unusable, role, p["full_name"], p.get("organisation") if role == "institution" else None)).lastrowid
    if role == "merchant":
        con.execute("INSERT INTO companies(owner_user_id, name, sector, city) VALUES (?,?,?,?)",
                    (uid, p["company_name"], p["category"], p.get("city")))
    db.log(con, uid, None, "creation_compte", "conditions acceptées")
    return uid


def _open_session(resp: Response, email: str, role: str, mode: str, profile: dict | None) -> dict:
    with db.tx() as con:
        u = con.execute("SELECT * FROM users WHERE username=?", (email,)).fetchone()
        if u and u["role"] != role:
            raise HTTPException(403, f"Cette adresse est liée à un compte {ROLE_LABEL[u['role']]} : utilisez l'espace {ROLE_LABEL[u['role']]}.")
        if not u:
            if mode != "signup" or not profile:
                raise HTTPException(404, "Aucun compte pour cette adresse : créez un compte.")
            uid = _create_account(con, email, role, profile)
        else:
            uid = u["id"]
        _session(resp, con, uid)
        db.log(con, uid, None, "connexion")
    return {"ok": True, "role": role}


@app.get("/api/auth/config")
def auth_config():
    return {"google_client_id": otp.google_client_id(), "demo_codes": otp.demo_codes(), "email_delivery": otp.smtp_configured()}


@app.post("/api/auth/code")
def auth_code(body: CodeRequest):
    email = body.email.strip().lower()
    profile = _check_profile(body.role, body.profile, body.accept_terms) if body.mode == "signup" else None
    if body.mode == "signup":
        with db.tx() as con:
            if con.execute("SELECT 1 FROM users WHERE username=?", (email,)).fetchone():
                raise HTTPException(409, "Un compte existe déjà avec cette adresse : connectez-vous.")
    if not otp.can_send(email):
        raise HTTPException(429, "Trop de codes demandés. Réessayez dans 15 minutes.")
    challenge, code = otp.new_challenge(services.SECRET, email, body.role, body.mode, profile)
    try:
        sent = otp.send_code(email, code)
    except Exception:
        raise HTTPException(502, "Envoi de l'e-mail impossible pour le moment.") from None
    out = {"challenge": challenge, "sent_to": otp.mask(email), "expires_in": otp.CODE_TTL}
    if not sent and otp.demo_codes():
        out["demo_code"] = code  # prototype sans serveur d'e-mail : code affiché à l'écran
    elif not sent:
        raise HTTPException(503, "Aucun service d'envoi d'e-mail n'est configuré.")
    return out


@app.post("/api/auth/verify")
def auth_verify(body: CodeCheck, resp: Response):
    try:
        data = otp.check_challenge(services.SECRET, body.challenge, body.code)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return _open_session(resp, data["e"], data["r"], data["m"], data["p"] or None)


@app.post("/api/auth/google")
def auth_google(body: GoogleAuth, resp: Response):
    try:
        info = otp.verify_google(body.credential)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    profile = None
    if body.mode == "signup":
        if body.profile is None:
            body.profile = Profile(full_name=info["name"])
        profile = _check_profile(body.role, body.profile, body.accept_terms)
    return _open_session(resp, info["email"], body.role, body.mode, profile)


# Session = cookie signé contenant l'identité (adresse, rôle, nom, commerce) et l'échéance.
# L'utilisateur est retrouvé par son adresse, jamais par un numéro interne : sur Vercel, chaque instance a sa
# propre base temporaire et les numéros n'y coïncident pas. Si une instance ne connaît pas encore le compte,
# elle le recrée à partir du cookie, dont la signature garantit qu'il n'a pas été modifié.
def _sign(payload: str) -> str:
    return hmac.new(services.SECRET, payload.encode(), hashlib.sha256).hexdigest()


def current_user(request: Request) -> dict:
    token = request.cookies.get("cw_session") or ""
    try:
        raw, sig = token.rsplit(".", 1)
        body = json.loads(otp._unb64(raw)) if hmac.compare_digest(_sign(raw), sig) else None
    except (ValueError, json.JSONDecodeError):
        body = None
    if not body or body.get("x", 0) < time.time():
        raise HTTPException(401, "Connexion requise")
    with db.tx() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (body["u"],)).fetchone()
        if row is None:  # compte créé sur une autre instance : on le restaure depuis le cookie signé
            uid = con.execute("INSERT INTO users(username, password_hash, role, display_name, organisation, accepted_terms_at) "
                              "VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                              (body["u"], f"{secrets.token_hex(16)}$connexion-par-code", body["r"], body["n"], body.get("o"))).lastrowid
            if body.get("c"):
                con.execute("INSERT INTO companies(owner_user_id, name, sector, city) VALUES (?,?,?,?)",
                            (uid, body["c"]["name"], body["c"].get("sector"), body["c"].get("city")))
            row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if row["role"] != body["r"]:
        raise HTTPException(401, "Session expirée")
    return {k: row[k] for k in ("id", "username", "role", "display_name", "organisation")}


def _session(resp: Response, con, user_id: int):
    u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    c = con.execute("SELECT name, sector, city FROM companies WHERE owner_user_id=? ORDER BY id LIMIT 1", (user_id,)).fetchone()
    body = {"u": u["username"], "r": u["role"], "n": u["display_name"], "o": u["organisation"],
            "c": dict(c) if c else None, "x": int(time.time()) + SESSION_HOURS * 3600}
    raw = otp._b64(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
    resp.set_cookie("cw_session", f"{raw}.{_sign(raw)}", httponly=True, samesite="strict", secure=db.ON_VERCEL,
                    max_age=SESSION_HOURS * 3600)


_failures: dict[str, list[float]] = {}  # identifiant -> horodatages des échecs récents


@app.post("/api/login")
def login(body: Login, resp: Response):
    name = body.username.strip().lower()[:40]
    recent = [t for t in _failures.get(name, []) if time.time() - t < 900]
    if len(recent) >= 5:
        raise HTTPException(429, "Trop de tentatives. Réessayez dans 15 minutes.")
    with db.tx() as con:
        u = con.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
        if not u or not db.check_password(body.password[:128], u["password_hash"]):
            _failures[name] = recent + [time.time()]
            raise HTTPException(401, "Identifiant ou mot de passe incorrect")
        _failures.pop(name, None)
        if body.role and u["role"] != body.role:
            raise HTTPException(403, f"Ce compte est un compte {ROLE_LABEL[u['role']]} : utilisez l'espace {ROLE_LABEL[u['role']]}.")
        _session(resp, con, u["id"])
        db.log(con, u["id"], None, "connexion")
    return {"ok": True, "role": u["role"]}


@app.post("/api/logout")
def logout(resp: Response):
    resp.delete_cookie("cw_session")
    return {"ok": True}


@app.get("/api/session")
def session(request: Request):
    """État de connexion sans erreur : les pages publiques l'appellent à chaque visite."""
    try:
        user = current_user(request)
    except HTTPException:
        return {"authenticated": False}
    return {"authenticated": True, **me(user)}


@app.get("/api/me")
def me(user=Depends(current_user)):
    with db.tx() as con:
        companies = [dict(r) for r in con.execute("SELECT * FROM companies WHERE owner_user_id=?", (user["id"],))]
    return {**user, "companies": companies}


# ------------------------------------------------------------------ droits
def can_read(con, user, company_id: int) -> bool:
    c = con.execute("SELECT owner_user_id FROM companies WHERE id=?", (company_id,)).fetchone()
    if not c:
        raise HTTPException(404, "Entreprise introuvable")
    if c["owner_user_id"] == user["id"]:
        return True
    return user["role"] == "institution" and con.execute(
        "SELECT 1 FROM shares WHERE company_id=? AND institution_user_id=? AND revoked_at IS NULL", (company_id, user["id"])).fetchone() is not None


def require_read(con, user, company_id):
    if not can_read(con, user, company_id):
        raise HTTPException(403, "Accès non autorisé par le commerçant")


def require_owner(con, user, company_id):
    c = con.execute("SELECT owner_user_id FROM companies WHERE id=?", (company_id,)).fetchone()
    if not c or c["owner_user_id"] != user["id"]:
        raise HTTPException(403, "Seul le titulaire du dossier peut effectuer cette action")


# ------------------------------------------------------------------ documents & données
@app.post("/api/companies/{company_id}/documents")
async def upload(company_id: int, files: list[UploadFile] = File(...), user=Depends(current_user)):
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"{MAX_FILES} fichiers au maximum par envoi")
    results = []
    with db.tx() as con:
        require_owner(con, user, company_id)
        for f in files:
            # Nom de fichier assaini : jamais utilisé tel quel dans un chemin ou affiché brut
            name = re.sub(r"[^\w.\- ]", "_", Path(f.filename or "fichier").name)[:120] or "fichier"
            if not name.lower().endswith((".pdf", ".xlsx", ".xlsm", ".csv", ".txt")):
                results.append({"filename": name, "kind": "inconnu", "warnings": ["Format refusé (PDF, XLSX ou CSV attendus)."], "n_values": 0, "n_transactions": 0})
                continue
            data = await f.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                results.append({"filename": name, "kind": "inconnu", "warnings": ["Fichier trop volumineux (15 Mo max)."], "n_values": 0, "n_transactions": 0})
                continue
            results.append(services.import_document(con, company_id, user["id"], name, data))
    return clean({"results": results})


Montant = Annotated[float | None, Field(ge=0, le=1e12)]


class Saisie(BaseModel):
    """Saisie simplifiée d'un mois, pour un commerçant sans comptabilité."""
    mois: str = Field(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")
    ventes: float = Field(ge=0, le=1e12)
    achats_marchandises: Montant = None
    loyers: Montant = None
    charges_personnel: Montant = None
    transport: Montant = None
    autres_charges_externes: Montant = None
    remboursement_emprunts: Montant = None
    charges_financieres: Montant = None
    tresorerie: Montant = None          # caisse + banque + mobile money
    stocks: Montant = None              # estimation
    immobilisations: Montant = None     # matériel, estimation
    creances_clients: Montant = None
    dettes_fournisseurs: Montant = None
    dettes_financieres_lt: Montant = None


ESTIMES = {"stocks", "immobilisations"}


@app.post("/api/companies/{company_id}/saisie")
def saisie(company_id: int, body: Saisie, user=Depends(current_user)):
    import calendar
    y, m = int(body.mois[:4]), int(body.mois[5:])
    start, end = date(y, m, 1).isoformat(), date(y, m, calendar.monthrange(y, m)[1]).isoformat()
    name = f"Saisie du commerçant ({body.mois})"
    data = body.model_dump(exclude={"mois"}, exclude_none=True)
    with db.tx() as con:
        require_owner(con, user, company_id)
        old = con.execute("SELECT id FROM documents WHERE company_id=? AND filename=?", (company_id, name)).fetchall()
        for d in old:  # une nouvelle saisie du même mois remplace la précédente
            con.execute("DELETE FROM fin_values WHERE document_id=?", (d["id"],))
            con.execute("DELETE FROM documents WHERE id=?", (d["id"],))
        doc = con.execute("INSERT INTO documents(company_id, filename, kind, format, sha256, path, uploaded_by, n_values, unmatched, warnings) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?)", (company_id, name, "saisie_simplifiee", "saisie", secrets.token_hex(16), "",
                                                           user["id"], 0, "[]", "[]")).lastrowid
        rows = [(k, v, "estime" if k in ESTIMES else "declare", None) for k, v in data.items()]
        actifs = sum(data.get(k, 0) for k in ("tresorerie", "stocks", "immobilisations", "creances_clients"))
        dettes = sum(data.get(k, 0) for k in ("dettes_fournisseurs", "dettes_financieres_lt"))
        if any(k in data for k in ("tresorerie", "stocks", "immobilisations")):
            rows.append(("capitaux_propres", actifs - dettes, "estime", "Estimé : ce que possède le commerce moins ce qu'il doit"))
        con.executemany("INSERT INTO fin_values(company_id, period_start, period_end, document_id, source_name, item, amount, status, "
                        "source_label, confidence, comment) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [(company_id, start, end, doc, name, k, v, st, "saisie simplifiée", 1.0, c) for k, v, st, c in rows])
        con.execute("UPDATE documents SET n_values=? WHERE id=?", (len(rows), doc))
        db.log(con, user["id"], company_id, "saisie_simplifiee", body.mois)
    return {"ok": True, "n_values": len(rows)}


@app.get("/api/companies/{company_id}/documents")
def documents(company_id: int, user=Depends(current_user)):
    with db.tx() as con:
        require_read(con, user, company_id)
        return clean(services.public_documents(services.load_documents(con, company_id)))


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, user=Depends(current_user)):
    with db.tx() as con:
        d = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404)
        require_owner(con, user, d["company_id"])
        con.execute("DELETE FROM fin_values WHERE document_id=?", (doc_id,))
        con.execute("DELETE FROM transactions WHERE document_id=?", (doc_id,))
        con.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        db.log(con, user["id"], d["company_id"], "suppression_document", d["filename"])
    return {"ok": True}


@app.get("/api/companies/{company_id}/values")
def values(company_id: int, status: str | None = None, user=Depends(current_user)):
    with db.tx() as con:
        require_read(con, user, company_id)
        q = "SELECT * FROM fin_values WHERE company_id=?" + (" AND status=?" if status else "") + " ORDER BY period_end, item"
        rows = [dict(r) for r in con.execute(q, (company_id, status) if status else (company_id,))]
    for r in rows:
        r["item_label"] = services.item_label(r["item"])
    return clean(rows)


class Verify(BaseModel):
    ids: list[int] = Field(default=[], max_length=5000)
    document_id: int | None = None


@app.post("/api/companies/{company_id}/values/verify")
def verify(company_id: int, body: Verify, user=Depends(current_user)):
    with db.tx() as con:
        require_owner(con, user, company_id)
        if body.document_id:
            n = con.execute("UPDATE fin_values SET status='verifie', verified_by=?, verified_at=CURRENT_TIMESTAMP "
                            "WHERE company_id=? AND document_id=? AND status='extrait'", (user["id"], company_id, body.document_id)).rowcount
        else:
            n = 0
            for i in body.ids:
                n += con.execute("UPDATE fin_values SET status='verifie', verified_by=?, verified_at=CURRENT_TIMESTAMP "
                                 "WHERE company_id=? AND id=?", (user["id"], company_id, i)).rowcount
        db.log(con, user["id"], company_id, "verification_valeurs", f"{n} valeur(s)")
    return {"verified": n}


class Correct(BaseModel):
    amount: float = Field(allow_inf_nan=False, ge=-1e13, le=1e13)
    comment: str | None = Field(default=None, max_length=500)


@app.patch("/api/values/{value_id}")
def correct(value_id: int, body: Correct, user=Depends(current_user)):
    with db.tx() as con:
        v = con.execute("SELECT * FROM fin_values WHERE id=?", (value_id,)).fetchone()
        if not v:
            raise HTTPException(404)
        require_owner(con, user, v["company_id"])
        note = f"Corrigé de {v['amount']:,.0f} à {body.amount:,.0f}".replace(",", " ") + (f" : {body.comment}" if body.comment else "")
        con.execute("UPDATE fin_values SET amount=?, status='verifie', comment=?, verified_by=?, verified_at=CURRENT_TIMESTAMP WHERE id=?",
                    (body.amount, note, user["id"], value_id))
        db.log(con, user["id"], v["company_id"], "correction_valeur", note)
    return {"ok": True}


def _request(con, request_id):
    r = con.execute("SELECT * FROM credit_requests WHERE id=?", (request_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Demande introuvable")
    return dict(r)


@app.get("/api/companies/{company_id}/analysis")
def analysis(company_id: int, request_id: int | None = None,
             amount: Annotated[float | None, Query(gt=0, le=1e12)] = None,
             duration_months: Annotated[int | None, Query(gt=0, le=120)] = None,
             annual_rate: Annotated[float | None, Query(ge=0, le=1)] = None,
             taux_defaut: Annotated[float | None, Query(gt=0, lt=0.5)] = None, user=Depends(current_user)):
    with db.tx() as con:
        require_read(con, user, company_id)
        req = None
        if request_id:
            req = _request(con, request_id)
            if req["company_id"] != company_id:
                raise HTTPException(400)
        elif amount:
            req = {"amount": amount, "duration_months": duration_months or 12, "annual_rate": annual_rate or 0.15}
        res = services.full_analysis(con, company_id, req, local_default_rate=taux_defaut)
        if user["role"] == "institution":
            db.log(con, user["id"], company_id, "consultation_analyse", f"demande {request_id}" if request_id else None)
    return JSONResponse(clean(res))


# ------------------------------------------------------------------ partage
@app.get("/api/institutions")
def institutions(user=Depends(current_user)):
    with db.tx() as con:
        return [dict(r) for r in con.execute("SELECT id, display_name, organisation FROM users WHERE role='institution'")]


class Share(BaseModel):
    institution_id: int


@app.get("/api/companies/{company_id}/shares")
def list_shares(company_id: int, user=Depends(current_user)):
    with db.tx() as con:
        require_owner(con, user, company_id)
        return [dict(r) for r in con.execute(
            "SELECT s.*, u.display_name, u.organisation FROM shares s JOIN users u ON u.id=s.institution_user_id WHERE company_id=? ORDER BY s.id DESC",
            (company_id,))]


@app.post("/api/companies/{company_id}/shares")
def share(company_id: int, body: Share, user=Depends(current_user)):
    with db.tx() as con:
        require_owner(con, user, company_id)
        inst = con.execute("SELECT * FROM users WHERE id=? AND role='institution'", (body.institution_id,)).fetchone()
        if not inst:
            raise HTTPException(404, "Institution inconnue")
        if not con.execute("SELECT 1 FROM shares WHERE company_id=? AND institution_user_id=? AND revoked_at IS NULL",
                           (company_id, body.institution_id)).fetchone():
            con.execute("INSERT INTO shares(company_id, institution_user_id, granted_by) VALUES (?,?,?)", (company_id, body.institution_id, user["id"]))
        db.log(con, user["id"], company_id, "autorisation_partage", inst["organisation"] or inst["display_name"])
    return {"ok": True}


@app.delete("/api/shares/{share_id}")
def revoke(share_id: int, user=Depends(current_user)):
    with db.tx() as con:
        s = con.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
        if not s:
            raise HTTPException(404)
        require_owner(con, user, s["company_id"])
        con.execute("UPDATE shares SET revoked_at=CURRENT_TIMESTAMP WHERE id=?", (share_id,))
        db.log(con, user["id"], s["company_id"], "retrait_partage", str(s["institution_user_id"]))
    return {"ok": True}


@app.get("/api/companies/{company_id}/access-log")
def access_log(company_id: int, user=Depends(current_user)):
    with db.tx() as con:
        require_owner(con, user, company_id)
        return [dict(r) for r in con.execute(
            "SELECT a.at, a.action, a.detail, u.display_name, u.organisation, u.role FROM access_log a LEFT JOIN users u ON u.id=a.user_id "
            "WHERE a.company_id=? ORDER BY a.id DESC LIMIT 100", (company_id,))]


class DossierExport(BaseModel):
    password: str | None = Field(default=None, max_length=128)


@app.post("/api/companies/{company_id}/dossier.pdf")
def dossier(company_id: int, body: DossierExport, user=Depends(current_user)):
    password = body.password
    with db.tx() as con:
        require_owner(con, user, company_id)
        a = services.full_analysis(con, company_id)
        if a.get("empty"):
            raise HTTPException(400, "Aucune donnée à exporter")
        pdf = reports.dossier_pdf(a, services.dossier_payload(con, company_id), password or None)
        db.log(con, user["id"], company_id, "export_dossier_pdf", "chiffré" if password else "non chiffré")
    name = a["company"]["name"].replace(" ", "_")
    return Response(pdf, media_type="application/pdf", headers=attachment(f"Dossier_{name}.pdf"))


# ------------------------------------------------------------------ institution
class NewCompany(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sector: Text = None
    city: Text = None


@app.post("/api/companies")
def create_company(body: NewCompany, user=Depends(current_user)):
    """Une institution ouvre un dossier pour téléverser le fichier transmis par un commerçant."""
    with db.tx() as con:
        cid = con.execute("INSERT INTO companies(owner_user_id, name, sector, city) VALUES (?,?,?,?)",
                          (user["id"], body.name, body.sector, body.city)).lastrowid
        db.log(con, user["id"], cid, "creation_dossier")
    return {"id": cid}


@app.get("/api/dossiers")
def dossiers(user=Depends(current_user)):
    if user["role"] != "institution":
        raise HTTPException(403)
    with db.tx() as con:
        rows = con.execute(
            "SELECT c.*, s.granted_at, 'partage' AS access FROM companies c JOIN shares s ON s.company_id=c.id "
            "WHERE s.institution_user_id=? AND s.revoked_at IS NULL "
            "UNION SELECT c.*, c.created_at, 'televerse' FROM companies c WHERE c.owner_user_id=?", (user["id"], user["id"])).fetchall()
        out = []
        for r in rows:
            reqs = [dict(x) for x in con.execute("SELECT * FROM credit_requests WHERE company_id=? AND institution_user_id=? ORDER BY id DESC",
                                                 (r["id"], user["id"]))]
            for q in reqs:
                d = con.execute("SELECT d.*, u.display_name AS analyst FROM decisions d JOIN users u ON u.id=d.analyst_user_id "
                                "WHERE request_id=? ORDER BY d.id DESC LIMIT 1", (q["id"],)).fetchone()
                q["decision"] = dict(d) if d else None
            out.append({**dict(r), "requests": reqs})
    return clean(out)


class NewRequest(BaseModel):
    company_id: int
    amount: float = Field(gt=0)
    duration_months: int = Field(gt=0, le=120)
    annual_rate: float = Field(ge=0, le=1)
    purpose: str | None = Field(default=None, max_length=200)


@app.post("/api/requests")
def create_request(body: NewRequest, user=Depends(current_user)):
    if user["role"] != "institution":
        raise HTTPException(403)
    with db.tx() as con:
        require_read(con, user, body.company_id)
        rid = con.execute("INSERT INTO credit_requests(company_id, institution_user_id, amount, duration_months, annual_rate, purpose) "
                          "VALUES (?,?,?,?,?,?)", (body.company_id, user["id"], body.amount, body.duration_months, body.annual_rate,
                                                  body.purpose)).lastrowid
        db.log(con, user["id"], body.company_id, "creation_demande_credit", f"{body.amount:,.0f} FCFA".replace(",", " "))
    return {"id": rid}


class Decision(BaseModel):
    decision: str = Field(pattern="^(Accordé|Accordé sous conditions|Refusé|Ajourné : pièces complémentaires)$")
    comment: str = Field(min_length=5, max_length=2000)


@app.post("/api/requests/{request_id}/decision")
def decide(request_id: int, body: Decision, user=Depends(current_user)):
    with db.tx() as con:
        req = _request(con, request_id)
        if req["institution_user_id"] != user["id"]:
            raise HTTPException(403, "Seul l'analyste de l'institution peut décider")
        require_read(con, user, req["company_id"])
        a = services.full_analysis(con, req["company_id"], req)
        con.execute("INSERT INTO decisions(request_id, analyst_user_id, decision, comment, score, pd) VALUES (?,?,?,?,?,?)",
                    (request_id, user["id"], body.decision, body.comment, a["score"]["score"], a["pd"].get("pd")))
        con.execute("UPDATE credit_requests SET status=? WHERE id=?", (body.decision, request_id))
        db.log(con, user["id"], req["company_id"], "decision_credit", body.decision)
    return {"ok": True}


@app.get("/api/requests/{request_id}/report.pdf")
def report(request_id: int, taux_defaut: Annotated[float | None, Query(gt=0, lt=0.5)] = None, user=Depends(current_user)):
    with db.tx() as con:
        req = _request(con, request_id)
        require_read(con, user, req["company_id"])
        a = services.full_analysis(con, req["company_id"], req, local_default_rate=taux_defaut)
        d = con.execute("SELECT d.*, u.display_name AS analyst FROM decisions d JOIN users u ON u.id=d.analyst_user_id "
                        "WHERE request_id=? ORDER BY d.id DESC LIMIT 1", (request_id,)).fetchone()
        pdf = reports.analysis_report(a, req, f"{user['display_name']} ({user['organisation'] or ''})", dict(d) if d else None)
        db.log(con, user["id"], req["company_id"], "telechargement_rapport", f"demande {request_id}")
    name = a["company"]["name"].replace(" ", "_")
    return Response(pdf, media_type="application/pdf", headers=attachment(f"Rapport_CreditWise_{name}.pdf"))


@app.get("/api/health")
def health():
    """État du déploiement, sans aucun secret : utile pour diagnostiquer Vercel."""
    return {"ok": True, "vercel": db.ON_VERCEL, "model": (ROOT / "models" / "pd_model.json").exists(),
            "demo_files": (ROOT / "data" / "demo").is_dir(), "frontend": (ROOT / "frontend" / "index.html").exists(),
            "email_delivery": otp.smtp_configured(), "google": bool(otp.google_client_id())}


@app.get("/api/model-card")
def model_card():
    return json.loads((ROOT / "models" / "model_card.json").read_text())


@app.get("/api/demo-files")
def demo_files():
    base = ROOT / "data" / "demo"
    return [{"company": p.parent.name, "name": p.name, "url": f"/demo/{p.parent.name}/{p.name}"} for p in sorted(base.glob("*/*"))]


if (ROOT / "data" / "demo").is_dir():  # absent si le dossier n'a pas été inclus dans le déploiement
    app.mount("/demo", StaticFiles(directory=ROOT / "data" / "demo"), name="demo")
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": getattr(exc, "detail", "Introuvable")}, status_code=404)
    return FileResponse(ROOT / "frontend" / "index.html")
