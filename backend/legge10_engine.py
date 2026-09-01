"""Lettura di riferimento della relazione tecnica ex Legge 10/91 (oggi, di
norma, relazione ex D.Lgs 192/2005 e s.m.i. / DM Requisiti Minimi — il nome
"Legge 10/91" resta quello d'uso comune tra i tecnici): contiene le
stratigrafie di murature, solai e copertura (materiali, spessori,
trasmittanza) che il computo deve riprendere per le voci di struttura e
involucro.

NOTA IMPORTANTE sui limiti di questa estrazione: questi documenti vengono
prodotti da software di calcolo energetico molto diversi tra loro (Termolog,
Docet, Edilclima, MC4, ecc.) con impaginazioni delle tabelle di stratigrafia
non standardizzate, e spesso sono PDF non vettoriali (stampe/scansioni) dove
il testo potrebbe non essere estraibile affatto. Per questo NON si tenta un
parsing strutturato affidabile "layer per layer" (rischierebbe di produrre
numeri sbagliati presentati come certi): si estrae invece il testo grezzo dei
blocchi che sembrano pertinenti (contengono una parola chiave di stratigrafia)
come RIFERIMENTO per l'utente, e si prova — solo come suggerimento facoltativo,
sempre da confermare — a riconoscere uno spessore complessivo dichiarato per
parete esterna, solaio e copertura con un'espressione regolare mirata."""
from __future__ import annotations
import re
import fitz

STRAT_KEYWORDS = [
    "STRATIGRAFIA", "PARETE", "MURATURA", "SOLAIO", "COPERTURA", "TETTO",
    "SPESSORE", "TRASMITTANZA", "TAMPONAMENTO",
]

_THICKNESS_RE = re.compile(
    r"spessore\s*(?:complessivo|totale)?\s*[:\-]?\s*(\d+[.,]?\d*)\s*(cm|mm)",
    re.IGNORECASE,
)

_CATEGORIA_HINTS = {
    "parete_esterna": ["PARETE ESTERNA", "PARETE PERIMETRALE", "MURATURA ESTERNA", "TAMPONAMENTO"],
    "solaio": ["SOLAIO"],
    "copertura": ["COPERTURA", "TETTO"],
}

MAX_BLOCCHI_RIFERIMENTO = 40


def extract_stratigrafie_reference(pdf_paths: list[str]) -> dict:
    """Estrae dai PDF forniti i blocchi di testo utili come riferimento sulle
    stratigrafie e, dove riconoscibile, uno spessore complessivo per
    parete esterna / solaio / copertura. Ritorna sempre una struttura valida
    anche se non si trova nulla (es. PDF scansionato senza testo)."""
    all_lines: list[str] = []
    pagine_senza_testo = 0
    pagine_totali = 0
    for path in pdf_paths:
        try:
            doc = fitz.open(path)
        except Exception:
            continue
        for page in doc:
            pagine_totali += 1
            text = page.get_text()
            if not text.strip():
                pagine_senza_testo += 1
            all_lines.extend(text.splitlines())
        doc.close()

    relevant: list[str] = []
    for i, line in enumerate(all_lines):
        upper = line.upper()
        if any(k in upper for k in STRAT_KEYWORDS):
            start = max(0, i - 1)
            end = min(len(all_lines), i + 3)
            block = "\n".join(l.strip() for l in all_lines[start:end] if l.strip())
            if block and block not in relevant:
                relevant.append(block)
            if len(relevant) >= MAX_BLOCCHI_RIFERIMENTO:
                break

    # La riga con l'hint di categoria (es. "STRATIGRAFIA PARETE ESTERNA") e la
    # riga con lo spessore complessivo dichiarato sono quasi sempre su righe
    # DIVERSE nel documento originale (una tabella o un elenco di strati):
    # si cerca quindi lo spessore in una finestra di righe successive
    # all'hint, non sulla stessa riga.
    _WINDOW = 20
    spessori_cm: dict[str, float] = {}
    for categoria, hints in _CATEGORIA_HINTS.items():
        for i, line in enumerate(all_lines):
            upper = line.upper()
            if not any(h in upper for h in hints):
                continue
            window = all_lines[i:i + _WINDOW]
            for wline in window:
                m = _THICKNESS_RE.search(wline)
                if m:
                    val = float(m.group(1).replace(",", "."))
                    if m.group(2).lower() == "mm":
                        val /= 10.0
                    spessori_cm.setdefault(categoria, round(val, 1))
                    break
            if categoria in spessori_cm:
                break

    note = []
    if pagine_totali == 0:
        note.append("Il file caricato per la Legge 10/91 non è stato letto (formato non valido o vuoto).")
    elif pagine_senza_testo == pagine_totali:
        note.append(
            "Il documento Legge 10/91 caricato non contiene testo estraibile (probabilmente una scansione/immagine): "
            "non è stato possibile leggere le stratigrafie automaticamente. Consulta il documento a parte per "
            "compilare correttamente le stratigrafie di murature, solai e copertura."
        )
    elif not relevant:
        note.append(
            "Nel documento Legge 10/91 caricato non sono stati trovati riferimenti riconoscibili a stratigrafie di "
            "murature, solai o copertura: verifica manualmente il documento per gli spessori da inserire."
        )

    return {
        "testo_riferimento": relevant,
        "spessori_rilevati_cm": spessori_cm,
        "note": note,
    }
