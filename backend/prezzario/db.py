"""Database (SQLite) dei prezzari: quello di esempio precaricato più quelli
che l'utente carica progetto per progetto (uno per regione/anno, riutilizzabili)."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .seed_data import PLACEHOLDER_PREZZARIO_META, PLACEHOLDER_VOCI

SCHEMA = """
CREATE TABLE IF NOT EXISTS prezzari (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regione TEXT NOT NULL,
    anno INTEGER NOT NULL,
    nome TEXT NOT NULL,
    is_placeholder INTEGER NOT NULL DEFAULT 0,
    data_caricamento TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voci (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prezzario_id INTEGER NOT NULL REFERENCES prezzari(id),
    categoria TEXT NOT NULL,
    sotto_tipo TEXT NOT NULL,
    codice TEXT NOT NULL,
    descrizione TEXT NOT NULL,
    unita_misura TEXT NOT NULL,
    prezzo REAL NOT NULL
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def ensure_placeholder_seed(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM prezzari WHERE is_placeholder = 1 LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO prezzari (regione, anno, nome, is_placeholder) VALUES (?, ?, ?, 1)",
        (PLACEHOLDER_PREZZARIO_META["regione"], PLACEHOLDER_PREZZARIO_META["anno"],
         PLACEHOLDER_PREZZARIO_META["nome"]),
    )
    prezzario_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO voci (prezzario_id, categoria, sotto_tipo, codice, descrizione, unita_misura, prezzo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(prezzario_id, cat, sotto, cod, desc, um, prezzo)
         for cat, sotto, cod, desc, um, prezzo in PLACEHOLDER_VOCI],
    )
    conn.commit()
    return prezzario_id


def import_prezzario_from_rows(conn: sqlite3.Connection, meta: dict, rows: list[dict]) -> int:
    """Importa un prezzario reale caricato dall'utente (es. CSV con colonne
    categoria, sotto_tipo, codice, descrizione, unita_misura, prezzo) e lo
    salva nel database per essere riutilizzato nei prossimi progetti."""
    cur = conn.execute(
        "INSERT INTO prezzari (regione, anno, nome, is_placeholder) VALUES (?, ?, ?, 0)",
        (meta["regione"], meta["anno"], meta["nome"]),
    )
    prezzario_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO voci (prezzario_id, categoria, sotto_tipo, codice, descrizione, unita_misura, prezzo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(prezzario_id, r["categoria"], r["sotto_tipo"], r["codice"], r["descrizione"],
          r["unita_misura"], float(r["prezzo"])) for r in rows],
    )
    conn.commit()
    return prezzario_id


def list_prezzari(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM prezzari ORDER BY data_caricamento DESC").fetchall()
    return [dict(r) for r in rows]


def get_voci(conn: sqlite3.Connection, prezzario_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM voci WHERE prezzario_id = ?", (prezzario_id,)).fetchall()
    return [dict(r) for r in rows]


def get_prezzario_meta(conn: sqlite3.Connection, prezzario_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM prezzari WHERE id = ?", (prezzario_id,)).fetchone()
    return dict(row) if row else None
