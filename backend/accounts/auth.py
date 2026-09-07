"""Hashing password ed helper di validazione per l'autenticazione — senza
dipendenze esterne (niente bcrypt/passlib): usa hashlib.pbkdf2_hmac, incluso
nella libreria standard di Python, quindi nessun pacchetto in più da
installare sul server. Sufficientemente robusto per un'applicazione con
questo profilo di utenza (uno studio, non un servizio di massa)."""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import secrets

_ALGO = "sha256"
_ITERAZIONI = 260_000  # in linea con le raccomandazioni OWASP 2024 per PBKDF2-SHA256


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), _ITERAZIONI)
    return f"pbkdf2_{_ALGO}${_ITERAZIONI}${salt}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo_label, iterazioni_str, salt, derived_hex = stored.split("$")
        algo = algo_label.replace("pbkdf2_", "")
        iterazioni = int(iterazioni_str)
    except (ValueError, AttributeError):
        return False
    candidato = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), bytes.fromhex(salt), iterazioni)
    return hmac.compare_digest(candidato.hex(), derived_hex)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


def password_valida(password: str) -> str | None:
    """Ritorna None se la password va bene, altrimenti il messaggio d'errore
    da mostrare all'utente."""
    if not password or len(password) < 8:
        return "La password deve essere di almeno 8 caratteri."
    return None
