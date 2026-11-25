"""Connexion sans mot de passe : code à 6 chiffres envoyé par e-mail, et connexion Google.

Le code n'est jamais stocké en clair. Le serveur renvoie au navigateur un « défi » signé (HMAC) qui
contient l'adresse, le profil saisi, l'échéance et une empreinte du code. À la vérification, le serveur
recalcule l'empreinte avec le code saisi. Aucune table n'est nécessaire : cela fonctionne aussi quand
plusieurs instances servent l'application (Vercel).

Envoi des e-mails : serveur SMTP défini par SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM.
Sans SMTP et avec CREDITWISE_DEMO_CODES=1 (valeur par défaut du prototype), le code est affiché à l'écran.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage

CODE_TTL = 600          # 10 minutes
MAX_CODES = 5           # envois par adresse sur 15 minutes
MAX_ATTEMPTS = 5        # essais par code
_sent: dict[str, list[float]] = {}
_attempts: dict[str, int] = {}


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("MAIL_FROM"))


def demo_codes() -> bool:
    return not smtp_configured() and os.environ.get("CREDITWISE_DEMO_CODES", "1") == "1"


def google_client_id() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_ID") or None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(secret: bytes, *parts: str) -> str:
    return hmac.new(secret, "|".join(parts).encode(), hashlib.sha256).hexdigest()


def can_send(email: str) -> bool:
    now = time.time()
    recent = [t for t in _sent.get(email, []) if now - t < 900]
    _sent[email] = recent
    return len(recent) < MAX_CODES


def new_challenge(secret: bytes, email: str, role: str, mode: str, profile: dict | None) -> tuple[str, str]:
    """Retourne (défi signé, code). Le défi ne permet pas de retrouver le code."""
    code = f"{secrets.randbelow(10**6):06d}"
    exp = int(time.time()) + CODE_TTL
    nonce = secrets.token_hex(8)
    body = {"e": email, "r": role, "m": mode, "p": profile or {}, "x": exp, "n": nonce,
            "h": _mac(secret, "code", email, nonce, str(exp), code)}
    raw = _b64(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
    _sent.setdefault(email, []).append(time.time())
    return f"{raw}.{_mac(secret, 'challenge', raw)}", code


def check_challenge(secret: bytes, challenge: str, code: str) -> dict:
    """Vérifie le défi et le code. Lève ValueError avec un message affichable."""
    try:
        raw, sig = challenge.split(".")
        ok_sig = hmac.compare_digest(_mac(secret, "challenge", raw), sig)
        body = json.loads(_unb64(raw)) if ok_sig else None
    except (ValueError, json.JSONDecodeError):
        body = None
    if not body:
        raise ValueError("Demande invalide : recommencez.")
    if body["x"] < time.time():
        raise ValueError("Code expiré : demandez-en un nouveau.")
    key = body["n"]
    if _attempts.get(key, 0) >= MAX_ATTEMPTS:
        raise ValueError("Trop d'essais : demandez un nouveau code.")
    code = "".join(ch for ch in str(code) if ch.isdigit())[:6]
    if not hmac.compare_digest(_mac(secret, "code", body["e"], body["n"], str(body["x"]), code), body["h"]):
        _attempts[key] = _attempts.get(key, 0) + 1
        raise ValueError("Code incorrect.")
    _attempts[key] = MAX_ATTEMPTS  # un code ne sert qu'une fois sur cette instance
    return body


def send_code(email: str, code: str) -> bool:
    """Envoie le code par SMTP. Retourne False si aucun serveur n'est configuré."""
    if not smtp_configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Votre code CreditWise : {code}"
    msg["From"] = os.environ["MAIL_FROM"]
    msg["To"] = email
    msg.set_content(f"Votre code de connexion CreditWise est {code}.\n"
                    f"Il est valable 10 minutes. Si vous n'avez rien demandé, ignorez ce message.")
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=10) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        logging.getLogger(__name__).exception("Envoi du code impossible")
        raise


def verify_google(credential: str) -> dict:
    """Vérifie un jeton d'identité Google auprès de Google. Retourne {email, name}."""
    client_id = google_client_id()
    if not client_id:
        raise ValueError("Connexion Google non configurée.")
    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": credential})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            info = json.loads(r.read())
    except OSError:
        raise ValueError("Jeton Google refusé.") from None
    if info.get("aud") != client_id or info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Jeton Google refusé.")
    if info.get("email_verified") not in (True, "true") or int(info.get("exp", 0)) < time.time():
        raise ValueError("Adresse Google non vérifiée ou jeton expiré.")
    return {"email": info["email"].lower(), "name": info.get("name") or info["email"].split("@")[0]}


def mask(email: str) -> str:
    user, _, domain = email.partition("@")
    return (user[:2] + "•" * max(1, len(user) - 2)) + "@" + domain
