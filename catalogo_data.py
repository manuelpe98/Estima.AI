"""Catalogo completo del Prezzario Regionale delle Opere Pubbliche 2022 di
Regione Lombardia (35.063 articoli ufficiali), estratto dai 4 PDF caricati da
Franco. A differenza del prezzario di riferimento curato in `seed_data.py`
(una selezione di poche decine di voci usata per il matching automatico),
questo è l'intero catalogo ufficiale, tenuto SOLO per la consultazione in
sola lettura (vedi `db.search_catalog`): non viene mai usato per il matching
automatico delle voci di computo, né compare tra i prezzari selezionabili.

I dati sono salvati compressi (gzip) accanto a questo file per tenere il
repository leggero: circa 0,7 MB invece di oltre 5 MB in chiaro.
"""
from __future__ import annotations
import gzip
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "catalogo_lombardia_2022.json.gz"

CATALOG_META = {
    "regione": "Lombardia",
    "anno": 2022,
    "nome": "Prezzario Regione Lombardia 2022 (catalogo completo, sola consultazione)",
}

# Da cambiare manualmente solo se in futuro il file dati viene rigenerato/aggiornato:
# permette a ensure_catalog_seed di accorgersi che il contenuto è cambiato e
# riallineare il database (stesso meccanismo di PLACEHOLDER_SEED_VERSION).
CATALOG_VERSION = "lombardia-2022-completo-v1"


CATEGORIA_CATALOGO = "Prezzario Lombardia 2022 (catalogo completo)"


def load_catalog_rows() -> list[dict]:
    """Carica le righe del catalogo dal file compresso, nel formato atteso da
    db.ensure_catalog_seed (categoria, sotto_tipo, codice, descrizione, um,
    prezzo). Il volume di provenienza (es. "Vol. 1.1") viene riportato nel
    campo sotto_tipo, riusato qui solo come filtro di consultazione — non ha
    alcun ruolo nel matching automatico per questo prezzario, che ne è escluso.

    Solleva FileNotFoundError se il file dati non è presente: in tal caso la
    consultazione del catalogo semplicemente non sarà disponibile, ma tutto
    il resto del sito continua a funzionare — vedi il try/except in main.py."""
    with gzip.open(DATA_PATH, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        {
            "categoria": CATEGORIA_CATALOGO,
            "sotto_tipo": r.get("vol", ""),
            "codice": r.get("codice", ""),
            "descrizione": r.get("descrizione", ""),
            "um": r.get("um", ""),
            "prezzo": r.get("prezzo", 0.0),
        }
        for r in raw
    ]
