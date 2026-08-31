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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .models import ProjectMeta
from .pipeline import validate_only, questions_for_project, run_pipeline
from .prezzario import db as prezzario_db
from .intake import required_documents, TIPI_INTERVENTO
from .parametri_engine import PARAMETRI

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


@app.post("/api/generate")
async def api_generate(
    tipo_intervento: str = Form(...),
    file_progetto: UploadFile = File(...),
    file_stato_di_fatto: UploadFile | None = File(None),
    file_strutturale: UploadFile | None = File(None),
    file_copertura: UploadFile | None = File(None),
    nome_progetto: str = Form("Progetto senza nome"),
    committente: str = Form(""),
    ubicazione: str = Form(""),
    capitolato_text: str | None = Form(None),
    answers_json: str = Form("{}"),
    parametri_json: str = Form("{}"),
    prezzario_id: int | None = Form(None),
    legend_page: int = Form(1),
    structural_legend_page: int = Form(1),
):
    if tipo_intervento not in TIPI_INTERVENTO:
        raise HTTPException(400, f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")

    pdf_progetto_path = _save_upload(file_progetto)
    pdf_sdf_path = _save_upload(file_stato_di_fatto) if file_stato_di_fatto else None
    pdf_strut_path = _save_upload(file_strutturale) if file_strutturale else None
    pdf_cop_path = _save_upload(file_copertura) if file_copertura else None

    if tipo_intervento == "ristrutturazione" and not pdf_sdf_path:
        return JSONResponse(status_code=422, content={
            "error": "Per una ristrutturazione è obbligatorio caricare anche la pianta dello stato di fatto."})

    answers = json.loads(answers_json)
    parametri_overrides = json.loads(parametri_json)
    meta = ProjectMeta(nome_progetto=nome_progetto, committente=committente, ubicazione=ubicazione)

    job_id = uuid.uuid4().hex
    excel_out = str(OUTPUT_DIR / f"{job_id}_computo.xlsx")
    primus_out = str(OUTPUT_DIR / f"{job_id}_elenco_prezzi_primus.xlsx")
    word_out = str(OUTPUT_DIR / f"{job_id}_computo.docx")

    result = run_pipeline(
        tipo_intervento=tipo_intervento,
        pdf_progetto_path=pdf_progetto_path,
        db_path=DB_PATH, meta=meta, answers=answers, parametri_overrides=parametri_overrides,
        pdf_stato_di_fatto_path=pdf_sdf_path, pdf_strutturale_path=pdf_strut_path,
        pdf_copertura_path=pdf_cop_path, capitolato_text=capitolato_text, prezzario_id=prezzario_id,
        legend_page=legend_page, structural_legend_page=structural_legend_page,
        excel_out=excel_out, primus_out=primus_out, word_out=word_out,
    )

    if not result.ok:
        messages = list(result.errors)
        for v in result.validations.values():
            messages.extend(v.messages)
        return JSONResponse(status_code=422, content={
            "error": "Uno o più elaborati non sono conformi ai requisiti (scala/quote/vettorialità).",
            "messages": messages,
        })

    zip_path = str(OUTPUT_DIR / f"{job_id}_computo.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(excel_out, arcname="computo_metrico.xlsx")
        zf.write(primus_out, arcname="elenco_prezzi_per_primus.xlsx")
        zf.write(word_out, arcname="relazione_computo.docx")

    return FileResponse(zip_path, media_type="application/zip",
                         filename="computo_metrico_estimativo.zip")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Il mount del frontend statico va DOPO tutte le route /api/*: FastAPI verifica
# le route nell'ordine di registrazione, quindi le richieste alle API vengono
# gestite sopra e solo il resto (compreso "/") arriva ai file statici.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
