"""API CreditWise (FastAPI). Lancer : uvicorn backend.app:app --reload"""
from __future__ import annotations

import json
import math
import secrets
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, reports, services

ROOT = Path(__file__).resolve().parents[1]
from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="CreditWise", version="0.1", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-cache"  # l'interface est toujours à jour pendant la démo
    return resp
MAX_UPLOAD = 15 * 1024 * 1024


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
class Login(BaseModel):
    username: str
    password: str


class Register(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=4)
    role: str = Field(pattern="^(merchant|institution)$")
    display_name: str
    organisation: str | None = None
    company_name: str | None = None
    sector: str | None = None
    city: str | None = None
    has_accounting_software: bool = False


def current_user(request: Request) -> dict:
    token = request.cookies.get("cw_session")
    if not token:
        raise HTTPException(401, "Connexion requise")
    with db.tx() as con:
        row = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "Session expirée")
    return {k: row[k] for k in ("id", "username", "role", "display_name", "organisation")}


def _session(resp: Response, con, user_id: int):
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions(token, user_id) VALUES (?,?)", (token, user_id))
    resp.set_cookie("cw_session", token, httponly=True, samesite="lax", max_age=8 * 3600)


@app.post("/api/login")
def login(body: Login, resp: Response):
    with db.tx() as con:
        u = con.execute("SELECT * FROM users WHERE username=?", (body.username.strip().lower(),)).fetchone()
        if not u or not db.check_password(body.password, u["password_hash"]):
            raise HTTPException(401, "Identifiant ou mot de passe incorrect")
        _session(resp, con, u["id"])
        db.log(con, u["id"], None, "connexion")
    return {"ok": True, "role": u["role"]}


@app.post("/api/register")
def register(body: Register, resp: Response):
    with db.tx() as con:
        if con.execute("SELECT 1 FROM users WHERE username=?", (body.username.lower(),)).fetchone():
            raise HTTPException(409, "Identifiant déjà utilisé")
        uid = con.execute("INSERT INTO users(username, password_hash, role, display_name, organisation) VALUES (?,?,?,?,?)",
                          (body.username.lower(), db.hash_password(body.password), body.role, body.display_name,
                           body.organisation)).lastrowid
        if body.role == "merchant":
            con.execute("INSERT INTO companies(owner_user_id, name, sector, city, has_accounting_software) VALUES (?,?,?,?,?)",
                        (uid, body.company_name or body.display_name, body.sector, body.city, int(body.has_accounting_software)))
        _session(resp, con, uid)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, resp: Response):
    with db.tx() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (request.cookies.get("cw_session"),))
    resp.delete_cookie("cw_session")
    return {"ok": True}


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
    results = []
    with db.tx() as con:
        require_owner(con, user, company_id)
        for f in files:
            data = await f.read()
            if len(data) > MAX_UPLOAD:
                results.append({"filename": f.filename, "warnings": ["Fichier trop volumineux (15 Mo max)."], "n_values": 0})
                continue
            results.append(services.import_document(con, company_id, user["id"], f.filename, data))
    return clean({"results": results})


@app.get("/api/companies/{company_id}/documents")
def documents(company_id: int, user=Depends(current_user)):
    with db.tx() as con:
        require_read(con, user, company_id)
        return clean(services.load_documents(con, company_id))


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
    ids: list[int] = []
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
    amount: float
    comment: str | None = None


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
def analysis(company_id: int, request_id: int | None = None, amount: float | None = None, duration_months: int | None = None,
             annual_rate: float | None = None, user=Depends(current_user)):
    with db.tx() as con:
        require_read(con, user, company_id)
        req = None
        if request_id:
            req = _request(con, request_id)
            if req["company_id"] != company_id:
                raise HTTPException(400)
        elif amount:
            req = {"amount": amount, "duration_months": duration_months or 12, "annual_rate": annual_rate or 0.15}
        res = services.full_analysis(con, company_id, req)
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


@app.get("/api/companies/{company_id}/dossier.pdf")
def dossier(company_id: int, password: str | None = None, user=Depends(current_user)):
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
    name: str
    sector: str | None = None
    city: str | None = None


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
    purpose: str | None = None


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
    comment: str = Field(min_length=5)


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
def report(request_id: int, user=Depends(current_user)):
    with db.tx() as con:
        req = _request(con, request_id)
        require_read(con, user, req["company_id"])
        a = services.full_analysis(con, req["company_id"], req)
        d = con.execute("SELECT d.*, u.display_name AS analyst FROM decisions d JOIN users u ON u.id=d.analyst_user_id "
                        "WHERE request_id=? ORDER BY d.id DESC LIMIT 1", (request_id,)).fetchone()
        pdf = reports.analysis_report(a, req, f"{user['display_name']} ({user['organisation'] or ''})", dict(d) if d else None)
        db.log(con, user["id"], req["company_id"], "telechargement_rapport", f"demande {request_id}")
    name = a["company"]["name"].replace(" ", "_")
    return Response(pdf, media_type="application/pdf", headers=attachment(f"Rapport_CreditWise_{name}.pdf"))


@app.get("/api/model-card")
def model_card():
    return json.loads((ROOT / "models" / "model_card.json").read_text())


@app.get("/api/demo-files")
def demo_files():
    base = ROOT / "data" / "demo"
    return [{"company": p.parent.name, "name": p.name, "url": f"/demo/{p.parent.name}/{p.name}"} for p in sorted(base.glob("*/*"))]


app.mount("/demo", StaticFiles(directory=ROOT / "data" / "demo"), name="demo")
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": getattr(exc, "detail", "Introuvable")}, status_code=404)
    return FileResponse(ROOT / "frontend" / "index.html")
