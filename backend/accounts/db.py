"""Database (SQLite) di account utente e progetti salvati in cloud — separato
dal database dei prezzari (stesso volume persistente, file diverso) per
tenere ben distinti i dati "di sistema" (prezzari, condivisi) da quelli
"di utente" (account, progetti, personali). Pensato per crescere in futuro
con i campi di abbonamento/fatturazione (vedi il campo 'piano' su 'utenti'
e le note nel modulo backend/accounts/auth.py), senza integrare per ora
nessun vero pagamento: qui c'è solo la struttura dati che lo renderà
possibile quando servirà."""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS utenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nome TEXT NOT NULL DEFAULT '',
    -- Piano di abbonamento: solo 'free' per ora (nessuna limitazione applicata
    -- né alcun pagamento richiesto/gestito). Il campo esiste già così che,
    -- quando in futuro si introdurranno piani a pagamento, non serva una
    -- migrazione dello schema per aggiungerlo — solo per iniziare a
    -- valorizzarlo davvero.
    piano TEXT NOT NULL DEFAULT 'free',
    creato_il TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS progetti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente_id INTEGER NOT NULL REFERENCES utenti(id),
    nome TEXT NOT NULL,
    committente TEXT NOT NULL DEFAULT '',
    ubicazione TEXT NOT NULL DEFAULT '',
    totale_testo TEXT NOT NULL DEFAULT '',
    dati_json TEXT NOT NULL,
    creato_il TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    aggiornato_il TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_progetti_utente_id ON progetti(utente_id)")
    conn.commit()
    return conn


# --- Utenti ---------------------------------------------------------------

def create_user(conn: sqlite3.Connection, email: str, password_hash: str, nome: str = "") -> dict:
    cur = conn.execute(
        "INSERT INTO utenti (email, password_hash, nome) VALUES (?, ?, ?)",
        (email, password_hash, nome),
    )
    conn.commit()
    return get_user_by_id(conn, cur.lastrowid)


def get_user_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    row = conn.execute("SELECT * FROM utenti WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM utenti WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def utente_pubblico(utente: dict) -> dict:
    """Solo i campi sicuri da restituire al frontend (MAI l'hash della password)."""
    return {"id": utente["id"], "email": utente["email"], "nome": utente["nome"], "piano": utente["piano"]}


# --- Progetti ---------------------------------------------------------------

def list_progetti(conn: sqlite3.Connection, utente_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, nome, committente, ubicazione, totale_testo, creato_il, aggiornato_il "
        "FROM progetti WHERE utente_id = ? ORDER BY aggiornato_il DESC",
        (utente_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_progetto(conn: sqlite3.Connection, progetto_id: int, utente_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM progetti WHERE id = ? AND utente_id = ?", (progetto_id, utente_id)
    ).fetchone()
    return dict(row) if row else None


def create_progetto(conn: sqlite3.Connection, utente_id: int, nome: str, committente: str,
                     ubicazione: str, totale_testo: str, dati_json: str) -> dict:
    cur = conn.execute(
        "INSERT INTO progetti (utente_id, nome, committente, ubicazione, totale_testo, dati_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (utente_id, nome, committente, ubicazione, totale_testo, dati_json),
    )
    conn.commit()
    return get_progetto(conn, cur.lastrowid, utente_id)


def update_progetto(conn: sqlite3.Connection, progetto_id: int, utente_id: int, nome: str,
                     committente: str, ubicazione: str, totale_testo: str, dati_json: str) -> dict | None:
    cur = conn.execute(
        "UPDATE progetti SET nome = ?, committente = ?, ubicazione = ?, totale_testo = ?, "
        "dati_json = ?, aggiornato_il = CURRENT_TIMESTAMP WHERE id = ? AND utente_id = ?",
        (nome, committente, ubicazione, totale_testo, dati_json, progetto_id, utente_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return get_progetto(conn, progetto_id, utente_id)


def delete_progetto(conn: sqlite3.Connection, progetto_id: int, utente_id: int) -> bool:
    cur = conn.execute("DELETE FROM progetti WHERE id = ? AND utente_id = ?", (progetto_id, utente_id))
    conn.commit()
    return cur.rowcount > 0
