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
    pdf = m.get(f"/api/companies/{cid}/dossier.pdf").content
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
