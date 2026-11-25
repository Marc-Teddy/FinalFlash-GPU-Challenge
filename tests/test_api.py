"""Parcours de bout en bout sur la base de démonstration (fichiers réellement importés)."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    tmp = tmp_path_factory.mktemp("cw")
    os.environ["CREDITWISE_DB"] = str(tmp / "test.db")
    os.environ["CREDITWISE_UPLOADS"] = str(tmp / "uploads")
    import importlib

    from backend import db
    importlib.reload(db)
    from backend import services, seed
    importlib.reload(services)
    importlib.reload(seed)
    seed.main()
    from backend import app as app_module
    importlib.reload(app_module)
    return app_module.app


def login(app, user):
    c = TestClient(app)
    assert c.post("/api/login", json={"username": user, "password": "demo"}).status_code == 200
    return c


def test_trois_profils_differencies(client):
    c = login(client, "analyste")
    res = {}
    for d in c.get("/api/dossiers").json():
        a = c.get(f"/api/companies/{d['id']}/analysis", params={"request_id": d["requests"][0]["id"]}).json()
        res[d["name"]] = a
    A, B, C = res["Boutique Akwaba Mode"], res["Quincaillerie La Solidité"], res["Alimentation Générale Le Bon Prix"]
    assert A["score"]["score"] >= 80 and not [x for x in A["alerts"] if x["severity"] == "elevee"]
    assert B["score"]["score"] < 60 and any(x["code"] == "baisse_prolongee" for x in B["alerts"])
    assert {"doublons", "ecart_grand_livre", "montant_inhabituel", "date_impossible", "poste_absent_mois"} <= {x["code"] for x in C["alerts"]}
    assert C["score"]["capped"] and "examiner" in C["score"]["category"]
    assert A["pd"]["pd"] < B["pd"]["pd"]


def test_acces_refuse_sans_autorisation(client):
    akwaba = login(client, "akwaba")
    cid = akwaba.get("/api/me").json()["companies"][0]["id"]
    other = login(client, "solidite")
    assert other.get(f"/api/companies/{cid}/analysis").status_code == 403


def test_dossier_signe_aller_retour_et_falsification(client):
    m = login(client, "akwaba")
    cid = m.get("/api/me").json()["companies"][0]["id"]
    pdf = m.post(f"/api/companies/{cid}/dossier.pdf", json={}).content
    inst = login(client, "analyste")
    new = inst.post("/api/companies", json={"name": "Dossier reçu"}).json()["id"]
    ok = inst.post(f"/api/companies/{new}/documents", files=[("files", ("d.pdf", pdf, "application/pdf"))]).json()["results"][0]
    assert ok["kind"] == "dossier_creditwise" and ok["n_values"] > 500
    payload = json.loads(PdfReader(io.BytesIO(pdf)).attachments["creditwise_dossier.json"][0])
    payload["data"]["values"][0]["amount"] *= 3
    w = PdfWriter()
    for p in PdfReader(io.BytesIO(pdf)).pages:
        w.add_page(p)
    w.add_attachment("creditwise_dossier.json", json.dumps(payload).encode())
    buf = io.BytesIO()
    w.write(buf)
    bad = inst.post(f"/api/companies/{new}/documents", files=[("files", ("x.pdf", buf.getvalue(), "application/pdf"))]).json()["results"][0]
    assert bad["n_values"] == 0 and "invalide" in bad["warnings"][0]


def test_rapport_et_decision_traces(client):
    c = login(client, "analyste")
    assert c.post("/api/requests/1/decision", json={"decision": "Accordé", "comment": "DSCR suffisant."}).status_code == 200
    r = c.get("/api/requests/1/report.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    m = login(client, "akwaba")
    cid = m.get("/api/me").json()["companies"][0]["id"]
    actions = {x["action"] for x in m.get(f"/api/companies/{cid}/access-log").json()}
    assert {"decision_credit", "telechargement_rapport", "consultation_analyse"} <= actions


def test_securite_entrees_et_details_internes(client):
    c = login(client, "akwaba")
    cid = c.get("/api/me").json()["companies"][0]["id"]
    # pas de chemin serveur exposé
    assert all("path" not in d for d in c.get(f"/api/companies/{cid}/documents").json())
    # format de fichier refusé, nom assaini
    r = c.post(f"/api/companies/{cid}/documents", files=[("files", ("../../evil.sh", b"x", "text/plain"))]).json()["results"][0]
    assert r["n_values"] == 0 and "/" not in r["filename"]
    # entrées invalides refusées
    assert c.get(f"/api/companies/{cid}/analysis", params={"amount": -5}).status_code == 422
    assert TestClient(client).post("/api/auth/code", json={"email": "pas-une-adresse", "role": "merchant",
                                                          "mode": "login"}).status_code == 422
    # en-têtes de sécurité et documentation interne non publiée
    assert c.get("/").headers["x-frame-options"] == "DENY"
    assert c.get("/openapi.json").status_code == 404 or "openapi" not in c.get("/openapi.json").text


def test_limitation_des_tentatives(client):
    c = TestClient(client)
    codes = [c.post("/api/login", json={"username": "bonprix", "password": "faux"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_connexion_refusee_dans_le_mauvais_espace(client):
    c = TestClient(client)
    r = c.post("/api/login", json={"username": "analyste", "password": "demo", "role": "merchant"})
    assert r.status_code == 403 and "établissement" in r.json()["detail"]
    assert c.post("/api/login", json={"username": "analyste", "password": "demo", "role": "institution"}).status_code == 200


def test_session_sans_erreur(client):
    c = TestClient(client)
    assert c.get("/api/session").json() == {"authenticated": False}
    c.post("/api/login", json={"username": "akwaba", "password": "demo"})
    r = c.get("/api/session").json()
    assert r["authenticated"] and r["role"] == "merchant" and r["companies"]


def test_cookie_falsifie_refuse(client):
    c = TestClient(client)
    c.cookies.set("cw_session", "1.9999999999.signaturebidon")
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/session").json() == {"authenticated": False}


PROFIL = {"full_name": "Amivi Dossou", "company_name": "Boutique Test", "category": "Alimentation", "city": "Cotonou"}


def test_inscription_par_code(client):
    c = TestClient(client)
    # conditions non acceptées : refus
    r = c.post("/api/auth/code", json={"email": "amivi@exemple.bj", "role": "merchant", "mode": "signup", "profile": PROFIL})
    assert r.status_code == 400
    r = c.post("/api/auth/code", json={"email": "Amivi@Exemple.bj", "role": "merchant", "mode": "signup",
                                       "profile": PROFIL, "accept_terms": True}).json()
    assert r["sent_to"].startswith("am") and len(r["demo_code"]) == 6
    # mauvais code refusé, bon code accepté, compte et commerce créés
    assert c.post("/api/auth/verify", json={"challenge": r["challenge"], "code": "000000" if r["demo_code"] != "000000" else "111111"}).status_code == 400
    assert c.post("/api/auth/verify", json={"challenge": r["challenge"], "code": r["demo_code"]}).json()["role"] == "merchant"
    me = c.get("/api/me").json()
    assert me["username"] == "amivi@exemple.bj" and me["companies"][0]["name"] == "Boutique Test"
    # le même code ne sert pas deux fois
    assert TestClient(client).post("/api/auth/verify", json={"challenge": r["challenge"], "code": r["demo_code"]}).status_code == 400
    # nouvelle inscription avec la même adresse : refus
    assert c.post("/api/auth/code", json={"email": "amivi@exemple.bj", "role": "merchant", "mode": "signup",
                                          "profile": PROFIL, "accept_terms": True}).status_code == 409


def test_connexion_par_code_et_defi_falsifie(client):
    c = TestClient(client)
    r = c.post("/api/auth/code", json={"email": "amivi@exemple.bj", "role": "merchant", "mode": "login"}).json()
    raw, sig = r["challenge"].split(".")
    assert c.post("/api/auth/verify", json={"challenge": raw + "." + ("1" if sig[0] == "0" else "0") + sig[1:], "code": r["demo_code"]}).status_code == 400
    assert c.post("/api/auth/verify", json={"challenge": r["challenge"], "code": r["demo_code"]}).status_code == 200
    # adresse inconnue : même réponse (pas de divulgation), mais aucune session possible
    r = c.post("/api/auth/code", json={"email": "inconnu@exemple.bj", "role": "merchant", "mode": "login"}).json()
    assert c.post("/api/auth/verify", json={"challenge": r["challenge"], "code": r["demo_code"]}).status_code == 404
    # mauvais espace
    r = c.post("/api/auth/code", json={"email": "amivi@exemple.bj", "role": "institution", "mode": "login"}).json()
    assert c.post("/api/auth/verify", json={"challenge": r["challenge"], "code": r["demo_code"]}).status_code == 403


def test_session_restauree_sur_une_autre_instance(client):
    """Sur Vercel, une autre instance ne connaît pas le compte : le cookie signé suffit à le restaurer."""
    from backend import db
    c = TestClient(client)
    r = c.post("/api/auth/code", json={"email": "instance@exemple.bj", "role": "merchant", "mode": "signup",
                                       "profile": PROFIL, "accept_terms": True}).json()
    assert c.post("/api/auth/verify", json={"challenge": r["challenge"], "code": r["demo_code"]}).status_code == 200
    with db.tx() as con:  # simule une instance qui n'a jamais vu ce compte
        uid = con.execute("SELECT id FROM users WHERE username='instance@exemple.bj'").fetchone()[0]
        con.execute("DELETE FROM companies WHERE owner_user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE id=?", (uid,))
    me = c.get("/api/me").json()
    assert me["username"] == "instance@exemple.bj" and me["companies"][0]["name"] == "Boutique Test"


def test_saisie_simplifiee_et_rapprochement(client):
    c = login(client, "nouveau")
    cid = c.get("/api/me").json()["companies"][0]["id"]
    for i, mois in enumerate(["2026-08", "2026-09", "2026-10"]):
        r = c.post(f"/api/companies/{cid}/saisie", json={"mois": mois, "ventes": 900_000 + 50_000 * i, "achats_marchandises": 600_000,
                                                         "loyers": 50_000, "tresorerie": 300_000, "stocks": 400_000, "dettes_fournisseurs": 100_000})
        assert r.status_code == 200
    a = c.get(f"/api/companies/{cid}/analysis").json()
    assert a["coverage"]["n_months_pnl"] == 3 and a["coverage"]["status_counts"].get("estime")
    assert a["ratios_by_key"] if "ratios_by_key" in a else True
    assert c.post(f"/api/companies/{cid}/saisie", json={"mois": "2026-13", "ventes": 1}).status_code == 422
    # le grand livre du commerçant A justifie ses ventes déclarées
    an = login(client, "analyste")
    a = an.get("/api/companies/1/analysis", params={"request_id": 1, "taux_defaut": 0.03}).json()
    assert a["proof"]["justified_months"] >= 20 and a["coverage"]["status_counts"]["justifie"] >= 20
    assert a["pd"]["recalibrated"] and a["pd"]["pd"] < a["pd"]["pd_raw"]
