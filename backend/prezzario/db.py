"""Database (SQLite) dei prezzari: quello di riferimento precaricato (Regione
Lombardia 2022) più quelli che l'utente carica progetto per progetto (uno per
regione/anno, riutilizzabili)."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .seed_data import PLACEHOLDER_PREZZARIO_META, PLACEHOLDER_VOCI, PLACEHOLDER_SEED_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS prezzari (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regione TEXT NOT NULL,
    anno INTEGER NOT NULL,
    nome TEXT NOT NULL,
    is_placeholder INTEGER NOT NULL DEFAULT 0,
    data_caricamento TEXT DEFAULT CURRENT_TIMESTAMP,
    seed_version TEXT
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
    # Migrazione: 'seed_version' è stata aggiunta dopo la prima versione dello
    # schema. Su un database esistente creato prima di questa colonna,
    # CREATE TABLE IF NOT EXISTS non la aggiunge da sola: va fatto a mano.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(prezzari)").fetchall()}
    if "seed_version" not in cols:
        conn.execute("ALTER TABLE prezzari ADD COLUMN seed_version TEXT")
        conn.commit()
    return conn


def ensure_placeholder_seed(conn: sqlite3.Connection) -> int:
    """Crea (o aggiorna) il prezzario placeholder di esempio.

    Il database dei prezzari è su un volume persistente (sopravvive ai
    redeploy): senza un controllo di versione, una volta creata la prima
    volta, la riga placeholder non verrebbe più toccata — e ogni nuova voce
    aggiunta a PLACEHOLDER_VOCI in una versione successiva del codice
    resterebbe invisibile sull'istanza già in uso. SEED_VERSION (hash del
    contenuto di PLACEHOLDER_VOCI) permette di accorgersi che il catalogo è
    cambiato e riallinearlo, senza toccare eventuali prezzari REALI caricati
    dall'utente (is_placeholder = 0, mai modificati da questa funzione)."""
    row = conn.execute(
        "SELECT id, seed_version FROM prezzari WHERE is_placeholder = 1 LIMIT 1"
    ).fetchone()
    if row and row["seed_version"] == PLACEHOLDER_SEED_VERSION:
        return row["id"]

    if row:
        prezzario_id = row["id"]
        conn.execute("DELETE FROM voci WHERE prezzario_id = ?", (prezzario_id,))
        conn.execute(
            "UPDATE prezzari SET regione = ?, anno = ?, nome = ?, seed_version = ? WHERE id = ?",
            (PLACEHOLDER_PREZZARIO_META["regione"], PLACEHOLDER_PREZZARIO_META["anno"],
             PLACEHOLDER_PREZZARIO_META["nome"], PLACEHOLDER_SEED_VERSION, prezzario_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO prezzari (regione, anno, nome, is_placeholder, seed_version) VALUES (?, ?, ?, 1, ?)",
            (PLACEHOLDER_PREZZARIO_META["regione"], PLACEHOLDER_PREZZARIO_META["anno"],
             PLACEHOLDER_PREZZARIO_META["nome"], PLACEHOLDER_SEED_VERSION),
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
