"""Initialise la base de démonstration (les fichiers passent par le vrai pipeline d'import).

Comptes (mot de passe : demo) :
  akwaba    : commerçante, Boutique Akwaba Mode (A)
  solidite  : commerçant, Quincaillerie La Solidité (B)
  bonprix   : commerçant, Alimentation Générale Le Bon Prix (C)
  nouveau   : commerçant sans données (import en direct pendant la démo)
  analyste  : analyste crédit, institution de microfinance fictive
Usage : python -m backend.seed
"""
from __future__ import annotations

from pathlib import Path

from . import db, services

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"

MERCHANTS = [
    ("akwaba", "Afi K. (fictive)", "A", "Boutique Akwaba Mode", "Commerce de vêtements", "Cotonou", 1,
     dict(amount=2_000_000, duration_months=12, annual_rate=0.15, purpose="Constitution du stock pour les fêtes de fin d'année")),
    ("solidite", "Koffi D. (fictif)", "B", "Quincaillerie La Solidité", "Quincaillerie", "Porto-Novo", 0,
     dict(amount=1_500_000, duration_months=18, annual_rate=0.15, purpose="Reconstitution de trésorerie")),
    ("bonprix", "Rachida B. (fictive)", "C", "Alimentation Générale Le Bon Prix", "Alimentation générale", "Parakou", 0,
     dict(amount=1_000_000, duration_months=12, annual_rate=0.15, purpose="Achat d'un congélateur et de stock")),
]


def main() -> None:
    """Réinitialise complètement la base de démonstration."""
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    if db.UPLOADS.exists():
        for f in db.UPLOADS.glob("*"):
            f.unlink()
    db.init()
    populate()
    print("Base initialisée :", db.DB_PATH)


def populate() -> None:
    """Crée les comptes et importe les fichiers de démonstration dans une base vide."""
    with db.tx() as con:
        inst = con.execute("INSERT INTO users(username, password_hash, role, display_name, organisation) VALUES (?,?,?,?,?)",
                           ("analyste", db.hash_password("demo"), "institution", "Analyste crédit", "Microfinance Démo (fictive)")).lastrowid
        for username, person, key, company, sector, city, soft, req in MERCHANTS:
            uid = con.execute("INSERT INTO users(username, password_hash, role, display_name) VALUES (?,?,?,?)",
                              (username, db.hash_password("demo"), "merchant", person)).lastrowid
            cid = con.execute("INSERT INTO companies(owner_user_id, name, sector, city, has_accounting_software) VALUES (?,?,?,?,?)",
                              (uid, company, sector, city, soft)).lastrowid
            for f in sorted((DEMO / key).iterdir()):
                services.import_document(con, cid, uid, f.name, f.read_bytes())
            con.execute("INSERT INTO shares(company_id, institution_user_id, granted_by) VALUES (?,?,?)", (cid, inst, uid))
            db.log(con, uid, cid, "autorisation_partage", "Microfinance Démo (fictive)")
            con.execute("INSERT INTO credit_requests(company_id, institution_user_id, amount, duration_months, annual_rate, purpose) "
                        "VALUES (?,?,?,?,?,?)", (cid, inst, req["amount"], req["duration_months"], req["annual_rate"], req["purpose"]))
        uid = con.execute("INSERT INTO users(username, password_hash, role, display_name) VALUES (?,?,?,?)",
                          ("nouveau", db.hash_password("demo"), "merchant", "Nouveau commerçant")).lastrowid
        con.execute("INSERT INTO companies(owner_user_id, name, sector, city) VALUES (?,?,?,?)",
                    (uid, "Mon commerce (démo en direct)", "Commerce", "Cotonou"))


if __name__ == "__main__":
    main()
