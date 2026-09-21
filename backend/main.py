"""App web (backend + sito) per il computo metrico automatico: un unico
processo FastAPI serve sia le API sia il frontend statico, così l'intero
prodotto è un solo servizio distribuibile su un host qualunque.

Avvio locale:
    uvicorn backend.main:app --reload --port 8000
    poi apri http://localhost:8000 nel browser (API e sito sono sullo stesso indirizzo)

Avvio con Docker: vedi Dockerfile / docker-compose.yml nella root del progetto.
"""
from __future__ import annotations
import base64
import csv
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import traceback
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import fitz
import stripe
from fastapi import FastAPI, UploadFile, File, Form, Body, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

logger = logging.getLogger("computo")

from .models import ProjectMeta, RoomQuantity, OpeningQuantity, TaggedElement, RoomComparison, ComputoVoce
from .pipeline import (
    validate_only, questions_for_project, extract_quantities, build_from_quantities,
    compute_voci, build_files_from_voci, build_single_file, FORMATI_SINGOLI,
)
from .prezzario import db as prezzario_db
from .prezzario import catalogo_data
from .accounts import db as accounts_db
from .accounts import auth as accounts_auth
from .prezzario.seed_data import REFERENCE_CATEGORIA_SOTTOTIPO, VOCI_SEMPRE_TENTATE
from .intake import required_documents, TIPI_INTERVENTO
from .parametri_engine import PARAMETRI
from .legge10_engine import extract_stratigrafie_reference
from .acustica_engine import extract_acustica_reference
from .relazione_tecnica_engine import extract_relazione_tecnica
from .elevation_engine import extract_elevation_bands
from .ai_assistant import (
    interpreta_istruzione, revisiona_computo, analizza_render, interpreta_preventivo_impresa,
    interpreta_computo_base_excel, AiAssistantError,
)
from .notifiche_email import invia_email
from .confronto_preventivi_engine import (
    leggi_computo_base, costruisci_confronto, RigaImpresa, ImpresaPreventivo, ConfrontoPreventiviError,
)
from .output.confronto_excel_generator import build_confronto_excel
from .output.confronto_pdf_generator import build_confronto_pdf

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
# In produzione punta DATA_DIR a un volume persistente (vedi docker-compose.yml):
# senza persistenza, il database dei prezzari caricati e i job vengono persi a ogni riavvio.
DATA_DIR = Path(os.environ.get("COMPUTO_DATA_DIR", BASE_DIR / "data"))
DB_PATH = str(DATA_DIR / "prezzari" / "prezzari.db")
ACCOUNTS_DB_PATH = str(DATA_DIR / "accounts" / "accounts.db")
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.environ.get("COMPUTO_MAX_UPLOAD_MB", "500")) * 1024 * 1024

app = FastAPI(title="Computo Metrico Automatico")
# CORS resta permissivo (l'unico frontend che deve poter chiamare queste API è
# servito dallo stesso servizio, stessa origine — vedi il mount dei file
# statici più sotto): con allow_credentials non impostato (quindi False, il
# default), il browser non allega comunque il cookie di sessione a nessuna
# richiesta cross-origin, indipendentemente da questa configurazione — quindi
# non serve restringere allow_origins solo per proteggere l'autenticazione.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Sessione utente (cookie firmato, per l'accesso con account — vedi più sotto
# gli endpoint /api/auth/*): SESSION_SECRET va impostata come variabile
# d'ambiente in produzione (stesso schema di BASIC_AUTH_USER/PASS più sotto),
# altrimenti ne viene generata una nuova ad ogni riavvio del server e tutti
# gli utenti risulterebbero disconnessi. Il cookie è httponly (non leggibile
# da JavaScript) e "lax" (non inviato in richieste cross-site), max 30 giorni.
SESSION_SECRET = os.environ.get("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    logger.warning(
        "SESSION_SECRET non impostata: generata una chiave temporanea, valida solo fino al prossimo "
        "riavvio del server (tutti gli utenti connessi verranno disconnessi). Impostala come variabile "
        "d'ambiente in produzione perché le sessioni restino valide tra un riavvio e l'altro."
    )
app.add_middleware(
    SessionMiddleware, secret_key=SESSION_SECRET, session_cookie="estima_session",
    max_age=60 * 60 * 24 * 30, same_site="lax",
)


# --- Gestione errori: qualunque errore mostrato in interfaccia deve SEMPRE
# riportare un motivo comprensibile, mai un messaggio generico senza dettagli
# (richiesto esplicitamente dopo che un errore imprevisto durante l'estrazione
# è comparso senza spiegazione). Tre casi distinti, tutti normalizzati nella
# stessa forma {"error": <testo>, "messages": [<testo>]} che il frontend sa
# già leggere: 1) un'eccezione Python non prevista da nessun endpoint (senza
# questo handler, FastAPI la trasforma in un generico "Internal Server Error"
# senza corpo utile); 2) una richiesta rifiutata prima di entrare nell'endpoint
# perché manca un campo obbligatorio o ha un tipo sbagliato (altrimenti
# FastAPI risponde con una lista di oggetti tecnici, non una frase); 3) una
# HTTPException sollevata esplicitamente nel codice (es. file troppo grande),
# che di default ha solo "detail" e non "error"/"messages". Il testo completo
# dell'eccezione Python arriva anche nell'interfaccia (non solo nei log): è
# uno strumento a un solo utente, non un servizio pubblico, quindi vedere il
# motivo tecnico reale è più utile che nasconderlo. ---
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Errore non gestito su %s %s:\n%s", request.method, request.url.path,
                 "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    testo = f"Errore interno imprevisto ({type(exc).__name__}): {exc}"
    return JSONResponse(status_code=500, content={"error": testo, "messages": [testo]})


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    dettagli = []
    for err in exc.errors():
        campo = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        dettagli.append(f"{campo}: {err.get('msg', 'valore non valido')}" if campo else err.get("msg", "valore non valido"))
    testo = "Richiesta non valida — " + "; ".join(dettagli) if dettagli else "Richiesta non valida."
    return JSONResponse(status_code=422, content={"error": testo, "messages": [testo]})


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    testo = str(exc.detail) if exc.detail else f"Errore HTTP {exc.status_code}."
    return JSONResponse(status_code=exc.status_code, content={"error": testo, "messages": [testo]},
                         headers=getattr(exc, "headers", None))


# Protezione con password (HTTP Basic): non è un vero sistema di account, ma
# senza account utente è il modo più semplice per far sì che un link altrimenti
# pubblico sia utilizzabile solo da chi conosce le credenziali. Si attiva solo
# se BASIC_AUTH_USER/BASIC_AUTH_PASS sono impostate come variabili d'ambiente:
# se assenti, il sito resta aperto (comodo in sviluppo locale).
BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER")
BASIC_AUTH_PASS = os.environ.get("BASIC_AUTH_PASS")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not BASIC_AUTH_USER or request.url.path == "/api/health":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                user, _, pwd = base64.b64decode(auth[6:]).decode().partition(":")
            except Exception:
                user, pwd = "", ""
            if secrets.compare_digest(user, BASIC_AUTH_USER) and secrets.compare_digest(pwd, BASIC_AUTH_PASS):
                return await call_next(request)
        return Response("Accesso non autorizzato.", status_code=401,
                         headers={"WWW-Authenticate": 'Basic realm="Computo Metrico Automatico"'})


if BASIC_AUTH_USER and BASIC_AUTH_PASS:
    app.add_middleware(BasicAuthMiddleware)


# --- Account utente: registrazione/accesso, e backup in cloud dei progetti --
# Sistema volutamente minimale (email+password, nessuna verifica email, nessun
# "password dimenticata" ancora): l'obiettivo di questa prima versione è avere
# un account persistente per non perdere i progetti (finora salvati solo nel
# browser, vedi lo storico locale più sotto in frontend/app.html) e una base
# su cui costruire in futuro piani a pagamento/fatturazione (vedi il campo
# 'piano' in accounts/db.py) — non è ancora un sistema pronto per un pubblico
# ampio senza account già noti/fidati come Franco stesso.
#
# Piani/crediti (deciso con Franco): DUE binari attivi in parallelo per le tre
# funzioni AI (analisi render, interpreta commento, revisione computo), che
# richiedono comunque sempre un account connesso — vedi _autorizza_azione_ai più
# sotto. Il binario "abbonamento ricorrente" (PIANI_ABBONAMENTO) dà accesso
# illimitato alle funzioni AI entro una quota settimanale/oraria che si consuma
# (barra visibile in interfaccia, come i limiti di Claude.it) per un canone fisso
# mensile. Il binario "crediti a consumo" (COSTO_CREDITI) resta disponibile per chi
# preferisce pagare solo quello che usa, senza abbonarsi: un abbonamento attivo ha
# sempre la precedenza sui crediti, che restano comunque a disposizione se
# l'abbonamento viene annullato. Tutto il resto del sito (estrazione
# vani/aperture, generazione/esportazione del computo) resta gratuito e senza
# account, perché non ha mai usato l'AI. NESSUN credito gratuito di benvenuto
# (deciso con Franco: "paga quello che usa", niente da regalare che si presti
# ad abusi con account multipli usa-e-getta) — un nuovo account parte a saldo
# zero e compra i crediti (o attiva un abbonamento) che le servono via Stripe
# (checkout ospitato da
# Stripe, PayPal incluso come metodo di pagamento se abilitato nel pannello
# Stripe — vedi /api/crediti/acquista e /api/stripe/webhook più sotto).
#
# La soglia giornaliera anti-abuso (LIMITE_AI_GIORNALIERO) resta attiva IN
# AGGIUNTA ai crediti: protegge da un account con crediti che, per un bug o un
# uso automatizzato, generasse un numero anomalo di chiamate in un solo
# giorno. È volutamente larga e configurabile via variabile d'ambiente senza
# bisogno di ridistribuire il codice.

LIMITE_AI_GIORNALIERO = int(os.environ.get("ESTIMA_LIMITE_AI_GIORNALIERO", "60"))

# --- Crediti: configurazione (tutta a variabili d'ambiente, modificabile su
# Render senza toccare il codice) --------------------------------------------
# Crediti assegnati gratis ad ogni nuovo account. Default 0 (NESSUN credito
# gratuito, deciso con Franco): si può comunque impostare
# ESTIMA_CREDITI_BENVENUTO su Render a un valore positivo in futuro, per una
# promozione a tempo o simili, senza toccare il codice.
CREDITI_BENVENUTO = int(os.environ.get("ESTIMA_CREDITI_BENVENUTO", "0"))
# Costo in crediti di ciascuna funzione AI. Nota: il costo REALE in API non è
# proporzionale a questi numeri — sia la revisione completa sia l'analisi
# render usano il modello più capace con visione (Sonnet, vedi
# backend/ai_assistant.py), non quello economico (Haiku, usato solo per
# interpreta_istruzione): a 0,19€/credito il margine resta comunque ampio su
# tutte e tre le funzioni, quindi qui non serve ripesarle. Per il binario ad
# abbonamento, dove il margine si gioca su una quota fissa mensile, si usa
# invece un peso separato pensato sul costo reale: vedi PESO_QUOTA_ABBONAMENTO
# più sotto.
COSTO_CREDITI = {
    "ai_analisi_render": int(os.environ.get("ESTIMA_COSTO_ANALISI_RENDER", "1")),
    "ai_interpreta_commento": int(os.environ.get("ESTIMA_COSTO_INTERPRETA_COMMENTO", "1")),
    "ai_revisione_computo": int(os.environ.get("ESTIMA_COSTO_REVISIONE_COMPUTO", "3")),
    # Interpretazione di UN preventivo impresa (confronto prezzi): legge l'intero computo di
    # riferimento più il documento libero dell'impresa, con lo stesso modello capace usato per
    # la revisione — costo allineato a quello, non a un'azione riga-per-riga.
    "ai_interpreta_preventivo": int(os.environ.get("ESTIMA_COSTO_INTERPRETA_PREVENTIVO", "3")),
    # Fallback SOLO quando il computo base caricato per il confronto preventivi non ha una
    # struttura di colonne riconoscibile meccanicamente (vedi confronto_preventivi_engine.py):
    # più leggero della revisione/interpretazione preventivo, perché legge un solo file già
    # tabellare (Excel), non deve incrociarlo con nient'altro.
    "ai_interpreta_computo_base": int(os.environ.get("ESTIMA_COSTO_INTERPRETA_COMPUTO_BASE", "2")),
}
# Unico pacchetto di crediti in vendita per ora (si può estendere a più
# pacchetti in futuro): quantità e prezzo si cambiano da qui/da variabile
# d'ambiente, senza toccare il resto del codice del checkout.
CREDITI_PACCHETTO = int(os.environ.get("ESTIMA_CREDITI_PACCHETTO", "100"))
PREZZO_PACCHETTO_CENTESIMI = int(os.environ.get("ESTIMA_PREZZO_PACCHETTO_CENT", "1900"))  # 19,00 EUR
VALUTA_PAGAMENTI = os.environ.get("ESTIMA_VALUTA_PAGAMENTI", "eur")

# Binario "abbonamento ricorrente" (deciso con Franco: due livelli, quota di azioni
# AI che si consuma con una barra visibile, come i limiti di Claude.it, invece di un
# saldo crediti). 'quota_settimanale'/'quota_oraria' sono espresse in "unità pesate"
# (vedi PESO_QUOTA_ABBONAMENTO subito sotto), su finestre SCORREVOLI (ultime N ore da
# adesso, non calendario) — vedi utilizzi_pesati_da in backend/accounts/db.py.
#
# Come sono stati scelti questi numeri (punto di partenza da ricalibrare quando si
# avranno consumi reali, non una misura esatta): margine obiettivo del 70% sul prezzo
# dell'abbonamento -> il 30% resta come budget mensile per l'API (5,97€ su Base,
# 11,97€ su Premium), diviso su ~4,345 settimane/mese. Il peso di ciascuna azione è
# pensato per valere all'incirca 0,01€ di costo reale in API secondo i prezzi
# Anthropic attuali (Haiku 4.5: 1$/5$ per milione di token; Sonnet 5: 2$/10$),
# calcolato leggendo le dimensioni reali dei prompt in backend/ai_assistant.py:
# interpreta_istruzione (Haiku, poche centinaia di token) costa un'unità; analisi
# render (Sonnet+visione, fino a 6-7 immagini) e revisione computo (Sonnet, cresce con
# il numero di righe) costano di più e sono quindi pesate sul caso da moderato a
# impegnativo, non sul caso più leggero — un abbonato che facesse SOLO revisioni su
# computi molto grandi resta comunque il caso limite da tenere d'occhio nei consumi
# reali, più che il singolo prezzo.
PIANI_ABBONAMENTO = {
    "base": {
        "nome": "Base",
        "prezzo_centesimi": int(os.environ.get("ESTIMA_ABBONAMENTO_BASE_PREZZO_CENT", "1990")),  # 19,90 EUR
        "quota_settimanale": int(os.environ.get("ESTIMA_ABBONAMENTO_BASE_QUOTA_SETTIMANALE", "130")),
        "quota_oraria": int(os.environ.get("ESTIMA_ABBONAMENTO_BASE_QUOTA_ORARIA", "20")),
    },
    "premium": {
        "nome": "Premium",
        "prezzo_centesimi": int(os.environ.get("ESTIMA_ABBONAMENTO_PREMIUM_PREZZO_CENT", "3990")),  # 39,90 EUR
        "quota_settimanale": int(os.environ.get("ESTIMA_ABBONAMENTO_PREMIUM_QUOTA_SETTIMANALE", "260")),
        "quota_oraria": int(os.environ.get("ESTIMA_ABBONAMENTO_PREMIUM_QUOTA_ORARIA", "40")),
    },
}
# Peso di ciascuna azione AI ai fini della quota abbonamento — vedi la spiegazione
# sopra. INDIPENDENTE da COSTO_CREDITI (il costo in crediti del binario a consumo):
# stesse funzioni, due unità di misura diverse per due modelli di prezzo diversi.
PESO_QUOTA_ABBONAMENTO = {
    "ai_interpreta_commento": int(os.environ.get("ESTIMA_PESO_ABBONAMENTO_INTERPRETA", "1")),
    "ai_analisi_render": int(os.environ.get("ESTIMA_PESO_ABBONAMENTO_RENDER", "3")),
    "ai_revisione_computo": int(os.environ.get("ESTIMA_PESO_ABBONAMENTO_REVISIONE", "8")),
    "ai_interpreta_preventivo": int(os.environ.get("ESTIMA_PESO_ABBONAMENTO_PREVENTIVO", "8")),
    "ai_interpreta_computo_base": int(os.environ.get("ESTIMA_PESO_ABBONAMENTO_COMPUTO_BASE", "5")),
}

# --- Periodo di prova gratuita ----------------------------------------------
# Fase temporanea PRIMA che crediti/abbonamenti diventino acquistabili per davvero
# (serve prima mettere a posto la Partita IVA — vedi la discussione avuta sul
# tema: un servizio a pagamento organizzato è "attività abituale" fin dal primo
# incasso, indipendentemente da margine o fatturato, quindi finché quella parte
# non è a posto non si può incassare nulla, nemmeno "a copertura costi"). In
# questa fase ogni utente connesso ha accesso gratuito alle funzioni AI fino a
# un tetto di spesa REALE (non di ricavo) a finestra mobile settimanale, per
# limitare l'esposizione economica di chi paga le chiamate API durante il test.
#
# ESTIMA_MODALITA_PROVA=false disattiva questa modalità e fa tornare tutto al
# binario normale crediti/abbonamento (comportamento pre-esistente, invariato):
# quando succede, il codice sotto semplicemente non viene più interpellato.
#
# Il tetto è espresso in euro (ESTIMA_PROVA_TETTO_SETTIMANALE_EUR) e convertito
# in "unità pesate" tramite una stima del costo reale per unità
# (ESTIMA_COSTO_REALE_UNITA_EUR): stessi pesi relativi di PESO_QUOTA_ABBONAMENTO
# (l'analisi render costa ~3 volte un'interpretazione commento, la revisione
# computo ~8 volte), ma tenuti come costante SEPARATA apposta — ricalibrare la
# quota degli abbonamenti a pagamento in futuro non deve spostare per sbaglio
# anche il tetto di questa fase di prova, e viceversa.
MODALITA_PROVA = os.environ.get("ESTIMA_MODALITA_PROVA", "true").strip().lower() in ("1", "true", "si", "sì", "yes")
PESO_COSTO_REALE_PROVA = {
    "ai_interpreta_commento": int(os.environ.get("ESTIMA_PESO_PROVA_INTERPRETA", "1")),
    "ai_analisi_render": int(os.environ.get("ESTIMA_PESO_PROVA_RENDER", "3")),
    "ai_revisione_computo": int(os.environ.get("ESTIMA_PESO_PROVA_REVISIONE", "8")),
    "ai_interpreta_preventivo": int(os.environ.get("ESTIMA_PESO_PROVA_PREVENTIVO", "8")),
    "ai_interpreta_computo_base": int(os.environ.get("ESTIMA_PESO_PROVA_COMPUTO_BASE", "5")),
}
PROVA_TETTO_SETTIMANALE_EUR = float(os.environ.get("ESTIMA_PROVA_TETTO_SETTIMANALE_EUR", "5.0"))
PROVA_COSTO_REALE_UNITA_EUR = float(os.environ.get("ESTIMA_COSTO_REALE_UNITA_EUR", "0.01"))
PROVA_TETTO_SETTIMANALE_UNITA = max(1, round(PROVA_TETTO_SETTIMANALE_EUR / PROVA_COSTO_REALE_UNITA_EUR))

# Chiavi Stripe: STRIPE_SECRET_KEY per creare le sessioni di pagamento,
# STRIPE_WEBHOOK_SECRET per verificare che gli avvisi di pagamento ricevuti su
# /api/stripe/webhook arrivino davvero da Stripe (e non da chiunque altro
# provi a chiamare quell'indirizzo per accreditarsi crediti gratis). Finché
# STRIPE_SECRET_KEY non è impostata, l'acquisto crediti risponde con un
# errore chiaro invece di un errore tecnico poco comprensibile.
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
# URL pubblico del sito, usato per costruire gli indirizzi di ritorno dopo il
# pagamento (successo/annullo) e i link nelle email di recupero password: su
# Render va impostata alla URL vera del servizio (es.
# https://estima-ai.onrender.com). In locale, se assente, si ripiega su un
# valore di sviluppo.
BASE_URL_PUBBLICO = os.environ.get("ESTIMA_BASE_URL", "http://localhost:8000").rstrip("/")

# --- Recupero password: configurazione --------------------------------------
# Il link di reset scade dopo questi minuti (vedi accounts_db.crea_token_reset
# / consuma_token_reset). Il limite giornaliero è per IP, non per email: una
# persona che sbaglia più volte la propria email non deve restare bloccata,
# ma non si deve nemmeno poter usare questo endpoint per intasare di email la
# casella di qualcun altro.
RESET_PASSWORD_SCADENZA_MINUTI = int(os.environ.get("ESTIMA_RESET_PASSWORD_SCADENZA_MINUTI", "60"))
LIMITE_RESET_PASSWORD_GIORNALIERO = int(os.environ.get("ESTIMA_LIMITE_RESET_PASSWORD_GIORNALIERO", "5"))


def _identificativo_richiesta(request: Request, utente: dict | None) -> str:
    """Chiave usata per contare gli utilizzi/applicare il limite anti-abuso:
    l'id utente se connesso, altrimenti l'IP del chiamante — così la soglia
    protegge Franco anche da chi genera come ospite, senza account."""
    if utente:
        return f"utente:{utente['id']}"
    ip = request.client.host if request.client else "sconosciuto"
    return f"ip:{ip}"


def _verifica_limite_ai(conn, identificativo: str) -> None:
    """Solleva 429 se questo identificativo ha già superato oggi la soglia di
    chiamate AI consentite in questa fase beta gratuita. Non riguarda le
    azioni puramente computazionali (generazione/download dei file), che
    restano senza limiti per scelta esplicita finché il modello di prezzo non
    è deciso."""
    n = accounts_db.conta_utilizzi_oggi(conn, identificativo, prefisso_tipo="ai_")
    if n >= LIMITE_AI_GIORNALIERO:
        raise HTTPException(
            429,
            "Hai raggiunto il limite giornaliero di richieste AI previsto in questa fase di test "
            "gratuita. Riprova domani, oppure scrivici se ti serve una soglia più alta.",
        )


def _verifica_quota_abbonamento(conn, utente: dict, tipo: str) -> None:
    """Solleva 429 se l'abbonato ha esaurito la quota oraria o settimanale del proprio
    piano (finestre SCORREVOLI, non a calendario — vedi PIANI_ABBONAMENTO più sopra per
    come sono stati scelti questi numeri). Controlla prima la soglia oraria (più
    stringente in caso di uso concentrato) e poi quella settimanale, così il messaggio
    mostrato è sempre quello del limite effettivamente toccato per primo."""
    piano = PIANI_ABBONAMENTO.get(utente.get("abbonamento_piano") or "")
    if not piano:
        # abbonamento_stato è 'attivo' ma abbonamento_piano è mancante o non
        # riconosciuto: dato incoerente (non dovrebbe succedere: imposta_abbonamento
        # scrive sempre insieme piano e stato) — meglio un errore chiaro che un
        # comportamento indefinito.
        raise HTTPException(500, "Configurazione dell'abbonamento non valida: contattaci per assistenza.")
    peso = PESO_QUOTA_ABBONAMENTO.get(tipo, 1)
    usati_ora = accounts_db.utilizzi_pesati_da(conn, utente["id"], PESO_QUOTA_ABBONAMENTO, ore=1)
    if usati_ora + peso > piano["quota_oraria"]:
        raise HTTPException(
            429,
            f"Hai raggiunto il limite orario del tuo abbonamento {piano['nome']} "
            f"({piano['quota_oraria']} azioni AI/ora). Riprova tra qualche minuto.",
        )
    usati_settimana = accounts_db.utilizzi_pesati_da(conn, utente["id"], PESO_QUOTA_ABBONAMENTO, ore=24 * 7)
    if usati_settimana + peso > piano["quota_settimanale"]:
        suggerimento = (
            " Passa a Premium dal tuo profilo per una quota più ampia, oppure riprova la prossima "
            "settimana." if utente.get("abbonamento_piano") == "base" else " Riprova la prossima settimana."
        )
        raise HTTPException(
            429,
            f"Hai raggiunto il limite settimanale del tuo abbonamento {piano['nome']} "
            f"({piano['quota_settimanale']} azioni AI/settimana).{suggerimento}",
        )


def _verifica_tetto_prova(conn, utente: dict, tipo: str) -> None:
    """Solleva 429 se l'utente ha esaurito il tetto di spesa reale settimanale (finestra
    SCORREVOLE, non a calendario) previsto per il periodo di prova gratuita — vedi
    PROVA_TETTO_SETTIMANALE_EUR più sopra per come è calcolato. Il messaggio non nomina MAI
    la cifra in euro (la barra mostrata in interfaccia usa solo una percentuale): il tetto è
    una tutela economica interna, non una cosa su cui l'utente deve ragionare in euro."""
    peso = PESO_COSTO_REALE_PROVA.get(tipo, 1)
    usati = accounts_db.utilizzi_pesati_da(conn, utente["id"], PESO_COSTO_REALE_PROVA, ore=24 * 7)
    if usati + peso > PROVA_TETTO_SETTIMANALE_UNITA:
        raise HTTPException(
            429,
            "Hai raggiunto il limite di utilizzo previsto per questo periodo di prova gratuita. "
            "Riprova la prossima settimana: a breve arriveranno gli abbonamenti a pagamento con "
            "quote più ampie.",
        )


def _autorizza_azione_ai(conn, utente: dict | None, tipo: str) -> str:
    """Verifica che l'utente possa eseguire l'azione AI 'tipo' e, se il binario è
    quello a consumo, scala SUBITO i crediti necessari, prima di chiamare l'AI — non
    dopo: scala_crediti è un unico UPDATE atomico, quindi due richieste della stessa
    funzione partite quasi insieme non possono entrambe superare il controllo e
    portare il saldo sotto zero.

    Ritorna 'prova', 'abbonamento' o 'crediti' a seconda di quale binario ha autorizzato
    la chiamata: il chiamante userà questo valore per sapere se, in caso di fallimento
    della chiamata AI, deve restituire crediti (binario a consumo — vedi i blocchi
    'except AiAssistantError' più sotto) oppure non deve fare nulla (binario prova o
    abbonamento: la quota/il tetto si ricalcolano dalle righe in 'utilizzi', scritte SOLO
    dopo il successo della chiamata — vedi registra_utilizzo in ciascun endpoint — quindi
    una chiamata fallita non consuma mai quota da sola, senza bisogno di un rimborso
    esplicito).

    Finché MODALITA_PROVA è attiva, è l'UNICO binario controllato — crediti e abbonamento
    restano congelati e non vengono nemmeno consultati, esattamente come i crediti restano
    congelati quando è attivo un abbonamento — così quando la prova finisce si riparte da
    dove ci si era fermati. Un abbonamento attivo ha comunque la precedenza sui crediti:
    chi è abbonato non consuma il proprio saldo crediti (che resta a disposizione se un
    domani l'abbonamento viene annullato)."""
    if not utente:
        raise HTTPException(
            401,
            "Devi avere un account connesso per usare le funzioni AI (il resto del sito resta "
            "gratuito senza account).",
        )
    if MODALITA_PROVA:
        _verifica_tetto_prova(conn, utente, tipo)
        return "prova"
    if utente.get("abbonamento_stato") == "attivo":
        _verifica_quota_abbonamento(conn, utente, tipo)
        return "abbonamento"
    costo = COSTO_CREDITI.get(tipo, 1)
    if not accounts_db.scala_crediti(conn, utente["id"], costo):
        saldo = utente.get("crediti_residui") or 0
        raise HTTPException(
            402,
            f"Crediti insufficienti per questa funzione AI (ne servono {costo}, saldo attuale {saldo}). "
            "Puoi acquistarne altri, o attivare un abbonamento, dal tuo account.",
        )
    return "crediti"


def _utente_sessione(request: Request) -> dict | None:
    """Utente attualmente connesso (dalla sessione), o None se nessuno ha
    fatto accesso. Non solleva mai eccezioni: usata dagli endpoint che
    funzionano sia con che senza account (es. GET /api/auth/utente)."""
    uid = request.session.get("uid")
    if not uid:
        return None
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    return accounts_db.get_user_by_id(conn, uid)


def richiedi_utente(request: Request) -> dict:
    """Come _utente_sessione, ma per gli endpoint che richiedono
    OBBLIGATORIAMENTE un account connesso (i progetti in cloud): solleva 401
    se nessuno ha fatto accesso, con un messaggio comprensibile a schermo."""
    utente = _utente_sessione(request)
    if not utente:
        raise HTTPException(401, "Devi accedere al tuo account per usare questa funzione.")
    return utente


@app.post("/api/auth/registrati")
async def api_auth_registrati(request: Request, payload: dict = Body(...)):
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    nome = str(payload.get("nome", "")).strip()
    consenso = bool(payload.get("consenso"))

    if not accounts_auth.is_valid_email(email):
        raise HTTPException(400, "Indirizzo email non valido.")
    errore_pwd = accounts_auth.password_valida(password)
    if errore_pwd:
        raise HTTPException(400, errore_pwd)
    if not consenso:
        raise HTTPException(400, "Devi accettare Termini e Condizioni e Informativa Privacy per creare un account.")

    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    if accounts_db.get_user_by_email(conn, email):
        raise HTTPException(400, "Esiste già un account con questa email: prova ad accedere invece di registrarti.")

    consenso_termini_il = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    utente = accounts_db.create_user(
        conn, email, accounts_auth.hash_password(password), nome, crediti_iniziali=CREDITI_BENVENUTO,
        consenso_termini_il=consenso_termini_il,
    )
    request.session["uid"] = utente["id"]
    return {"utente": accounts_db.utente_pubblico(utente)}


@app.post("/api/auth/accedi")
async def api_auth_accedi(request: Request, payload: dict = Body(...)):
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    utente = accounts_db.get_user_by_email(conn, email)
    # Stesso messaggio sia per email inesistente sia per password sbagliata:
    # non si deve poter scoprire se un'email è registrata o no provando ad
    # accedere (pratica di sicurezza standard).
    if not utente or not accounts_auth.verify_password(password, utente["password_hash"]):
        raise HTTPException(401, "Email o password non corrette.")

    request.session["uid"] = utente["id"]
    return {"utente": accounts_db.utente_pubblico(utente)}


@app.post("/api/auth/richiedi-reset")
async def api_auth_richiedi_reset(request: Request, payload: dict = Body(...)):
    """Primo passo del recupero password: se l'email corrisponde a un
    account, invia un'email con un link contenente un token a tempo (vedi
    RESET_PASSWORD_SCADENZA_MINUTI) per impostare una nuova password.

    Risponde SEMPRE con lo stesso messaggio generico, esista o meno
    quell'email tra gli account registrati — altrimenti questo endpoint
    diventerebbe un modo per scoprire quali email hanno un account (stessa
    ragione per cui /api/auth/accedi non distingue email inesistente da
    password sbagliata). Soggetto a un piccolo limite anti-abuso per IP
    (LIMITE_RESET_PASSWORD_GIORNALIERO), per non permettere di intasare la
    casella di qualcuno con email di reset ripetute."""
    email = str(payload.get("email", "")).strip().lower()
    messaggio = ("Se l'indirizzo è associato a un account, riceverai a breve un'email con le istruzioni "
                 "per reimpostare la password.")
    if not accounts_auth.is_valid_email(email):
        return {"ok": True, "messaggio": messaggio}

    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    ip = request.client.host if request.client else "sconosciuto"
    identificativo = f"ip:{ip}"
    if accounts_db.conta_utilizzi_oggi(conn, identificativo, prefisso_tipo="reset_password_richiesta") \
            >= LIMITE_RESET_PASSWORD_GIORNALIERO:
        # Anche qui risposta generica: non si conferma né si nega nulla
        # neppure quando il limite anti-abuso è stato raggiunto.
        return {"ok": True, "messaggio": messaggio}
    accounts_db.registra_utilizzo(conn, identificativo, "reset_password_richiesta")

    utente = accounts_db.get_user_by_email(conn, email)
    if utente:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        # Stesso formato di CURRENT_TIMESTAMP in SQLite ("YYYY-MM-DD HH:MM:SS",
        # UTC): il confronto in consuma_token_reset è testuale, non una vera
        # data, quindi i due formati devono coincidere byte per byte o il
        # confronto "scade_il > CURRENT_TIMESTAMP" darebbe risultati sbagliati.
        scade_il = (datetime.utcnow() + timedelta(minutes=RESET_PASSWORD_SCADENZA_MINUTI)).strftime("%Y-%m-%d %H:%M:%S")
        accounts_db.crea_token_reset(conn, utente["id"], token_hash, scade_il)
        link = f"{BASE_URL_PUBBLICO}/app.html?reset={token}"
        invia_email(
            utente["email"],
            "Reimposta la password del tuo account Estima.AI",
            corpo_html=(
                f"<p>Hai richiesto di reimpostare la password del tuo account Estima.AI.</p>"
                f'<p><a href="{link}">Clicca qui per scegliere una nuova password</a> '
                f"(il link è valido {RESET_PASSWORD_SCADENZA_MINUTI} minuti).</p>"
                f"<p>Se non sei stato tu a richiederlo, ignora pure questa email: la password "
                f"del tuo account resterà invariata.</p>"
            ),
            corpo_testo=(
                f"Reimposta la password del tuo account Estima.AI: {link} "
                f"(link valido {RESET_PASSWORD_SCADENZA_MINUTI} minuti). "
                f"Se non sei stato tu a richiederlo, ignora questa email."
            ),
        )
    return {"ok": True, "messaggio": messaggio}


@app.post("/api/auth/reset-password")
async def api_auth_reset_password(request: Request, payload: dict = Body(...)):
    """Secondo passo del recupero password: consuma il token ricevuto via
    email (vedi accounts_db.consuma_token_reset — uso singolo, scade dopo
    RESET_PASSWORD_SCADENZA_MINUTI minuti) e imposta la nuova password.
    In caso di successo effettua anche l'accesso automatico (comodità: chi
    ha appena dimostrato di controllare la propria email/account non deve
    doversi riloggare subito dopo)."""
    token = str(payload.get("token", ""))
    nuova_password = str(payload.get("password", ""))
    if not token:
        raise HTTPException(400, "Link di reset mancante o non valido.")
    errore_pwd = accounts_auth.password_valida(nuova_password)
    if errore_pwd:
        raise HTTPException(400, errore_pwd)

    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    utente_id = accounts_db.consuma_token_reset(conn, token_hash)
    if not utente_id:
        raise HTTPException(
            400, "Questo link è scaduto o non è più valido: richiedi un nuovo reset della password.",
        )

    accounts_db.aggiorna_password(conn, utente_id, accounts_auth.hash_password(nuova_password))
    request.session["uid"] = utente_id
    utente = accounts_db.get_user_by_id(conn, utente_id)
    return {"utente": accounts_db.utente_pubblico(utente)}


@app.post("/api/auth/esci")
async def api_auth_esci(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/utente")
async def api_auth_utente(request: Request):
    utente = _utente_sessione(request)
    return {"utente": accounts_db.utente_pubblico(utente) if utente else None}


@app.get("/api/account/utilizzo")
async def api_account_utilizzo(utente: dict = Depends(richiedi_utente)):
    """Riepilogo dei consumi di questo mese per l'account connesso (numero di
    computi generati/azioni AI) più i dati utili al frontend per mostrare il
    saldo crediti, il catalogo piani abbonamento, il consumo di quota
    settimanale/oraria se abbonato, quanto costa ciascuna funzione AI e i
    dettagli del pacchetto crediti acquistabile — così il pannello account e i
    messaggi di "crediti insufficienti"/"quota esaurita" restano sincronizzati
    con la configurazione del server senza valori duplicati lato frontend."""
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    riepilogo = accounts_db.riepilogo_utilizzo_mensile(conn, utente["id"])
    prova = None
    if MODALITA_PROVA:
        prova = {
            "usati": accounts_db.utilizzi_pesati_da(conn, utente["id"], PESO_COSTO_REALE_PROVA, ore=24 * 7),
            "limite": PROVA_TETTO_SETTIMANALE_UNITA,
        }
    quota_abbonamento = None
    if utente.get("abbonamento_stato") == "attivo":
        piano = PIANI_ABBONAMENTO.get(utente.get("abbonamento_piano") or "")
        if piano:
            quota_abbonamento = {
                "piano": utente.get("abbonamento_piano"),
                "nome_piano": piano["nome"],
                "settimana": {
                    "usati": accounts_db.utilizzi_pesati_da(conn, utente["id"], PESO_QUOTA_ABBONAMENTO, ore=24 * 7),
                    "limite": piano["quota_settimanale"],
                },
                "ora": {
                    "usati": accounts_db.utilizzi_pesati_da(conn, utente["id"], PESO_QUOTA_ABBONAMENTO, ore=1),
                    "limite": piano["quota_oraria"],
                },
            }
    return {
        "utilizzo_mese_corrente": riepilogo,
        "limite_ai_giornaliero": LIMITE_AI_GIORNALIERO,
        "costo_crediti": COSTO_CREDITI,
        "pacchetto_crediti": {
            "crediti": CREDITI_PACCHETTO,
            "prezzo_centesimi": PREZZO_PACCHETTO_CENTESIMI,
            "valuta": VALUTA_PAGAMENTI,
        },
        "acquisto_crediti_disponibile": bool(STRIPE_SECRET_KEY) and not MODALITA_PROVA,
        "piani_abbonamento": PIANI_ABBONAMENTO,
        "quota_abbonamento": quota_abbonamento,
        "abbonamento_disponibile": bool(STRIPE_SECRET_KEY) and not MODALITA_PROVA,
        "modalita_prova": MODALITA_PROVA,
        "prova": prova,
    }


@app.post("/api/crediti/acquista")
async def api_crediti_acquista(request: Request, utente: dict = Depends(richiedi_utente)):
    """Crea una sessione di pagamento Stripe per il pacchetto di crediti
    configurato (CREDITI_PACCHETTO/PREZZO_PACCHETTO_CENTESIMI) e restituisce
    l'indirizzo della pagina di pagamento OSPITATA DA STRIPE a cui il
    frontend deve reindirizzare l'utente: nessun dato di pagamento (numero di
    carta, PayPal, ecc.) passa mai dal nostro server. I crediti vengono
    accreditati solo dopo che Stripe conferma il pagamento tramite il webhook
    (vedi /api/stripe/webhook), MAI a questo punto — questo endpoint apre
    solo la pagina di pagamento, non conferma nulla."""
    if MODALITA_PROVA:
        # Durante il periodo di prova gratuita non si può incassare nulla (vedi il
        # commento su MODALITA_PROVA più sopra): questo endpoint resta bloccato finché
        # la fase di test non finisce, anche se STRIPE_SECRET_KEY fosse configurata.
        raise HTTPException(
            403,
            "Gli acquisti sono sospesi durante questo periodo di prova gratuita: stai già usando Estima.AI "
            "senza costi. Gli abbonamenti a pagamento arriveranno a breve.",
        )
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            503,
            "L'acquisto di crediti non è ancora configurato su questo server (manca la chiave Stripe). "
            "Riprova più tardi.",
        )
    try:
        sessione = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": VALUTA_PAGAMENTI,
                    "product_data": {
                        "name": f"{CREDITI_PACCHETTO} crediti Estima.AI",
                        "description": "Crediti per le funzioni AI di Estima.AI (analisi render, "
                                        "interpretazione commenti, revisione computo).",
                    },
                    "unit_amount": PREZZO_PACCHETTO_CENTESIMI,
                },
                "quantity": 1,
            }],
            client_reference_id=str(utente["id"]),
            metadata={"utente_id": str(utente["id"]), "crediti": str(CREDITI_PACCHETTO)},
            customer_email=utente["email"],
            success_url=f"{BASE_URL_PUBBLICO}/app.html?acquisto=ok",
            cancel_url=f"{BASE_URL_PUBBLICO}/app.html?acquisto=annullato",
        )
    except stripe.error.StripeError as exc:
        logger.error("Errore nella creazione della sessione Stripe: %s", exc)
        raise HTTPException(502, "Non è stato possibile aprire la pagina di pagamento. Riprova più tardi.")
    return {"checkout_url": sessione.url}


@app.post("/api/abbonamento/attiva")
async def api_abbonamento_attiva(payload: dict = Body(...), utente: dict = Depends(richiedi_utente)):
    """Crea una sessione di pagamento Stripe in modalità 'subscription' (ricorrente,
    mensile) per il piano scelto ('base' o 'premium', vedi PIANI_ABBONAMENTO) e
    restituisce l'indirizzo della pagina di pagamento OSPITATA DA STRIPE, come per
    /api/crediti/acquista. Il prezzo è passato come price_data con 'recurring' inline
    (stesso approccio già usato per i crediti): non serve creare in anticipo un Price
    su Stripe, quantità/prezzo restano configurabili da qui/da variabile d'ambiente.
    L'abbonamento viene attivato lato server SOLO dopo la conferma via webhook (vedi
    /api/stripe/webhook), MAI a questo punto."""
    if MODALITA_PROVA:
        raise HTTPException(
            403,
            "Gli abbonamenti non sono ancora attivabili durante questo periodo di prova gratuita: stai già "
            "usando Estima.AI senza costi. Arriveranno a breve.",
        )
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            503,
            "Gli abbonamenti non sono ancora configurati su questo server (manca la chiave Stripe). "
            "Riprova più tardi.",
        )
    piano_id = str(payload.get("piano", "")).strip().lower()
    piano = PIANI_ABBONAMENTO.get(piano_id)
    if not piano:
        raise HTTPException(400, "Piano non valido: scegli 'base' o 'premium'.")
    if utente.get("abbonamento_stato") == "attivo":
        raise HTTPException(
            400,
            "Hai già un abbonamento attivo: annullalo dal tuo account prima di attivarne uno nuovo "
            "(resta valido fino al rinnovo, poi puoi sceglierne un altro).",
        )
    try:
        sessione = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency": VALUTA_PAGAMENTI,
                    "product_data": {
                        "name": f"Estima.AI — Abbonamento {piano['nome']}",
                        "description": f"Funzioni AI di Estima.AI (analisi render, interpretazione commenti, "
                                        f"revisione computo) fino a {piano['quota_settimanale']} azioni/settimana "
                                        f"({piano['quota_oraria']}/ora).",
                    },
                    "unit_amount": piano["prezzo_centesimi"],
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            client_reference_id=str(utente["id"]),
            metadata={"utente_id": str(utente["id"]), "piano": piano_id},
            subscription_data={"metadata": {"utente_id": str(utente["id"]), "piano": piano_id}},
            customer_email=utente["email"],
            success_url=f"{BASE_URL_PUBBLICO}/app.html?abbonamento=ok",
            cancel_url=f"{BASE_URL_PUBBLICO}/app.html?abbonamento=annullato",
        )
    except stripe.error.StripeError as exc:
        logger.error("Errore nella creazione della sessione Stripe (abbonamento %s): %s", piano_id, exc)
        raise HTTPException(502, "Non è stato possibile aprire la pagina di pagamento. Riprova più tardi.")
    return {"checkout_url": sessione.url}


@app.post("/api/abbonamento/annulla")
async def api_abbonamento_annulla(utente: dict = Depends(richiedi_utente)):
    """Annulla l'abbonamento al TERMINE del periodo già pagato (cancel_at_period_end
    su Stripe): l'utente mantiene l'accesso alla quota fino a abbonamento_rinnovo_il,
    senza essere addebitato di nuovo al rinnovo successivo — lo stato Stripe della
    subscription resta 'active' fino a quel momento (quindi qui non c'è nulla da
    aggiornare subito nel nostro database: lo stato mostrato resta 'attivo', a ragione,
    finché la quota è ancora davvero utilizzabile). Lo stato definitivo arriva dal
    webhook customer.subscription.deleted quando Stripe chiude per davvero
    l'abbonamento (vedi termina_abbonamento)."""
    if utente.get("abbonamento_stato") != "attivo" or not utente.get("stripe_subscription_id"):
        raise HTTPException(400, "Non risulta nessun abbonamento attivo da annullare.")
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Operazione non disponibile al momento. Riprova più tardi.")
    sub_id = utente["stripe_subscription_id"]
    try:
        stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
    except stripe.error.StripeError as exc:
        logger.error("Errore nell'annullamento dell'abbonamento Stripe %s: %s", sub_id, exc)
        raise HTTPException(502, "Non è stato possibile annullare l'abbonamento. Riprova più tardi.")
    scadenza = utente.get("abbonamento_rinnovo_il") or "del termine del periodo corrente"
    return {
        "ok": True,
        "messaggio": f"Abbonamento annullato: resta attivo fino al {scadenza}, poi non verrà rinnovato.",
    }


_STATI_STRIPE_ATTIVI = {"active", "trialing"}
_STATI_STRIPE_IN_RITARDO = {"past_due", "unpaid"}


def _sincronizza_abbonamento_da_subscription(conn: "accounts_db.sqlite3.Connection", sub: dict) -> None:
    """Allinea il nostro database allo stato di una Stripe Subscription,
    a partire da un evento customer.subscription.created/updated (o da una
    lettura diretta dell'oggetto). Usa PRIMA i metadata della subscription
    (impostati da subscription_data.metadata in /api/abbonamento/attiva, quindi
    presenti fin dalla creazione) e, se mancano, ricade sulla ricerca per
    stripe_subscription_id già salvato — utile per eventi successivi in cui i
    metadata potrebbero non essere ripetuti."""
    metadata = sub.get("metadata") or {}
    utente_id = None
    piano_id = metadata.get("piano")
    try:
        if metadata.get("utente_id"):
            utente_id = int(metadata["utente_id"])
    except (TypeError, ValueError):
        utente_id = None
    if utente_id is None:
        esistente = accounts_db.get_user_by_stripe_subscription_id(conn, sub["id"])
        if not esistente:
            logger.error("Webhook Stripe subscription senza utente_id riconoscibile: %s", sub.get("id"))
            return
        utente_id = esistente["id"]
        piano_id = piano_id or esistente.get("abbonamento_piano")
    if not piano_id:
        logger.error("Webhook Stripe subscription senza piano riconoscibile: %s", sub.get("id"))
        return

    stato_stripe = sub.get("status")
    if stato_stripe in _STATI_STRIPE_ATTIVI:
        stato = "attivo"
    elif stato_stripe in _STATI_STRIPE_IN_RITARDO:
        stato = "in_ritardo"
    else:
        stato = "terminato"

    rinnovo_il = None
    periodo_fine = sub.get("current_period_end")
    if periodo_fine:
        rinnovo_il = datetime.utcfromtimestamp(periodo_fine).strftime("%Y-%m-%d %H:%M:%S")

    if stato == "terminato":
        accounts_db.termina_abbonamento(conn, sub["id"])
    else:
        accounts_db.imposta_abbonamento(
            conn, utente_id, piano_id, stato, sub.get("customer"), sub["id"], rinnovo_il,
        )
    logger.info(
        "Abbonamento sincronizzato: utente %s, piano %s, stato Stripe %s -> %s (subscription %s)",
        utente_id, piano_id, stato_stripe, stato, sub.get("id"),
    )


@app.post("/api/stripe/webhook")
async def api_stripe_webhook(request: Request):
    """Indirizzo che Stripe chiama automaticamente per gli eventi di
    pagamento e abbonamento (da configurare nel pannello Stripe: Sviluppatori
    > Webhook, puntato su <url-del-sito>/api/stripe/webhook, eventi
    'checkout.session.completed', 'customer.subscription.created',
    'customer.subscription.updated', 'customer.subscription.deleted'). La
    firma nell'header 'Stripe-Signature' viene verificata con
    STRIPE_WEBHOOK_SECRET per essere certi che l'avviso arrivi davvero da
    Stripe: senza questo controllo chiunque potrebbe chiamare questo
    indirizzo e accreditarsi crediti o un abbonamento gratis. Stripe può
    inviare lo stesso avviso più di una volta (a garanzia di consegna): vedi
    accounts_db.registra_pagamento_se_nuovo per l'idempotenza dei crediti;
    la sincronizzazione dell'abbonamento è invece naturalmente idempotente
    (scrive sempre lo stato più recente, non lo somma a quello precedente)."""
    if not STRIPE_WEBHOOK_SECRET:
        # Non configurato: nessun accredito possibile, ma si risponde comunque
        # con successo per non far ritentare Stripe all'infinito un webhook
        # che qui non sappiamo verificare.
        logger.error("Ricevuto webhook Stripe ma STRIPE_WEBHOOK_SECRET non è configurata: ignorato.")
        return {"ok": True, "elaborato": False}

    corpo = await request.body()
    firma = request.headers.get("stripe-signature", "")
    try:
        evento = stripe.Webhook.construct_event(corpo, firma, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Firma del webhook non valida.")

    if evento["type"] == "checkout.session.completed":
        # .to_dict() converte lo StripeObject (che supporta l'accesso con [],
        # ma NON il metodo .get() dei dict veri) in un dict normale, così il
        # resto della funzione può usare .get() con i valori di default senza
        # dover verificare ogni volta la presenza della chiave.
        sessione = evento["data"]["object"].to_dict()
        if sessione.get("mode") == "subscription":
            # L'attivazione vera e propria dell'abbonamento è gestita dagli
            # eventi customer.subscription.* qui sotto (la Subscription creata
            # da questo checkout porta gli stessi metadata, vedi
            # subscription_data.metadata in /api/abbonamento/attiva): qui non
            # c'è nulla da accreditare come crediti.
            return {"ok": True}
        metadata = sessione.get("metadata") or {}
        try:
            utente_id = int(metadata.get("utente_id") or sessione.get("client_reference_id"))
            crediti = int(metadata.get("crediti") or CREDITI_PACCHETTO)
        except (TypeError, ValueError):
            logger.error("Webhook Stripe checkout.session.completed senza utente_id valido: %s", sessione.get("id"))
            return {"ok": True, "elaborato": False}
        importo = sessione.get("amount_total") or PREZZO_PACCHETTO_CENTESIMI
        valuta = sessione.get("currency") or VALUTA_PAGAMENTI
        conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
        nuovo = accounts_db.registra_pagamento_se_nuovo(
            conn, sessione["id"], utente_id, crediti, importo, valuta,
        )
        if nuovo:
            logger.info("Accreditati %s crediti all'utente %s (sessione Stripe %s)", crediti, utente_id, sessione["id"])
    elif evento["type"] in ("customer.subscription.created", "customer.subscription.updated"):
        sub = evento["data"]["object"].to_dict()
        conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
        _sincronizza_abbonamento_da_subscription(conn, sub)
    elif evento["type"] == "customer.subscription.deleted":
        sub = evento["data"]["object"].to_dict()
        conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
        utente_id = accounts_db.termina_abbonamento(conn, sub["id"])
        if utente_id:
            logger.info("Abbonamento terminato per l'utente %s (subscription Stripe %s)", utente_id, sub["id"])
    return {"ok": True}


@app.get("/api/progetti")
async def api_lista_progetti(utente: dict = Depends(richiedi_utente)):
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    return {"progetti": accounts_db.list_progetti(conn, utente["id"])}


@app.post("/api/progetti")
async def api_crea_progetto(payload: dict = Body(...), utente: dict = Depends(richiedi_utente)):
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    nome = str(payload.get("nome") or "Progetto senza nome").strip() or "Progetto senza nome"
    dati = payload.get("dati")
    if dati is None:
        raise HTTPException(400, "Dati del progetto mancanti.")
    progetto = accounts_db.create_progetto(
        conn, utente["id"], nome,
        str(payload.get("committente") or ""), str(payload.get("ubicazione") or ""),
        str(payload.get("totale_testo") or ""), json.dumps(dati),
    )
    del progetto["dati_json"]  # non serve rispedirlo indietro, solo i metadati
    return {"progetto": progetto}


@app.put("/api/progetti/{progetto_id}")
async def api_aggiorna_progetto(progetto_id: int, payload: dict = Body(...), utente: dict = Depends(richiedi_utente)):
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    nome = str(payload.get("nome") or "Progetto senza nome").strip() or "Progetto senza nome"
    dati = payload.get("dati")
    if dati is None:
        raise HTTPException(400, "Dati del progetto mancanti.")
    progetto = accounts_db.update_progetto(
        conn, progetto_id, utente["id"], nome,
        str(payload.get("committente") or ""), str(payload.get("ubicazione") or ""),
        str(payload.get("totale_testo") or ""), json.dumps(dati),
    )
    if not progetto:
        raise HTTPException(404, "Progetto non trovato (o non è tuo).")
    del progetto["dati_json"]
    return {"progetto": progetto}


@app.get("/api/progetti/{progetto_id}")
async def api_leggi_progetto(progetto_id: int, utente: dict = Depends(richiedi_utente)):
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    progetto = accounts_db.get_progetto(conn, progetto_id, utente["id"])
    if not progetto:
        raise HTTPException(404, "Progetto non trovato (o non è tuo).")
    progetto["dati"] = json.loads(progetto.pop("dati_json"))
    return {"progetto": progetto}


@app.delete("/api/progetti/{progetto_id}")
async def api_elimina_progetto(progetto_id: int, utente: dict = Depends(richiedi_utente)):
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    if not accounts_db.delete_progetto(conn, progetto_id, utente["id"]):
        raise HTTPException(404, "Progetto non trovato (o non è tuo).")
    return {"ok": True}


def _save_upload(file: UploadFile) -> str:
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    size = 0
    with dest.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    413,
                    f"Il file '{file.filename}' è troppo grande (supera {MAX_UPLOAD_BYTES // (1024*1024)} MB, "
                    "il limite per singolo file): riducilo o dividilo e riprova.",
                )
            f.write(chunk)
    return str(dest)


def _merge_pdfs(paths: list[str], out_path: str) -> str:
    """Unisce più PDF caricati per la stessa categoria (es. pianta + prospetti +
    sezioni) in un unico documento, nell'ordine in cui sono stati selezionati,
    così la pipeline di estrazione (che lavora su un solo file) resta invariata.
    """
    if len(paths) == 1:
        return paths[0]
    merged = fitz.open()
    for p in paths:
        with fitz.open(p) as d:
            merged.insert_pdf(d)
    merged.save(out_path)
    merged.close()
    return out_path


@app.get("/api/intake/requirements")
async def api_intake_requirements(tipo_intervento: str):
    if tipo_intervento not in TIPI_INTERVENTO:
        raise HTTPException(400, f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")
    return [asdict(d) for d in required_documents(tipo_intervento)]


@app.get("/api/parametri")
async def api_parametri():
    return [asdict(p) for p in PARAMETRI]


@app.post("/api/validate")
async def api_validate(file: UploadFile = File(...)):
    path = _save_upload(file)
    result = validate_only(path)
    return asdict(result)


@app.post("/api/questions")
async def api_questions(capitolato_text: str | None = Form(None)):
    qs = questions_for_project(capitolato_text)
    return {"questions": [asdict(q) for q in qs]}


@app.get("/api/prezzari")
async def api_list_prezzari():
    conn = prezzario_db.get_connection(DB_PATH)
    prezzario_db.ensure_placeholder_seed(conn)
    return prezzario_db.list_prezzari(conn)


@app.get("/api/catalogo-prezzario")
async def api_catalogo_prezzario(q: str = "", vol: str = "", limit: int = 50, offset: int = 0):
    """Consultazione in sola lettura del catalogo completo del prezzario
    ufficiale (35.063 voci): NON incide in alcun modo sul matching automatico
    del computo, serve solo perché l'utente possa cercare un codice/voce
    ufficiale e copiarne a mano codice/prezzo in una riga del computo. Se il
    file dati del catalogo non è presente in questa installazione, risponde
    con un elenco vuoto invece di un errore: è una funzione accessoria, non
    deve mai bloccare il resto del sito."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conn = prezzario_db.get_connection(DB_PATH)
    catalog_id = prezzario_db.catalog_id_if_seeded(conn, catalogo_data.CATALOG_VERSION)
    if catalog_id is None:
        # Prima richiesta dopo l'avvio (o dati aggiornati): carica le 35.000
        # righe da disco e popola il database. Le richieste successive
        # passano dal ramo veloce sopra, senza ricaricare nulla.
        try:
            catalog_rows = catalogo_data.load_catalog_rows()
        except FileNotFoundError:
            return {"totale": 0, "voci": [], "disponibile": False}
        catalog_id = prezzario_db.ensure_catalog_seed(
            conn, catalogo_data.CATALOG_META, catalog_rows, catalogo_data.CATALOG_VERSION,
        )
    risultato = prezzario_db.search_catalog(conn, catalog_id, query=q, volume=vol, limit=limit, offset=offset)
    risultato["disponibile"] = True
    return risultato


@app.post("/api/prezzari/upload")
async def api_upload_prezzario(
    file: UploadFile = File(...),
    regione: str = Form(...),
    anno: int = Form(...),
    nome: str = Form(...),
):
    """Carica un prezzario reale (CSV con colonne: categoria, sotto_tipo, codice,
    descrizione, unita_misura, prezzo) e lo salva nel database per essere
    riusato nei prossimi progetti, come richiesto."""
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    required_cols = {"categoria", "sotto_tipo", "codice", "descrizione", "unita_misura", "prezzo"}
    if not rows or not required_cols.issubset(rows[0].keys()):
        raise HTTPException(400, f"Il CSV deve contenere le colonne: {sorted(required_cols)}")
    conn = prezzario_db.get_connection(DB_PATH)
    pid = prezzario_db.import_prezzario_from_rows(
        conn, {"regione": regione, "anno": anno, "nome": nome}, rows,
    )

    # Avviso (non blocca il caricamento, che resta comunque salvato): "categoria" e
    # "sotto_tipo" NON sono etichette libere, sono valori interni fissi che il motore
    # di calcolo cerca esattamente (es. categoria "cantiere", sotto_tipo
    # "approntamento") — un CSV con nomi diversi da quelli attesi viene importato
    # correttamente ma non produce NESSUNA voce nel computo, in modo silenzioso.
    # Qui si confronta ogni riga con il vocabolario di riferimento e si avvisa subito,
    # invece di lasciare scoprire il problema solo al momento del calcolo.
    coppie_csv = {(r["categoria"].strip(), r["sotto_tipo"].strip()) for r in rows if r.get("categoria") and r.get("sotto_tipo")}
    corrispondenze = coppie_csv & REFERENCE_CATEGORIA_SOTTOTIPO
    voci_sempre_mancanti = VOCI_SEMPRE_TENTATE - coppie_csv
    avviso = None
    if not corrispondenze:
        avviso = (
            "ATTENZIONE: nessuna riga di questo CSV corrisponde a una categoria/sotto_tipo riconosciuta dal "
            "sistema. 'categoria' e 'sotto_tipo' non sono etichette libere: devono coincidere ESATTAMENTE con i "
            "valori interni usati dal motore di calcolo (es. categoria 'cantiere', sotto_tipo 'approntamento'). "
            "Con questo prezzario selezionato, il computo risulterebbe COMPLETAMENTE VUOTO. Contatta chi ha "
            "sviluppato il sistema per avere l'elenco esatto dei valori attesi, oppure continua a usare il "
            "prezzario di riferimento predefinito (Regione Lombardia 2022)."
        )
    elif voci_sempre_mancanti:
        avviso = (
            "Attenzione: alcune voci sempre presenti in ogni computo non sono state trovate in questo CSV "
            f"(mancano le combinazioni categoria/sotto_tipo: {sorted(voci_sempre_mancanti)}), quindi non "
            "compariranno nei computi generati con questo prezzario. Le altre voci importate che corrispondono "
            f"al vocabolario riconosciuto ({len(corrispondenze)} su {len(rows)} righe) funzioneranno regolarmente."
        )

    return {"prezzario_id": pid, "voci_importate": len(rows), "voci_riconosciute": len(corrispondenze), "avviso": avviso}


@app.post("/api/estrai-vani")
async def api_estrai_vani(
    request: Request,
    tipo_intervento: str = Form(...),
    file_progetto: list[UploadFile] = File(...),
    file_stato_di_fatto: list[UploadFile] = File(default=[]),
    file_strutturale: list[UploadFile] = File(default=[]),
    file_copertura: list[UploadFile] = File(default=[]),
    file_legge10: list[UploadFile] = File(default=[]),
    file_acustica: list[UploadFile] = File(default=[]),
    file_relazione_tecnica: list[UploadFile] = File(default=[]),
    file_prospetti: list[UploadFile] = File(default=[]),
    file_render: list[UploadFile] = File(default=[]),
    file_modello_3d: list[UploadFile] = File(default=[]),
    file_altri_documenti: list[UploadFile] = File(default=[]),
    legend_page: int = Form(1),
    structural_legend_page: int = Form(1),
):
    """Prima fase: dai PDF ai vani/aperture/elementi strutturali rilevati,
    SENZA calcolare prezzi né generare file. L'utente li rivede (e corregge,
    se serve) nel passo successivo, prima di generare il computo vero e
    proprio con /api/generate — necessario perché su disegni CAD reali molto
    dettagliati il rilievo automatico non è sempre perfetto (es. due ambienti
    attigui possono risultare uniti in un'unica area)."""
    if tipo_intervento not in TIPI_INTERVENTO:
        raise HTTPException(400, f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")

    job_id = uuid.uuid4().hex
    progetto_paths = [_save_upload(f) for f in file_progetto if f.filename]
    sdf_paths = [_save_upload(f) for f in file_stato_di_fatto if f.filename]
    strut_paths = [_save_upload(f) for f in file_strutturale if f.filename]
    cop_paths = [_save_upload(f) for f in file_copertura if f.filename]
    legge10_paths = [_save_upload(f) for f in file_legge10 if f.filename]
    acustica_paths = [_save_upload(f) for f in file_acustica if f.filename]
    relazione_tecnica_paths = [_save_upload(f) for f in file_relazione_tecnica if f.filename]
    prospetti_paths = [_save_upload(f) for f in file_prospetti if f.filename]
    # Render: analizzato (vedi più sotto) da un'AI con visione, SOLO come riferimento
    # qualitativo — mai per calcolare quantità/prezzi in automatico. Modello 3D:
    # allegato SOLO come riferimento per la consultazione manuale (formato proprietario,
    # nessun parsing della geometria in questa versione).
    render_paths = [_save_upload(f) for f in file_render if f.filename]
    modello_3d_paths = [_save_upload(f) for f in file_modello_3d if f.filename]
    # Altri documenti in formato libero: come il modello 3D, allegati SOLO come
    # riferimento per la consultazione manuale — nessun formato è previsto, quindi
    # nessun parsing automatico è possibile in generale (a differenza dei campi
    # sopra, dedicati a un formato/uso specifico).
    altri_documenti_paths = [_save_upload(f) for f in file_altri_documenti if f.filename]

    if not progetto_paths:
        return JSONResponse(status_code=422, content={
            "error": "Carica almeno un elaborato per la pianta di progetto."})

    if not relazione_tecnica_paths:
        return JSONResponse(status_code=422, content={
            "error": "È obbligatorio caricare la relazione tecnica descrittiva dell'intervento."})

    pdf_progetto_path = _merge_pdfs(progetto_paths, str(UPLOAD_DIR / f"{job_id}_progetto_unito.pdf"))
    pdf_sdf_path = _merge_pdfs(sdf_paths, str(UPLOAD_DIR / f"{job_id}_sdf_unito.pdf")) if sdf_paths else None
    pdf_strut_path = _merge_pdfs(strut_paths, str(UPLOAD_DIR / f"{job_id}_strutturale_unito.pdf")) if strut_paths else None
    pdf_cop_path = _merge_pdfs(cop_paths, str(UPLOAD_DIR / f"{job_id}_copertura_unito.pdf")) if cop_paths else None

    if tipo_intervento == "ristrutturazione" and not pdf_sdf_path:
        return JSONResponse(status_code=422, content={
            "error": "Per una ristrutturazione è obbligatorio caricare anche la pianta dello stato di fatto."})

    extraction = extract_quantities(
        tipo_intervento=tipo_intervento, pdf_progetto_path=pdf_progetto_path,
        pdf_stato_di_fatto_path=pdf_sdf_path, pdf_strutturale_path=pdf_strut_path,
        pdf_copertura_path=pdf_cop_path, legend_page=legend_page,
        structural_legend_page=structural_legend_page,
    )
    if not extraction.ok:
        return JSONResponse(status_code=422, content={
            "error": "Uno o più elaborati non sono conformi ai requisiti (scala/quote/vettorialità).",
            "messages": extraction.errors + extraction.validation_messages,
        })

    legge10 = extract_stratigrafie_reference(legge10_paths) if legge10_paths else None
    acustica = extract_acustica_reference(acustica_paths) if acustica_paths else None
    relazione_tecnica = extract_relazione_tecnica(relazione_tecnica_paths)
    documenti_riferimento_allegati = (
        [Path(p).name.split("_", 1)[-1] for p in render_paths]
        + [Path(p).name.split("_", 1)[-1] for p in modello_3d_paths]
        + [Path(p).name.split("_", 1)[-1] for p in altri_documenti_paths]
    )
    if documenti_riferimento_allegati:
        extraction.note_metodologiche.append(
            "Documenti allegati come riferimento per la consultazione manuale: "
            f"{', '.join(documenti_riferimento_allegati)}."
        )

    # --- Prospetti quotati caricati: se presenti, ne viene fatto un rilievo
    # meccanico delle bande di altezza (vedi elevation_engine.py) PRIMA di
    # analizzare i render, così l'AI di visione può abbinare un rivestimento
    # visto nel render a un'altezza REALMENTE misurata (mai calcolata da lei)
    # e ottenere una superficie di facciata misurata, non stimata. ---
    pdf_prospetti_path = (
        _merge_pdfs(prospetti_paths, str(UPLOAD_DIR / f"{job_id}_prospetti_uniti.pdf"))
        if prospetti_paths else None
    )
    bande_prospetti_viste: list[dict] = []
    if pdf_prospetti_path:
        try:
            with fitz.open(pdf_prospetti_path) as doc_prospetti:
                bande_prospetti_viste = extract_elevation_bands(doc_prospetti)
        except Exception:
            bande_prospetti_viste = []
    bande_prospetti_flat = [b for vista in bande_prospetti_viste for b in vista["bande"]]
    if prospetti_paths and not bande_prospetti_flat:
        extraction.note_metodologiche.append(
            "Prospetti quotati caricati, ma non è stato possibile individuare in modo affidabile quote "
            "altimetriche utilizzabili per il rilievo automatico delle altezze di facciata: eventuali "
            "rivestimenti individuati nei render restano solo un riferimento visivo, senza superficie misurata "
            "— verifica e misura a mano dai prospetti."
        )

    # --- Analisi visiva dei render caricati (facoltativa: solo se ci sono render
    # E una chiave AI configurata). A differenza del modello 3D (formato proprietario
    # non leggibile), un render è un'immagine: il modello di visione può osservarla e
    # descrivere materiali/elementi visibili (facciate, parapetti, infissi, pavimentazioni
    # esterne) — come riferimento qualitativo per l'utente, e per la sola categoria
    # "facciata", se sono stati caricati anche prospetti quotati con bande misurabili,
    # può abbinare l'elemento a un'altezza reale (mai calcolata/inventata dall'AI, sempre
    # verificata server-side in analizza_render/_banda_valida) per ottenere una superficie
    # MISURATA (altezza x perimetro esterno), da confermare comunque a mano prima di
    # considerarla definitiva. Se l'AI non è configurata, l'utente non è connesso, non ha
    # crediti sufficienti, o la chiamata fallisce, NON blocca l'estrazione: viene solo
    # annotato (i crediti eventualmente scalati vengono restituiti se l'AI non risponde). ---
    analisi_render = None
    if render_paths:
        _conn_utilizzi = accounts_db.get_connection(ACCOUNTS_DB_PATH)
        _utente_corrente = _utente_sessione(request)
        _id_richiesta = _identificativo_richiesta(request, _utente_corrente)
        _binario_render = None
        try:
            _verifica_limite_ai(_conn_utilizzi, _id_richiesta)
            _binario_render = _autorizza_azione_ai(_conn_utilizzi, _utente_corrente, "ai_analisi_render")
        except HTTPException as exc:
            extraction.note_metodologiche.append(
                f"Analisi visiva dei render non disponibile ({exc.detail}): i render restano comunque "
                "allegati come riferimento per la consultazione manuale."
            )
        else:
            try:
                analisi_render = analizza_render(
                    render_paths, prospetti_pdf_path=pdf_prospetti_path, bande_prospetti=bande_prospetti_flat,
                )
                accounts_db.registra_utilizzo(
                    _conn_utilizzi, _id_richiesta, "ai_analisi_render", utente_id=_utente_corrente["id"],
                )
                for elemento in analisi_render["elementi"]:
                    banda = elemento.get("banda_abbinata")
                    if banda and extraction.perimetro_esterno_m > 0:
                        elemento["area_m2"] = round(banda["altezza_m"] * extraction.perimetro_esterno_m, 2)
                    else:
                        elemento["area_m2"] = None
                righe_render = "; ".join(
                    f"[{e['categoria']}] {e['descrizione']}"
                    + (f" — superficie misurata: {e['area_m2']} m² (banda {e['banda_abbinata']['da_m']}-"
                       f"{e['banda_abbinata']['a_m']} m dal prospetto)" if e.get("area_m2") else "")
                    for e in analisi_render["elementi"]
                )
                extraction.note_metodologiche.append(
                    f"🖼️ Analisi visiva AI dei {analisi_render['immagini_analizzate']} render caricati (riferimento "
                    "qualitativo, NON usato da solo per calcolare quantità o prezzi — verifica sempre di persona): "
                    f"{analisi_render['sintesi']}" + (f" Dettaglio: {righe_render}." if righe_render else "")
                )
                if analisi_render["immagini_scartate"]:
                    extraction.note_metodologiche.append(
                        "I seguenti file caricati come render non sono immagini leggibili e non sono stati "
                        f"analizzati: {', '.join(analisi_render['immagini_scartate'])}."
                    )
            except AiAssistantError as exc:
                if _binario_render == "crediti":
                    accounts_db.aggiungi_crediti(
                        _conn_utilizzi, _utente_corrente["id"], COSTO_CREDITI["ai_analisi_render"],
                    )
                extraction.note_metodologiche.append(
                    f"Analisi visiva dei render non disponibile ({exc}): i render restano comunque allegati come "
                    "riferimento per la consultazione manuale."
                    + (" Il credito non è stato addebitato." if _binario_render == "crediti" else "")
                )

    return {
        "rooms": [asdict(r) for r in extraction.rooms],
        "openings": [asdict(o) for o in extraction.openings],
        "structural_elements": [asdict(e) for e in extraction.structural_elements],
        "footprint_area_m2": extraction.footprint_area_m2,
        "perimetro_esterno_m": extraction.perimetro_esterno_m,
        "piscina_area_m2": extraction.piscina_area_m2,
        "piscina_perimetro_m": extraction.piscina_perimetro_m,
        "piscina_lunghezza_m": extraction.piscina_lunghezza_m,
        "piscina_larghezza_m": extraction.piscina_larghezza_m,
        "roof_area_m2": extraction.roof_area_m2,
        "rooms_sdf": [asdict(r) for r in extraction.rooms_sdf] if extraction.rooms_sdf else [],
        "confronto": [asdict(c) for c in extraction.confronto],
        "note_metodologiche": extraction.note_metodologiche,
        "validation_messages": extraction.validation_messages,
        "legge10": legge10,
        "acustica": acustica,
        "relazione_tecnica": relazione_tecnica,
        "render_count": len(render_paths),
        "modello_3d_count": len(modello_3d_paths),
        "altri_documenti_count": len(altri_documenti_paths),
        "documenti_riferimento_allegati": documenti_riferimento_allegati,
        "analisi_render": analisi_render,
    }


@app.post("/api/calcola-voci")
async def api_calcola_voci(
    tipo_intervento: str = Form(...),
    rooms_json: str = Form("[]"),
    openings_json: str = Form("[]"),
    structural_elements_json: str = Form("[]"),
    footprint_area_m2: float = Form(0.0),
    perimetro_esterno_m: float = Form(0.0),
    piscina_area_m2: float = Form(0.0),
    piscina_perimetro_m: float = Form(0.0),
    piscina_lunghezza_m: float = Form(0.0),
    piscina_larghezza_m: float = Form(0.0),
    roof_area_m2: float = Form(0.0),
    rooms_sdf_json: str = Form("[]"),
    confronto_json: str = Form("[]"),
    note_metodologiche_json: str = Form("[]"),
    validation_messages_json: str = Form("[]"),
    nome_progetto: str = Form("Progetto senza nome"),
    committente: str = Form(""),
    ubicazione: str = Form(""),
    capitolato_text: str | None = Form(None),
    answers_json: str = Form("{}"),
    parametri_json: str = Form("{}"),
    prezzario_id: int | None = Form(None),
    acustica_materiali_json: str = Form("[]"),
    render_facciate_json: str = Form("[]"),
):
    """Seconda fase: dai vani/aperture/elementi (rilevati da /api/estrai-vani
    ed eventualmente corretti dall'utente nella pagina di verifica) alle righe
    di computo VALORIZZATE (prezzo x quantità), SENZA ancora generare i file
    finali. Restituisce le voci in JSON perché l'utente le riveda — e le
    corregga o commenti riga per riga — nel browser, prima di scaricare i
    file definitivi con /api/generate."""
    if tipo_intervento not in TIPI_INTERVENTO:
        raise HTTPException(400, f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")

    try:
        rooms = [RoomQuantity(**r) for r in json.loads(rooms_json)]
        openings = [OpeningQuantity(**o) for o in json.loads(openings_json)]
        structural_elements = [TaggedElement(**e) for e in json.loads(structural_elements_json)]
        rooms_sdf_list = [RoomQuantity(**r) for r in json.loads(rooms_sdf_json)]
        confronto = [RoomComparison(**c) for c in json.loads(confronto_json)]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Dati di vani/aperture non validi: {exc}")

    if not rooms and not structural_elements and footprint_area_m2 <= 0 and roof_area_m2 <= 0:
        return JSONResponse(status_code=422, content={
            "error": "Nessun vano, elemento strutturale, sedime o copertura da computare: "
                     "torna al passaggio di verifica ed elenca almeno un vano o un elemento."})

    answers = json.loads(answers_json)
    parametri_overrides = json.loads(parametri_json)
    note_metodologiche = json.loads(note_metodologiche_json)
    validation_messages = json.loads(validation_messages_json)
    try:
        acustica_materiali = [str(m) for m in json.loads(acustica_materiali_json)]
    except (TypeError, ValueError):
        acustica_materiali = []
    try:
        # Elementi di facciata (categoria "facciata" di analisi_render) che l'utente
        # ha confermato nel passaggio di verifica: ognuno arriva già con "area_m2"
        # calcolata server-side da /api/estrai-vani (altezza misurata su prospetto x
        # perimetro esterno) — qui non si ricalcola nulla, si passa solo a valle.
        render_facciate = [dict(r) for r in json.loads(render_facciate_json) if isinstance(r, dict)]
    except (TypeError, ValueError):
        render_facciate = []
    meta = ProjectMeta(nome_progetto=nome_progetto, committente=committente, ubicazione=ubicazione)

    result = compute_voci(
        tipo_intervento=tipo_intervento, meta=meta, answers=answers, parametri_overrides=parametri_overrides,
        rooms=rooms, openings=openings, structural_elements=structural_elements,
        footprint_area_m2=footprint_area_m2, roof_area_m2=roof_area_m2,
        rooms_sdf=(rooms_sdf_list or None), confronto=confronto,
        note_metodologiche=note_metodologiche, validation_messages=validation_messages,
        db_path=DB_PATH, prezzario_id=prezzario_id, capitolato_text=capitolato_text,
        perimetro_esterno_m=perimetro_esterno_m,
        piscina_area_m2=piscina_area_m2, piscina_perimetro_m=piscina_perimetro_m,
        piscina_lunghezza_m=piscina_lunghezza_m, piscina_larghezza_m=piscina_larghezza_m,
        acustica_materiali=acustica_materiali,
        render_facciate=render_facciate,
    )

    if not result.voci:
        # Diagnostica: build_computo() tenta SEMPRE almeno le due voci di
        # apprestamento di cantiere (v. matching.py), indipendentemente dai dati
        # geometrici — e il controllo più sopra ha già escluso il caso di un input
        # completamente vuoto. Se nonostante questo il risultato è a zero voci, la
        # causa quasi certa è che il prezzario ATTIVO non contiene nessuna
        # categoria/sotto_tipo che il sistema sa cercare (es. un CSV caricato con
        # nomi diversi da quelli attesi, o un prezzario di prova rimasto selezionato
        # per errore): senza questo controllo l'utente riceverebbe un computo vuoto
        # con un 200 OK, senza nessuna spiegazione del motivo.
        prezzario_attivo = meta.prezzario_nome or (f"id {prezzario_id}" if prezzario_id else "sconosciuto")
        errore_principale = (
            f"Il prezzario attualmente selezionato (\"{prezzario_attivo}\") non contiene nessuna voce "
            "compatibile con i dati inseriti: il computo risulterebbe completamente vuoto."
        )
        return JSONResponse(status_code=422, content={
            "error": errore_principale,
            "messages": [
                errore_principale,
                "Torna al passaggio 3 (\"Prezzario di riferimento\") e controlla quale prezzario è selezionato "
                "nel menu a tendina.",
                "Se hai caricato un prezzario reale (CSV), le colonne 'categoria' e 'sotto_tipo' devono contenere "
                "ESATTAMENTE gli stessi valori interni usati dal sistema (es. categoria 'cantiere', sotto_tipo "
                "'approntamento'), non nomi liberi a scelta — verifica l'avviso mostrato al momento del "
                "caricamento del CSV.",
                "In alternativa, seleziona il prezzario di riferimento predefinito (Regione Lombardia 2022) per "
                "verificare che il resto del flusso funzioni correttamente.",
            ],
        })

    return {
        "voci": [asdict(v) for v in result.voci],
        "totale": result.totale,
        "note_metodologiche": result.note_metodologiche,
        "validation_messages": validation_messages,
        "confronto": [asdict(c) for c in result.confronto],
        "meta": {
            "nome_progetto": meta.nome_progetto,
            "committente": meta.committente,
            "ubicazione": meta.ubicazione,
            "prezzario_nome": meta.prezzario_nome,
            "tipo_intervento": tipo_intervento,
        },
    }


def _parse_generate_payload(
    tipo_intervento: str, voci_json: str, confronto_json: str,
    note_metodologiche_json: str, validation_messages_json: str,
    nome_progetto: str, committente: str, ubicazione: str, prezzario_nome: str,
):
    """Validazione/parsing comune a /api/generate e /api/scarica-formato: dai
    campi form ricevuti (voci del computo, eventualmente corrette a mano
    dall'utente, e metadati di progetto) agli oggetti tipizzati pronti per i
    generatori di output. Solleva HTTPException in caso di dati non validi."""
    if tipo_intervento not in TIPI_INTERVENTO:
        raise HTTPException(400, f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")
    try:
        voci = [ComputoVoce(**v) for v in json.loads(voci_json)]
        confronto = [RoomComparison(**c) for c in json.loads(confronto_json)]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Dati del computo non validi: {exc}")
    note_metodologiche = json.loads(note_metodologiche_json)
    validation_messages = json.loads(validation_messages_json)
    meta = ProjectMeta(nome_progetto=nome_progetto, committente=committente, ubicazione=ubicazione,
                        prezzario_nome=prezzario_nome, tipo_intervento=tipo_intervento)
    return voci, confronto, note_metodologiche, validation_messages, meta


@app.post("/api/generate")
async def api_generate(
    request: Request,
    tipo_intervento: str = Form(...),
    voci_json: str = Form(...),
    nome_progetto: str = Form("Progetto senza nome"),
    committente: str = Form(""),
    ubicazione: str = Form(""),
    prezzario_nome: str = Form("Prezzario Regione Lombardia 2022 (selezione di riferimento)"),
    confronto_json: str = Form("[]"),
    note_metodologiche_json: str = Form("[]"),
    validation_messages_json: str = Form("[]"),
):
    """Terza fase: dalle righe di computo calcolate da /api/calcola-voci ed
    EVENTUALMENTE corrette/commentate a mano dall'utente nel browser, al
    pacchetto completo dei file finali (Excel, PriMus, Word, PDF) in un unico
    zip. Non ricalcola nulla: usa esattamente le righe ricevute, così le
    correzioni dell'utente sono quelle che finiscono nei file scaricati. Per
    scaricare un solo formato alla volta, vedi /api/scarica-formato."""
    voci, confronto, note_metodologiche, validation_messages, meta = _parse_generate_payload(
        tipo_intervento, voci_json, confronto_json, note_metodologiche_json, validation_messages_json,
        nome_progetto, committente, ubicazione, prezzario_nome,
    )
    if not voci:
        return JSONResponse(status_code=422, content={
            "error": "Il computo non contiene nessuna voce da generare: torna al passaggio precedente."})

    job_id = uuid.uuid4().hex
    excel_out = str(OUTPUT_DIR / f"{job_id}_computo.xlsx")
    primus_out = str(OUTPUT_DIR / f"{job_id}_elenco_prezzi_primus.xlsx")
    word_out = str(OUTPUT_DIR / f"{job_id}_computo.docx")
    pdf_out = str(OUTPUT_DIR / f"{job_id}_computo.pdf")

    build_files_from_voci(
        voci=voci, meta=meta, note_metodologiche=note_metodologiche,
        validation_messages=validation_messages, confronto=confronto,
        excel_out=excel_out, primus_out=primus_out, word_out=word_out, pdf_out=pdf_out,
    )

    zip_path = str(OUTPUT_DIR / f"{job_id}_computo.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(excel_out, arcname="computo_metrico.xlsx")
        zf.write(primus_out, arcname="elenco_prezzi_per_primus.xlsx")
        zf.write(word_out, arcname="relazione_computo.docx")
        zf.write(pdf_out, arcname="computo_metrico.pdf")

    # Registrato (non limitato, non ancora a pagamento): pura visibilità sui
    # consumi in vista di un futuro piano a crediti/abbonamento — vedi la nota
    # sulla tabella 'utilizzi' in accounts/db.py.
    _conn_utilizzi = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    _utente_corrente = _utente_sessione(request)
    accounts_db.registra_utilizzo(
        _conn_utilizzi, _identificativo_richiesta(request, _utente_corrente), "generazione_computo",
        utente_id=_utente_corrente["id"] if _utente_corrente else None, dettaglio="zip_completo",
    )

    return FileResponse(zip_path, media_type="application/zip",
                         filename="computo_metrico_estimativo.zip")


@app.post("/api/scarica-formato")
async def api_scarica_formato(
    request: Request,
    formato: str = Form(...),
    tipo_intervento: str = Form(...),
    voci_json: str = Form(...),
    nome_progetto: str = Form("Progetto senza nome"),
    committente: str = Form(""),
    ubicazione: str = Form(""),
    prezzario_nome: str = Form("Prezzario Regione Lombardia 2022 (selezione di riferimento)"),
    confronto_json: str = Form("[]"),
    note_metodologiche_json: str = Form("[]"),
    validation_messages_json: str = Form("[]"),
):
    """Come /api/generate, ma genera e restituisce UN SOLO file (formato:
    'excel' | 'pdf' | 'primus' | 'word') invece dello zip completo — per i
    pulsanti di download separati nel passaggio di revisione, così l'utente
    scarica solo il formato che gli serve in quel momento."""
    if formato not in FORMATI_SINGOLI:
        raise HTTPException(400, f"formato deve essere uno tra {sorted(FORMATI_SINGOLI)}")

    voci, confronto, note_metodologiche, validation_messages, meta = _parse_generate_payload(
        tipo_intervento, voci_json, confronto_json, note_metodologiche_json, validation_messages_json,
        nome_progetto, committente, ubicazione, prezzario_nome,
    )
    if not voci:
        return JSONResponse(status_code=422, content={
            "error": "Il computo non contiene nessuna voce da generare: torna al passaggio precedente."})

    nome_file, media_type = FORMATI_SINGOLI[formato]
    job_id = uuid.uuid4().hex
    out_path = str(OUTPUT_DIR / f"{job_id}_{nome_file}")

    build_single_file(
        formato, voci=voci, meta=meta, note_metodologiche=note_metodologiche,
        validation_messages=validation_messages, confronto=confronto, out_path=out_path,
    )

    _conn_utilizzi = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    _utente_corrente = _utente_sessione(request)
    accounts_db.registra_utilizzo(
        _conn_utilizzi, _identificativo_richiesta(request, _utente_corrente), "generazione_computo",
        utente_id=_utente_corrente["id"] if _utente_corrente else None, dettaglio=formato,
    )

    return FileResponse(out_path, media_type=media_type, filename=nome_file)


@app.post("/api/interpreta-commento")
async def api_interpreta_commento(request: Request, payload: dict = Body(...)):
    """Interpreta un'istruzione scritta liberamente dall'utente nella colonna
    "Commento" di una riga di computo (nel passaggio di revisione, prima del
    download) e restituisce come applicarla: modifica dei valori della riga,
    eliminazione della riga, oppure nessuna modifica con una spiegazione.
    Non tocca né il file né le altre righe: il frontend applica il risultato
    solo alla riga da cui è partita l'istruzione.

    Corpo atteso: {"voce": {...campi della riga...}, "istruzione": "testo"}.
    Richiede un account connesso con un abbonamento attivo (entro la quota) o crediti
    sufficienti (vedi _autorizza_azione_ai: 401 se non connesso, 402/429 se
    crediti/quota insufficienti) e ANTHROPIC_API_KEY configurata sul server (se
    assente, 503 — e i crediti eventualmente scalati vengono restituiti, non si paga
    un servizio non erogato). Usa il modello economico (Haiku): è una modifica
    strutturata su una riga sola, non serve un modello più costoso.
    Soggetta anche al limite giornaliero anti-abuso (vedi _verifica_limite_ai)."""
    voce = payload.get("voce") or {}
    istruzione = (payload.get("istruzione") or "").strip()
    if not istruzione:
        raise HTTPException(400, "Istruzione vuota.")
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    utente = _utente_sessione(request)
    identificativo = _identificativo_richiesta(request, utente)
    _verifica_limite_ai(conn, identificativo)
    binario = _autorizza_azione_ai(conn, utente, "ai_interpreta_commento")
    try:
        risultato = interpreta_istruzione(voce, istruzione)
    except AiAssistantError as exc:
        if binario == "crediti":
            accounts_db.aggiungi_crediti(conn, utente["id"], COSTO_CREDITI["ai_interpreta_commento"])
        return JSONResponse(status_code=503, content={"error": str(exc)})
    accounts_db.registra_utilizzo(conn, identificativo, "ai_interpreta_commento", utente_id=utente["id"])
    return risultato


@app.post("/api/revisiona-computo")
async def api_revisiona_computo(request: Request, payload: dict = Body(...)):
    """Secondo passaggio, facoltativo e su richiesta esplicita dell'utente
    (mai automatico): fa rileggere l'INTERO computo già generato a un
    modello linguistico più capace (Sonnet, non Haiku — qui serve
    ragionare su tutte le voci insieme, non modificarne una alla volta),
    che lo confronta con i dati di progetto e segnala possibili anomalie
    (prezzi o quantità fuori scala, incongruenze tra voci, categorie
    mancanti) — SENZA mai modificare nulla da solo: restituisce solo un
    elenco di osservazioni che l'utente valuta e applica a mano.

    Corpo atteso: {"voci": [...], "meta": {...}, "tipo_intervento": "..."}.
    Richiede un account connesso con un abbonamento attivo (entro la quota) o crediti
    sufficienti (401/402/429, vedi _autorizza_azione_ai — è la funzione più costosa sia
    in crediti sia in peso quota, vedi COSTO_CREDITI/PESO_QUOTA_ABBONAMENTO) e
    ANTHROPIC_API_KEY (se assente, 503 e i crediti eventualmente scalati vengono
    restituiti). Soggetta anche al limite giornaliero anti-abuso."""
    voci = payload.get("voci") or []
    meta = payload.get("meta") or {}
    tipo_intervento = payload.get("tipo_intervento") or ""
    if not voci:
        raise HTTPException(400, "Nessuna voce da revisionare.")
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    utente = _utente_sessione(request)
    identificativo = _identificativo_richiesta(request, utente)
    _verifica_limite_ai(conn, identificativo)
    binario = _autorizza_azione_ai(conn, utente, "ai_revisione_computo")
    try:
        risultato = revisiona_computo(voci, meta, tipo_intervento)
    except AiAssistantError as exc:
        if binario == "crediti":
            accounts_db.aggiungi_crediti(conn, utente["id"], COSTO_CREDITI["ai_revisione_computo"])
        return JSONResponse(status_code=503, content={"error": str(exc)})
    accounts_db.registra_utilizzo(conn, identificativo, "ai_revisione_computo", utente_id=utente["id"])
    return risultato


@app.post("/api/confronto/carica-base")
async def api_confronto_carica_base(request: Request, file: UploadFile = File(...)):
    """Prima fase del confronto preventivi (vedi il commento in cima a
    confronto_preventivi_engine.py per l'intero flusso): rilegge un computo
    metrico in Excel — NON deve necessariamente essere quello generato da
    Estima, va bene qualunque file Excel con una struttura di computo
    riconoscibile — e ne estrae le voci essenziali da usare come base del
    confronto.

    Prova prima il riconoscimento meccanico delle intestazioni di colonna
    (leggi_computo_base: gratuito, nessun account richiesto). Solo se questo
    fallisce perché il file ha una struttura troppo fuori dagli schemi,
    ripiega sull'interpretazione AI (interpreta_computo_base_excel): questo
    SECONDO tentativo richiede un account connesso con abbonamento attivo
    (entro la quota) o crediti sufficienti (401/402/429, vedi
    _autorizza_azione_ai), esattamente come /api/confronto/interpreta-preventivo."""
    path = _save_upload(file)
    messaggio_euristica: str | None = None
    try:
        voci = leggi_computo_base(path)
        return {"voci": voci, "interpretazione_ai": False}
    except ConfrontoPreventiviError as exc_heuristica:
        # Il nome dell'eccezione non sopravvive fuori dal blocco except (Python lo derefenzia
        # automaticamente alla fine del blocco): il messaggio va salvato qui, non riletto dopo.
        messaggio_euristica = str(exc_heuristica)

    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    utente = _utente_sessione(request)
    identificativo = _identificativo_richiesta(request, utente)
    _verifica_limite_ai(conn, identificativo)
    try:
        binario = _autorizza_azione_ai(conn, utente, "ai_interpreta_computo_base")
    except HTTPException as exc_auth:
        raise HTTPException(
            exc_auth.status_code,
            f"{messaggio_euristica} Il file non ha una struttura riconoscibile automaticamente: ho provato a "
            f"interpretarlo con l'AI, ma {exc_auth.detail}",
        )
    try:
        voci = interpreta_computo_base_excel(path)
    except AiAssistantError as exc_ai:
        if binario == "crediti":
            accounts_db.aggiungi_crediti(conn, utente["id"], COSTO_CREDITI["ai_interpreta_computo_base"])
        return JSONResponse(status_code=422, content={
            "error": f"{messaggio_euristica} Ho provato a interpretarlo con l'AI ma non ci sono riuscito: {exc_ai}"})
    accounts_db.registra_utilizzo(
        conn, identificativo, "ai_interpreta_computo_base", utente_id=utente["id"] if utente else None,
    )
    return {"voci": voci, "interpretazione_ai": True}


@app.post("/api/confronto/interpreta-preventivo")
async def api_confronto_interpreta_preventivo(
    request: Request,
    file: UploadFile = File(...),
    nome_impresa: str = Form(...),
    voci_json: str = Form(...),
):
    """Seconda fase, ripetuta una volta per ogni impresa caricata: interpreta
    il preventivo ricevuto così com'è (formato libero) e lo abbina alle voci
    del computo base. QUESTO è il passaggio che consuma crediti/quota AI (una
    chiamata per preventivo caricato) — a differenza del resto del confronto,
    che è puro calcolo. Richiede un account connesso con abbonamento attivo
    (entro la quota) o crediti sufficienti (401/402/429, vedi
    _autorizza_azione_ai) e ANTHROPIC_API_KEY configurata sul server (se
    assente, 503 e i crediti eventualmente scalati vengono restituiti). Il
    risultato è SEMPRE da rivedere/correggere in interfaccia prima di passare
    a /api/confronto/scarica, che non consuma nulla."""
    nome_impresa = (nome_impresa or "").strip()
    if not nome_impresa:
        raise HTTPException(400, "Nome impresa mancante.")
    try:
        voci = json.loads(voci_json)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Voci di riferimento non valide: {exc}")
    if not voci:
        raise HTTPException(400, "Nessuna voce di riferimento: carica prima il computo base.")

    path = _save_upload(file)
    conn = accounts_db.get_connection(ACCOUNTS_DB_PATH)
    utente = _utente_sessione(request)
    identificativo = _identificativo_richiesta(request, utente)
    _verifica_limite_ai(conn, identificativo)
    binario = _autorizza_azione_ai(conn, utente, "ai_interpreta_preventivo")
    try:
        risultato = interpreta_preventivo_impresa(voci, nome_impresa, path)
    except AiAssistantError as exc:
        if binario == "crediti":
            accounts_db.aggiungi_crediti(conn, utente["id"], COSTO_CREDITI["ai_interpreta_preventivo"])
        return JSONResponse(status_code=503, content={"error": str(exc)})
    accounts_db.registra_utilizzo(conn, identificativo, "ai_interpreta_preventivo", utente_id=utente["id"])
    return risultato


@app.post("/api/confronto/scarica")
async def api_confronto_scarica(payload: dict = Body(...)):
    """Terza e ultima fase: dalle voci base e dai dati di ciascuna impresa —
    già rivisti/corretti dall'utente in interfaccia — genera il file di
    confronto nel formato richiesto ('excel' o 'pdf'). Pura generazione file:
    nessuna chiamata AI, nessun account richiesto, stesso principio già
    applicato alla generazione del computo (vedi /api/scarica-formato).

    Corpo atteso: {"formato": "excel"|"pdf", "meta": {...}, "voci": [...],
    "imprese": [{"nome": str, "righe": [{"numero", "prezzo_unitario", "nota"}],
    "totale_dichiarato": float|None}]}."""
    formato = payload.get("formato")
    if formato not in ("excel", "pdf"):
        raise HTTPException(400, "formato deve essere 'excel' o 'pdf'.")
    voci = payload.get("voci") or []
    imprese_payload = payload.get("imprese") or []
    meta = payload.get("meta") or {}
    if not voci:
        raise HTTPException(400, "Nessuna voce di computo su cui basare il confronto.")
    if not imprese_payload:
        raise HTTPException(400, "Serve almeno un'impresa da confrontare.")

    imprese: list[ImpresaPreventivo] = []
    for imp in imprese_payload:
        nome = (imp.get("nome") or "").strip()
        if not nome:
            continue
        righe: dict[int, RigaImpresa] = {}
        for r in (imp.get("righe") or []):
            try:
                numero = int(r.get("numero"))
            except (TypeError, ValueError):
                continue
            prezzo = r.get("prezzo_unitario")
            try:
                prezzo = float(prezzo) if prezzo not in (None, "") else None
            except (TypeError, ValueError):
                prezzo = None
            righe[numero] = RigaImpresa(prezzo_unitario=prezzo, nota=(r.get("nota") or ""))
        totale_dichiarato = imp.get("totale_dichiarato")
        try:
            totale_dichiarato = float(totale_dichiarato) if totale_dichiarato not in (None, "") else None
        except (TypeError, ValueError):
            totale_dichiarato = None
        imprese.append(ImpresaPreventivo(nome=nome, righe=righe, totale_dichiarato=totale_dichiarato))
    if not imprese:
        raise HTTPException(400, "Serve almeno un'impresa con un nome valido.")

    try:
        confronto = costruisci_confronto(voci, imprese)
    except ConfrontoPreventiviError as exc:
        raise HTTPException(422, str(exc))

    job_id = uuid.uuid4().hex
    if formato == "excel":
        out_path = str(OUTPUT_DIR / f"{job_id}_confronto_preventivi.xlsx")
        build_confronto_excel(confronto, meta, out_path)
        return FileResponse(
            out_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="confronto_preventivi.xlsx",
        )
    out_path = str(OUTPUT_DIR / f"{job_id}_confronto_preventivi.pdf")
    build_confronto_pdf(confronto, meta, out_path)
    return FileResponse(out_path, media_type="application/pdf", filename="confronto_preventivi.pdf")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Il mount del frontend statico va DOPO tutte le route /api/*: FastAPI verifica
# le route nell'ordine di registrazione, quindi le richieste alle API vengono
# gestite sopra e solo il resto (compreso "/") arriva ai file statici.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
