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
import io
import json
import os
import secrets
import shutil
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path

import fitz
from fastapi import FastAPI, UploadFile, File, Form, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .models import ProjectMeta, RoomQuantity, OpeningQuantity, TaggedElement, RoomComparison, ComputoVoce
from .pipeline import (
    validate_only, questions_for_project, extract_quantities, build_from_quantities,
    compute_voci, build_files_from_voci,
)
from .prezzario import db as prezzario_db
from .intake import required_documents, TIPI_INTERVENTO
from .parametri_engine import PARAMETRI
from .legge10_engine import extract_stratigrafie_reference
from .acustica_engine import extract_acustica_reference
from .ai_assistant import interpreta_istruzione, AiAssistantError

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
# In produzione punta DATA_DIR a un volume persistente (vedi docker-compose.yml):
# senza persistenza, il database dei prezzari caricati e i job vengono persi a ogni riavvio.
DATA_DIR = Path(os.environ.get("COMPUTO_DATA_DIR", BASE_DIR / "data"))
DB_PATH = str(DATA_DIR / "prezzari" / "prezzari.db")
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.environ.get("COMPUTO_MAX_UPLOAD_MB", "50")) * 1024 * 1024

app = FastAPI(title="Computo Metrico Automatico")
# CORS permissivo perché in questa versione non ci sono ancora account utente:
# da restringere alle origini reali quando si introduce l'autenticazione.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

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


def _save_upload(file: UploadFile) -> str:
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    size = 0
    with dest.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File troppo grande (limite {MAX_UPLOAD_BYTES // (1024*1024)} MB).")
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
    return {"prezzario_id": pid, "voci_importate": len(rows)}


@app.post("/api/estrai-vani")
async def api_estrai_vani(
    tipo_intervento: str = Form(...),
    file_progetto: list[UploadFile] = File(...),
    file_stato_di_fatto: list[UploadFile] = File(default=[]),
    file_strutturale: list[UploadFile] = File(default=[]),
    file_copertura: list[UploadFile] = File(default=[]),
    file_legge10: list[UploadFile] = File(default=[]),
    file_acustica: list[UploadFile] = File(default=[]),
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

    if not progetto_paths:
        return JSONResponse(status_code=422, content={
            "error": "Carica almeno un elaborato per la pianta di progetto."})

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
    )

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


@app.post("/api/generate")
async def api_generate(
    tipo_intervento: str = Form(...),
    voci_json: str = Form(...),
    nome_progetto: str = Form("Progetto senza nome"),
    committente: str = Form(""),
    ubicazione: str = Form(""),
    prezzario_nome: str = Form("Prezzario di esempio (placeholder, non ufficiale)"),
    confronto_json: str = Form("[]"),
    note_metodologiche_json: str = Form("[]"),
    validation_messages_json: str = Form("[]"),
):
    """Terza fase: dalle righe di computo calcolate da /api/calcola-voci ed
    EVENTUALMENTE corrette/commentate a mano dall'utente nel browser, ai file
    finali (Excel, PriMus, Word). Non ricalcola nulla: usa esattamente le
    righe ricevute, così le correzioni dell'utente sono quelle che finiscono
    nei file scaricati."""
    if tipo_intervento not in TIPI_INTERVENTO:
        raise HTTPException(400, f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")

    try:
        voci = [ComputoVoce(**v) for v in json.loads(voci_json)]
        confronto = [RoomComparison(**c) for c in json.loads(confronto_json)]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Dati del computo non validi: {exc}")

    if not voci:
        return JSONResponse(status_code=422, content={
            "error": "Il computo non contiene nessuna voce da generare: torna al passaggio precedente."})

    note_metodologiche = json.loads(note_metodologiche_json)
    validation_messages = json.loads(validation_messages_json)
    meta = ProjectMeta(nome_progetto=nome_progetto, committente=committente, ubicazione=ubicazione,
                        prezzario_nome=prezzario_nome, tipo_intervento=tipo_intervento)

    job_id = uuid.uuid4().hex
    excel_out = str(OUTPUT_DIR / f"{job_id}_computo.xlsx")
    primus_out = str(OUTPUT_DIR / f"{job_id}_elenco_prezzi_primus.xlsx")
    word_out = str(OUTPUT_DIR / f"{job_id}_computo.docx")

    build_files_from_voci(
        voci=voci, meta=meta, note_metodologiche=note_metodologiche,
        validation_messages=validation_messages, confronto=confronto,
        excel_out=excel_out, primus_out=primus_out, word_out=word_out,
    )

    zip_path = str(OUTPUT_DIR / f"{job_id}_computo.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(excel_out, arcname="computo_metrico.xlsx")
        zf.write(primus_out, arcname="elenco_prezzi_per_primus.xlsx")
        zf.write(word_out, arcname="relazione_computo.docx")

    return FileResponse(zip_path, media_type="application/zip",
                         filename="computo_metrico_estimativo.zip")


@app.post("/api/interpreta-commento")
async def api_interpreta_commento(payload: dict = Body(...)):
    """Interpreta un'istruzione scritta liberamente dall'utente nella colonna
    "Commento" di una riga di computo (nel passaggio di revisione, prima del
    download) e restituisce come applicarla: modifica dei valori della riga,
    eliminazione della riga, oppure nessuna modifica con una spiegazione.
    Non tocca né il file né le altre righe: il frontend applica il risultato
    solo alla riga da cui è partita l'istruzione.

    Corpo atteso: {"voce": {...campi della riga...}, "istruzione": "testo"}.
    Richiede ANTHROPIC_API_KEY configurata sul server: se assente risponde
    503 con un messaggio chiaro invece di applicare una modifica finta."""
    voce = payload.get("voce") or {}
    istruzione = (payload.get("istruzione") or "").strip()
    if not istruzione:
        raise HTTPException(400, "Istruzione vuota.")
    try:
        risultato = interpreta_istruzione(voce, istruzione)
    except AiAssistantError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    return risultato


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Il mount del frontend statico va DOPO tutte le route /api/*: FastAPI verifica
# le route nell'ordine di registrazione, quindi le richieste alle API vengono
# gestite sopra e solo il resto (compreso "/") arriva ai file statici.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
