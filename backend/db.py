"""Stockage SQLite. Chaque valeur financière suit le format interne recommandé par le guide :
entreprise, période début/fin, date d'import, document source, poste, montant, devise, unité,
statut (déclaré / extrait / vérifié / estimé), commentaire."""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Sur Vercel, seul /tmp est inscriptible : la base de démonstration y est recréée à chaque démarrage à froid.
ON_VERCEL = bool(os.environ.get("VERCEL"))
_DATA = Path("/tmp/creditwise") if ON_VERCEL else ROOT / "data"
DB_PATH = Path(os.environ.get("CREDITWISE_DB", _DATA / "creditwise.db"))
UPLOADS = Path(os.environ.get("CREDITWISE_UPLOADS", _DATA / "uploads"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('merchant','institution')), display_name TEXT NOT NULL,
  organisation TEXT, accepted_terms_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL, name TEXT NOT NULL, sector TEXT, city TEXT,
  has_accounting_software INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, filename TEXT NOT NULL, kind TEXT, format TEXT,
  sha256 TEXT NOT NULL, path TEXT NOT NULL, uploaded_by INTEGER, uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
  n_values INTEGER DEFAULT 0, n_transactions INTEGER DEFAULT 0, unmatched TEXT, warnings TEXT);
CREATE TABLE IF NOT EXISTS fin_values (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  imported_at TEXT DEFAULT CURRENT_TIMESTAMP, document_id INTEGER, source_name TEXT, item TEXT NOT NULL,
  amount REAL NOT NULL, currency TEXT DEFAULT 'XOF', unit TEXT DEFAULT 'FCFA',
  status TEXT NOT NULL CHECK (status IN ('declare','extrait','verifie','estime')),
  source_label TEXT, confidence REAL, comment TEXT, verified_by INTEGER, verified_at TEXT);
CREATE INDEX IF NOT EXISTS ix_values_company ON fin_values(company_id);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, document_id INTEGER, date TEXT, raw_date TEXT,
  reference TEXT, counterparty TEXT, label TEXT, account TEXT, debit REAL, credit REAL);
CREATE INDEX IF NOT EXISTS ix_tx_company ON transactions(company_id);
CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, institution_user_id INTEGER NOT NULL,
  granted_by INTEGER NOT NULL, granted_at TEXT DEFAULT CURRENT_TIMESTAMP, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS credit_requests (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, institution_user_id INTEGER NOT NULL,
  amount REAL NOT NULL, duration_months INTEGER NOT NULL, annual_rate REAL NOT NULL, purpose TEXT,
  status TEXT DEFAULT 'en_analyse', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, analyst_user_id INTEGER NOT NULL, decision TEXT NOT NULL,
  comment TEXT NOT NULL, score REAL, pd REAL, decided_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS access_log (
  id INTEGER PRIMARY KEY, user_id INTEGER, company_id INTEGER, action TEXT NOT NULL, detail TEXT,
  at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with tx() as con:
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
        if "accepted_terms_at" not in cols:  # base créée avant l'ajout de la colonne
            con.execute("ALTER TABLE users ADD COLUMN accepted_terms_at TEXT")


def is_empty() -> bool:
    with tx() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(hash_password(pw, salt), stored)


def log(con, user_id, company_id, action, detail=None) -> None:
    con.execute("INSERT INTO access_log(user_id, company_id, action, detail) VALUES (?,?,?,?)",
                (user_id, company_id, action, detail))
