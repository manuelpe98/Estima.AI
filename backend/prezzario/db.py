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
    is_catalog INTEGER NOT NULL DEFAULT 0,
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
    if "is_catalog" not in cols:
        conn.execute("ALTER TABLE prezzari ADD COLUMN is_catalog INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voci_prezzario_id ON voci(prezzario_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voci_codice ON voci(codice)")
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
    # Il catalogo completo (is_catalog=1) è escluso di proposito da questo elenco:
    # è pensato solo per la consultazione read-only (vedi search_catalog), mai come
    # prezzario selezionabile per il matching automatico delle voci di computo.
    rows = conn.execute(
        "SELECT * FROM prezzari WHERE is_catalog = 0 ORDER BY data_caricamento DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def catalog_id_if_seeded(conn: sqlite3.Connection, version: str) -> int | None:
    """Ritorna l'id del catalogo già presente in database SE è già alla
    versione richiesta, senza dover ricaricare/passare le 35.000 righe
    sorgente ad ogni singola ricerca (costoso da rifare ad ogni richiesta):
    il chiamante carica le righe da disco solo quando questa funzione
    ritorna None, cioè solo la prima volta o dopo un aggiornamento dei dati."""
    row = conn.execute(
        "SELECT id FROM prezzari WHERE is_catalog = 1 AND seed_version = ? LIMIT 1", (version,)
    ).fetchone()
    return row["id"] if row else None


def ensure_catalog_seed(conn: sqlite3.Connection, meta: dict, rows: list[dict], version: str) -> int:
    """Crea (o aggiorna) il catalogo completo del prezzario ufficiale, tenuto
    come prezzario a parte (is_catalog=1) usato SOLO dalla consultazione in
    sola lettura (search_catalog) — mai incluso in list_prezzari, quindi mai
    selezionabile come prezzario per il matching automatico del computo.
    Stessa logica di versione di ensure_placeholder_seed: senza un controllo,
    su un database già popolato (volume persistente) le righe non
    verrebbero più riallineate se in futuro cambiasse il file sorgente."""
    row = conn.execute(
        "SELECT id, seed_version FROM prezzari WHERE is_catalog = 1 LIMIT 1"
    ).fetchone()
    if row and row["seed_version"] == version:
        return row["id"]

    if row:
        prezzario_id = row["id"]
        conn.execute("DELETE FROM voci WHERE prezzario_id = ?", (prezzario_id,))
        conn.execute(
            "UPDATE prezzari SET regione = ?, anno = ?, nome = ?, seed_version = ? WHERE id = ?",
            (meta["regione"], meta["anno"], meta["nome"], version, prezzario_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO prezzari (regione, anno, nome, is_placeholder, is_catalog, seed_version) "
            "VALUES (?, ?, ?, 0, 1, ?)",
            (meta["regione"], meta["anno"], meta["nome"], version),
        )
        prezzario_id = cur.lastrowid

    conn.executemany(
        "INSERT INTO voci (prezzario_id, categoria, sotto_tipo, codice, descrizione, unita_misura, prezzo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(prezzario_id, r["categoria"], r["sotto_tipo"], r["codice"], r["descrizione"], r["um"], r["prezzo"])
         for r in rows],
    )
    conn.commit()
    return prezzario_id


def search_catalog(conn: sqlite3.Connection, catalog_id: int, query: str = "",
                    volume: str = "", limit: int = 50, offset: int = 0) -> dict:
    """Ricerca in sola lettura nel catalogo completo: per codice e/o testo
    della descrizione, con filtro opzionale per volume (sotto_tipo, es. "Vol.
    1.1"). Restituisce sia i risultati (al massimo `limit`) sia il conteggio
    totale delle corrispondenze, per poter mostrare "Trovate N voci"."""
    clauses = ["prezzario_id = ?"]
    params: list = [catalog_id]
    q = (query or "").strip()
    if q:
        clauses.append("(codice LIKE ? OR descrizione LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])
    if volume:
        clauses.append("sotto_tipo = ?")
        params.append(volume)
    where = " AND ".join(clauses)
    totale = conn.execute(f"SELECT COUNT(*) AS n FROM voci WHERE {where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT codice, descrizione, unita_misura, prezzo, sotto_tipo FROM voci WHERE {where} "
        "ORDER BY codice LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return {"totale": totale, "voci": [dict(r) for r in rows]}


def get_voci(conn: sqlite3.Connection, prezzario_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM voci WHERE prezzario_id = ?", (prezzario_id,)).fetchall()
    return [dict(r) for r in rows]


def get_prezzario_meta(conn: sqlite3.Connection, prezzario_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM prezzari WHERE id = ?", (prezzario_id,)).fetchone()
    return dict(row) if row else None
