"""Database (SQLite) di account utente e progetti salvati in cloud — separato
dal database dei prezzari (stesso volume persistente, file diverso) per
tenere ben distinti i dati "di sistema" (prezzari, condivisi) da quelli
"di utente" (account, progetti, personali).

Predisposto per un futuro modello a pagamento (deciso con Franco: non ancora
scelto tra abbonamento e crediti a consumo, quindi la struttura dati supporta
entrambi i binari) — SENZA integrare per ora nessun vero pagamento né
applicare alcun blocco reale: 'piano' resta 'beta_gratuita' per tutti finché
non si decide il lancio. I campi 'crediti_residui'/'abbonamento_*' restano
NULL fino ad allora; 'stripe_customer_id' è solo un segnaposto per quando si
integrerà un vero processore di pagamento (Stripe è la scelta più comune per
questo genere di SaaS, ma nulla è ancora collegato).

La tabella 'utilizzi' registra invece FIN DA ORA ogni azione che in futuro
potrebbe avere un costo per l'utente (in crediti) o rientrare in una soglia
di abbonamento — in particolare le chiamate che usano l'AI (tipo che inizia
con 'ai_'), le uniche con un costo reale già oggi (chiave ANTHROPIC_API_KEY
di Franco, condivisa da tutti i visitatori). Serve a due cose già utili
prima ancora di un vero pagamento: mostrare i consumi nel pannello account,
e applicare un limite giornaliero "anti-abuso" (vedi verifica_limite_ai in
backend/main.py) puramente per proteggere Franco da una bolletta AI
imprevista — non è un piano a pagamento, è solo una rete di sicurezza."""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS utenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nome TEXT NOT NULL DEFAULT '',
    -- Piano attuale: 'beta_gratuita' per tutti finché non si lancia un vero
    -- piano a pagamento. Valori futuri previsti: 'abbonamento' (si veda
    -- abbonamento_stato/abbonamento_rinnovo_il) oppure 'crediti' (si veda
    -- crediti_residui) — quale dei due binari verrà lanciato è ancora da
    -- decidere, la struttura dati supporta già entrambi.
    piano TEXT NOT NULL DEFAULT 'beta_gratuita',
    -- Binario "crediti a consumo": saldo residuo, scalato ad ogni azione a
    -- pagamento quando/se questo modello verrà attivato. NULL = non in uso.
    crediti_residui INTEGER,
    -- Binario "abbonamento ricorrente": stato ('attivo'/'scaduto'/'sospeso')
    -- e data del prossimo rinnovo. NULL = non in uso.
    abbonamento_stato TEXT,
    abbonamento_rinnovo_il TEXT,
    -- Segnaposto per il futuro processore di pagamento (es. Stripe): NULL
    -- finché non esiste davvero un cliente/pagamento collegato.
    stripe_customer_id TEXT,
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

-- Registro dei consumi: un utilizzo per riga. 'identificativo' è "utente:<id>"
-- se si è connessi, altrimenti "ip:<indirizzo>" per chi genera da ospite —
-- così il limite anti-abuso e i futuri crediti funzionano anche prima della
-- registrazione. 'tipo' distingue le azioni con un costo AI reale (prefisso
-- 'ai_': ai_analisi_render, ai_interpreta_commento, ai_revisione_computo) da
-- quelle solo computazionali (es. 'generazione_computo'), registrate comunque
-- per avere già ora lo storico completo dei consumi.
CREATE TABLE IF NOT EXISTS utilizzi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente_id INTEGER REFERENCES utenti(id),
    identificativo TEXT NOT NULL,
    tipo TEXT NOT NULL,
    dettaglio TEXT,
    creato_il TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Migrazione per i database già esistenti (creati prima dell'introduzione dei
# campi di piano/crediti/abbonamento): ALTER TABLE non supporta "IF NOT
# EXISTS" per le colonne in SQLite, quindi si tenta e si ignora l'errore se
# la colonna esiste già. Il CREATE TABLE IF NOT EXISTS sopra non tocca una
# tabella già creata in precedenza, quindi su un database esistente (es. su
# Render) sono queste righe, non lo SCHEMA, ad aggiungere le nuove colonne.
_MIGRAZIONI_UTENTI = [
    "ALTER TABLE utenti ADD COLUMN crediti_residui INTEGER",
    "ALTER TABLE utenti ADD COLUMN abbonamento_stato TEXT",
    "ALTER TABLE utenti ADD COLUMN abbonamento_rinnovo_il TEXT",
    "ALTER TABLE utenti ADD COLUMN stripe_customer_id TEXT",
]


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # 'piano' su database preesistenti aveva 'free' come default: lo si
    # allinea al nuovo 'beta_gratuita' solo per le righe che avevano ancora
    # il vecchio valore, senza toccare eventuali piani già impostati a mano.
    conn.execute("UPDATE utenti SET piano = 'beta_gratuita' WHERE piano = 'free'")
    for _stmt in _MIGRAZIONI_UTENTI:
        try:
            conn.execute(_stmt)
        except sqlite3.OperationalError:
            pass  # colonna già presente da un avvio precedente
    conn.execute("CREATE INDEX IF NOT EXISTS idx_progetti_utente_id ON progetti(utente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_utilizzi_identificativo_data ON utilizzi(identificativo, creato_il)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_utilizzi_utente ON utilizzi(utente_id)")
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
    """Solo i campi sicuri da restituire al frontend (MAI l'hash della password).
    Include già i campi di piano/crediti/abbonamento (tutti NULL/beta finché
    non si lancia un piano a pagamento) così il frontend può mostrarli fin da
    ora senza bisogno di un'altra API quando verranno valorizzati davvero."""
    return {
        "id": utente["id"],
        "email": utente["email"],
        "nome": utente["nome"],
        "piano": utente["piano"],
        "crediti_residui": utente["crediti_residui"] if "crediti_residui" in utente.keys() else None,
        "abbonamento_stato": utente["abbonamento_stato"] if "abbonamento_stato" in utente.keys() else None,
        "abbonamento_rinnovo_il": utente["abbonamento_rinnovo_il"] if "abbonamento_rinnovo_il" in utente.keys() else None,
    }


# --- Utilizzi (consumi) ------------------------------------------------------
# Vedi il commento sulla tabella 'utilizzi' più sopra: registrano fin da ora
# ogni azione potenzialmente a pagamento in futuro, e già oggi permettono un
# limite anti-abuso sulle chiamate AI (le uniche con un costo reale) e un
# riepilogo dei consumi nel pannello account.

def registra_utilizzo(conn: sqlite3.Connection, identificativo: str, tipo: str,
                       utente_id: int | None = None, dettaglio: str | None = None) -> None:
    conn.execute(
        "INSERT INTO utilizzi (utente_id, identificativo, tipo, dettaglio) VALUES (?, ?, ?, ?)",
        (utente_id, identificativo, tipo, dettaglio),
    )
    conn.commit()


def conta_utilizzi_oggi(conn: sqlite3.Connection, identificativo: str, prefisso_tipo: str = "") -> int:
    """Quanti utilizzi (di un certo tipo, se specificato un prefisso) risultano
    registrati OGGI per questo identificativo (utente o IP)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM utilizzi WHERE identificativo = ? AND tipo LIKE ? "
        "AND date(creato_il) = date('now')",
        (identificativo, prefisso_tipo + "%"),
    ).fetchone()
    return row["n"] if row else 0


def riepilogo_utilizzo_mensile(conn: sqlite3.Connection, utente_id: int) -> dict:
    """Conteggio dei consumi di questo mese per un utente registrato, da
    mostrare nel pannello account (non ancora legato a un vero addebito)."""
    row = conn.execute(
        "SELECT "
        "  COUNT(*) AS totale, "
        "  SUM(CASE WHEN tipo LIKE 'ai_%' THEN 1 ELSE 0 END) AS ai "
        "FROM utilizzi WHERE utente_id = ? AND strftime('%Y-%m', creato_il) = strftime('%Y-%m', 'now')",
        (utente_id,),
    ).fetchone()
    return {"totale": row["totale"] or 0, "ai": row["ai"] or 0}


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
