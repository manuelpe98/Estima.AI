"""Database (SQLite) di account utente e progetti salvati in cloud — separato
dal database dei prezzari (stesso volume persistente, file diverso) per
tenere ben distinti i dati "di sistema" (prezzari, condivisi) da quelli
"di utente" (account, progetti, personali).

Binario "abbonamento ricorrente" (abbonamento_stato/abbonamento_rinnovo_il):
struttura dati pronta ma NON ancora attivato — resta NULL per tutti finché
non si deciderà di lanciarlo.

Binario "crediti a consumo" (crediti_residui): ATTIVATO. Le funzioni AI
(analisi render, interpreta commento, revisione computo) richiedono un
account con crediti residui sufficienti — chi non vuole comprare crediti
può continuare a usare gratuitamente tutto il resto del sito (estrazione
vani/aperture dai PDF, generazione del computo, esportazioni), che non ha
mai usato l'AI. NESSUN credito gratuito di benvenuto (deciso con Franco:
"paga quello che usa", per non prestarsi ad abusi con account multipli
usa-e-getta) — un nuovo account parte a saldo zero, ESTIMA_CREDITI_BENVENUTO
in backend/main.py resta a 0 di default (impostabile in futuro su Render se
si vorrà una promozione a tempo, senza toccare il codice). I pagamenti
passano da Stripe (pagina di pagamento ospitata da Stripe, mai un numero di
carta sul nostro server): 'stripe_customer_id' resta un riferimento
opzionale, 'pagamenti' registra ogni acquisto completato (per idempotenza:
lo stesso pagamento non può accreditare crediti due volte, anche se Stripe
invia lo stesso avviso più volte, cosa che fa regolarmente per garanzia di
consegna).

La tabella 'utilizzi' registra ogni azione che ha (o potrebbe avere) un
costo per l'utente — in particolare le chiamate che usano l'AI (tipo che
inizia con 'ai_'). Serve a mostrare i consumi nel pannello account e ad
applicare un limite giornaliero "anti-abuso" (vedi _verifica_limite_ai in
backend/main.py), una rete di sicurezza aggiuntiva pensata soprattutto per
chi non ha ancora scalato crediti (fasi di errore/retry) più che come
meccanismo di fatturazione: quello lo fanno i crediti stessi."""
from __future__ import annotations
import os
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
    -- Binario "abbonamento ricorrente", ATTIVATO: quale livello ('base' o
    -- 'premium', vedi PIANI_ABBONAMENTO in backend/main.py) e l'id
    -- dell'abbonamento Stripe corrispondente, usato dal webhook per
    -- ritrovare l'utente su customer.subscription.updated/deleted (che non
    -- portano un utente_id nei metadata come invece fa checkout.session.
    -- completed). NULL finché non si attiva un abbonamento.
    abbonamento_piano TEXT,
    stripe_subscription_id TEXT,
    -- Data/ora (stesso formato di scade_il in reset_password) in cui
    -- l'utente ha accettato Termini e Condizioni e Informativa Privacy in
    -- fase di registrazione: prova dell'accettazione, non solo una spunta
    -- lato interfaccia. NULL per gli account creati prima dell'introduzione
    -- della casella di consenso obbligatoria.
    consenso_termini_il TEXT,
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

-- Un pagamento Stripe completato = una riga. 'stripe_session_id' è UNIQUE:
-- è la chiave di idempotenza che impedisce di accreditare due volte gli
-- stessi crediti se il webhook di Stripe arriva più di una volta per lo
-- stesso pagamento (comportamento normale e documentato di Stripe).
CREATE TABLE IF NOT EXISTS pagamenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente_id INTEGER NOT NULL REFERENCES utenti(id),
    stripe_session_id TEXT NOT NULL UNIQUE,
    crediti_aggiunti INTEGER NOT NULL,
    importo_centesimi INTEGER NOT NULL,
    valuta TEXT NOT NULL DEFAULT 'eur',
    creato_il TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Un link di recupero password = una riga, a uso singolo. 'token_hash' è
-- l'hash SHA-256 del token vero spedito via email (mai il token in chiaro,
-- stessa logica delle password: se qualcuno leggesse il database non deve
-- poter usare direttamente queste righe per reimpostare la password di un
-- altro account). 'scade_il' è confrontato come testo con CURRENT_TIMESTAMP
-- di SQLite: va quindi scritto nello stesso formato ("YYYY-MM-DD HH:MM:SS",
-- UTC, senza "T" né microsecondi — vedi crea_token_reset).
CREATE TABLE IF NOT EXISTS reset_password (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente_id INTEGER NOT NULL REFERENCES utenti(id),
    token_hash TEXT NOT NULL UNIQUE,
    creato_il TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scade_il TEXT NOT NULL,
    usato_il TEXT
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
    "ALTER TABLE utenti ADD COLUMN consenso_termini_il TEXT",
    "ALTER TABLE utenti ADD COLUMN abbonamento_piano TEXT",
    "ALTER TABLE utenti ADD COLUMN stripe_subscription_id TEXT",
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
    # Normalizzazione una tantum per gli account ESISTENTI (registrati prima
    # dell'attivazione dei crediti, quando 'crediti_residui' era sempre NULL):
    # li porta a un saldo esplicito invece di NULL (che scala_crediti tratta
    # comunque come "insufficiente", ma un numero è più chiaro di NULL nel
    # pannello account). Il valore è ESTIMA_CREDITI_BENVENUTO, di default 0
    # (nessun credito gratuito, deciso con Franco) — se in futuro verrà
    # impostato a un valore positivo su Render per una promozione, questo
    # stesso passaggio farà da accredito una tantum anche per gli account già
    # esistenti, non solo per i nuovi. La condizione "IS NULL" rende il
    # passaggio innocuo se ripetuto: dopo la prima esecuzione non tocca più
    # nessuna riga. Stessa variabile d'ambiente di CREDITI_BENVENUTO in
    # backend/main.py, letta qui direttamente per restare valida anche se
    # get_connection viene chiamata prima che main.py legga i propri valori.
    conn.execute(
        "UPDATE utenti SET crediti_residui = ? WHERE crediti_residui IS NULL",
        (int(os.environ.get("ESTIMA_CREDITI_BENVENUTO", "0")),),
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_progetti_utente_id ON progetti(utente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_utilizzi_identificativo_data ON utilizzi(identificativo, creato_il)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_utilizzi_utente ON utilizzi(utente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pagamenti_utente ON pagamenti(utente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reset_password_utente ON reset_password(utente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_utenti_stripe_subscription ON utenti(stripe_subscription_id)")
    conn.commit()
    return conn


# --- Utenti ---------------------------------------------------------------

def create_user(conn: sqlite3.Connection, email: str, password_hash: str, nome: str = "",
                 crediti_iniziali: int = 0, consenso_termini_il: str | None = None) -> dict:
    """crediti_iniziali: crediti di benvenuto assegnati alla creazione
    dell'account (vedi ESTIMA_CREDITI_BENVENUTO in backend/main.py), 0 se
    non se ne vogliono dare. consenso_termini_il: timestamp (stesso formato
    "YYYY-MM-DD HH:MM:SS" usato altrove) in cui l'utente ha accettato Termini
    e Informativa Privacy — valorizzato dal chiamante solo dopo aver
    verificato che il consenso sia stato effettivamente dato in fase di
    registrazione (vedi /api/auth/registrati in backend/main.py)."""
    cur = conn.execute(
        "INSERT INTO utenti (email, password_hash, nome, crediti_residui, consenso_termini_il) VALUES (?, ?, ?, ?, ?)",
        (email, password_hash, nome, crediti_iniziali, consenso_termini_il),
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
        "abbonamento_piano": utente["abbonamento_piano"] if "abbonamento_piano" in utente.keys() else None,
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


def utilizzi_pesati_da(conn: sqlite3.Connection, utente_id: int, pesi: dict, ore: float) -> int:
    """Somma pesata delle azioni AI ('ai_%') registrate da questo utente nelle ultime
    'ore' ore (finestra SCORREVOLE da adesso indietro, non a calendario — coerente con
    come funzionano i limiti orario/settimanale dell'abbonamento in backend/main.py,
    ispirati a quelli di Claude.it). 'pesi': dict tipo->peso (PESO_QUOTA_ABBONAMENTO in
    backend/main.py — indipendente da COSTO_CREDITI, il peso in crediti del binario a
    consumo: i due sistemi non condividono la stessa unità)."""
    righe = conn.execute(
        "SELECT tipo, COUNT(*) AS n FROM utilizzi WHERE utente_id = ? AND tipo LIKE 'ai_%' "
        "AND creato_il >= datetime('now', ? || ' hours') GROUP BY tipo",
        (utente_id, f"-{ore}"),
    ).fetchall()
    return sum(pesi.get(r["tipo"], 1) * r["n"] for r in righe)


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


# --- Crediti e pagamenti -----------------------------------------------------
# Binario "crediti a consumo": un intero per utente, scalato ad ogni chiamata
# AI e accreditato dopo un pagamento Stripe andato a buon fine. Le operazioni
# di scrittura sono scritte come singole UPDATE con condizione nella WHERE
# (non un "leggi il saldo, poi scrivi il nuovo valore" in due passaggi) così
# restano corrette anche con richieste concorrenti sullo stesso account.

def scala_crediti(conn: sqlite3.Connection, utente_id: int, quantita: int) -> bool:
    """Scala 'quantita' crediti se il saldo è sufficiente, in un solo UPDATE
    atomico (evita che due richieste simultanee dello stesso utente possano
    entrambe passare il controllo prima che il saldo sia aggiornato). Ritorna
    True se scalati, False se il saldo non basta (nessuna modifica fatta)."""
    cur = conn.execute(
        "UPDATE utenti SET crediti_residui = crediti_residui - ? "
        "WHERE id = ? AND crediti_residui >= ?",
        (quantita, utente_id, quantita),
    )
    conn.commit()
    return cur.rowcount > 0


def aggiungi_crediti(conn: sqlite3.Connection, utente_id: int, quantita: int) -> None:
    """Accredita 'quantita' crediti (es. dopo un acquisto). COALESCE gestisce
    il caso, ormai raro, di un saldo ancora NULL su un account creato prima
    dell'introduzione del sistema di crediti."""
    conn.execute(
        "UPDATE utenti SET crediti_residui = COALESCE(crediti_residui, 0) + ? WHERE id = ?",
        (quantita, utente_id),
    )
    conn.commit()


def registra_pagamento_se_nuovo(conn: sqlite3.Connection, stripe_session_id: str, utente_id: int,
                                 crediti_aggiunti: int, importo_centesimi: int, valuta: str = "eur") -> bool:
    """Registra un pagamento Stripe e accredita i crediti SOLO se questo
    'stripe_session_id' non era già stato registrato: Stripe può inviare lo
    stesso avviso di pagamento più di una volta (a garanzia di consegna), e
    senza questo controllo lo stesso acquisto accrediterebbe crediti più
    volte. Ritorna True se il pagamento è stato registrato ora (nuovo),
    False se era già presente (avviso duplicato, nessuna modifica fatta)."""
    try:
        conn.execute(
            "INSERT INTO pagamenti (utente_id, stripe_session_id, crediti_aggiunti, importo_centesimi, valuta) "
            "VALUES (?, ?, ?, ?, ?)",
            (utente_id, stripe_session_id, crediti_aggiunti, importo_centesimi, valuta),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # stripe_session_id già presente: avviso duplicato, non riaccreditare.
        # ESSENZIALE annullare qui la transazione lasciata a metà dall'INSERT
        # fallito: senza rollback esplicito la connessione resta con una
        # transazione aperta e tiene bloccato il database (SQLite non la
        # rilascia da sola all'uscita dalla funzione), bloccando le richieste
        # successive — scoperto proprio testando i webhook duplicati che
        # Stripe invia regolarmente per garanzia di consegna.
        conn.rollback()
        return False
    aggiungi_crediti(conn, utente_id, crediti_aggiunti)
    return True


# --- Abbonamento ricorrente ---------------------------------------------------
# Binario "abbonamento ricorrente": a differenza dei crediti (un saldo scalato ad
# ogni chiamata), qui l'autorizzazione si basa su una quota che si ricalcola da
# 'utilizzi' ad ogni richiesta (vedi utilizzi_pesati_da sopra) — non c'è un saldo da
# aggiornare qui. Queste funzioni si occupano solo di tenere allineati piano/stato/
# riferimenti Stripe dell'utente con quello che riporta Stripe via webhook.

def imposta_abbonamento(conn: sqlite3.Connection, utente_id: int, piano: str, stato: str,
                         stripe_customer_id: str | None, stripe_subscription_id: str | None,
                         rinnovo_il: str | None) -> None:
    """Upsert dello stato abbonamento per un utente: usata sia alla prima attivazione
    (checkout.session.completed) sia ad ogni aggiornamento successivo (rinnovo, cambio
    stato, annullamento programmato — customer.subscription.updated). 'piano':
    'base'/'premium' (vedi PIANI_ABBONAMENTO in backend/main.py). 'stato': valore
    leggibile mostrato all'utente ('attivo', 'annullamento_programmato', 'in_ritardo',
    'sospeso', ...), NON necessariamente uguale allo stato interno di Stripe. Il campo
    generale 'piano' dell'utente passa a 'abbonamento' solo se stato == 'attivo' (uno
    stato non attivo non deve far credere alle funzioni AI di avere via libera)."""
    conn.execute(
        "UPDATE utenti SET piano = CASE WHEN ? = 'attivo' THEN 'abbonamento' ELSE piano END, "
        "abbonamento_piano = ?, abbonamento_stato = ?, abbonamento_rinnovo_il = ?, "
        "stripe_customer_id = COALESCE(?, stripe_customer_id), stripe_subscription_id = ? "
        "WHERE id = ?",
        (stato, piano, stato, rinnovo_il, stripe_customer_id, stripe_subscription_id, utente_id),
    )
    conn.commit()


def termina_abbonamento(conn: sqlite3.Connection, stripe_subscription_id: str) -> int | None:
    """customer.subscription.deleted: l'abbonamento è DAVVERO terminato (non solo
    'si annullerà al rinnovo', quello è imposta_abbonamento con stato
    'annullamento_programmato'). Il piano torna a 'beta_gratuita' così le funzioni AI
    richiedono di nuovo crediti; un eventuale saldo crediti residuo non viene toccato.
    Ritorna l'id dell'utente aggiornato, o None se nessun utente aveva questo
    stripe_subscription_id (avviso duplicato o già disaccoppiato)."""
    row = conn.execute(
        "SELECT id FROM utenti WHERE stripe_subscription_id = ?", (stripe_subscription_id,),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE utenti SET piano = 'beta_gratuita', abbonamento_stato = 'terminato', "
        "abbonamento_piano = NULL WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    return row["id"]


def get_user_by_stripe_subscription_id(conn: sqlite3.Connection, stripe_subscription_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM utenti WHERE stripe_subscription_id = ?", (stripe_subscription_id,),
    ).fetchone()
    return dict(row) if row else None


# --- Recupero password -------------------------------------------------------

def crea_token_reset(conn: sqlite3.Connection, utente_id: int, token_hash: str, scade_il: str) -> None:
    """Registra un nuovo token di reset per l'utente. Invalida prima
    qualunque richiesta di reset precedente ancora inutilizzata per lo
    stesso utente: se una persona chiede il reset più volte, resta valido
    solo l'ultimo link ricevuto via email (i precedenti, se cliccati,
    risulteranno scaduti/non validi)."""
    conn.execute("DELETE FROM reset_password WHERE utente_id = ? AND usato_il IS NULL", (utente_id,))
    conn.execute(
        "INSERT INTO reset_password (utente_id, token_hash, scade_il) VALUES (?, ?, ?)",
        (utente_id, token_hash, scade_il),
    )
    conn.commit()


def consuma_token_reset(conn: sqlite3.Connection, token_hash: str) -> int | None:
    """Segna il token come usato SE valido (esiste, non ancora usato, non
    scaduto) in un solo UPDATE atomico — stesso principio di scala_crediti:
    due richieste con lo stesso token non possono entrambe risultare valide
    (es. il link cliccato due volte, o un tentativo di riutilizzo). Ritorna
    l'utente_id a cui appartiene il token se era valido, None altrimenti
    (token inesistente, già usato, o scaduto)."""
    cur = conn.execute(
        "UPDATE reset_password SET usato_il = CURRENT_TIMESTAMP "
        "WHERE token_hash = ? AND usato_il IS NULL AND scade_il > CURRENT_TIMESTAMP",
        (token_hash,),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    row = conn.execute("SELECT utente_id FROM reset_password WHERE token_hash = ?", (token_hash,)).fetchone()
    return row["utente_id"] if row else None


def aggiorna_password(conn: sqlite3.Connection, utente_id: int, nuovo_password_hash: str) -> None:
    conn.execute("UPDATE utenti SET password_hash = ? WHERE id = ?", (nuovo_password_hash, utente_id))
    conn.commit()


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
