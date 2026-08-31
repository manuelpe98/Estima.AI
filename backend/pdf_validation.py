"""Validazione del PDF caricato: deve essere vettoriale, in scala dichiarata e quotato.

Regola posta dall'utente: se il PDF non è in scala e completo di quote, non è
idoneo al rilievo quantità automatico e va rifiutato con un messaggio chiaro,
invece di procedere con una stima silenziosa.
"""
from __future__ import annotations
import re
import fitz  # PyMuPDF
from .models import ValidationResult

SCALE_PATTERNS = [
    re.compile(r"SCALA\s*1\s*[:\.]\s*(\d+)", re.IGNORECASE),
    re.compile(r"\bSC\.?\s*1\s*[:\.]\s*(\d+)", re.IGNORECASE),
    re.compile(r"\b1\s*:\s*(\d{2,4})\b"),
]

# Etichette numeriche plausibili come quote in cm su una pianta domestica/edilizia
QUOTE_NUMBER_RE = re.compile(r"^\d{2,4}([.,]\d{1,2})?$")
MIN_QUOTE_COUNT_FOR_VALID = 6


def _all_text_spans(doc: "fitz.Document") -> list[dict]:
    spans = []
    for page in doc:
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    spans.append({
                        "text": span["text"].strip(),
                        "bbox": span["bbox"],
                        "page": page.number,
                    })
    return spans


def find_scale(spans: list[dict]) -> int | None:
    for sp in spans:
        for pattern in SCALE_PATTERNS:
            m = pattern.search(sp["text"])
            if m:
                try:
                    val = int(m.group(1))
                    if 1 < val <= 5000:
                        return val
                except ValueError:
                    continue
    return None


def count_quote_numbers(spans: list[dict]) -> int:
    count = 0
    for sp in spans:
        txt = sp["text"].replace(" ", "")
        if QUOTE_NUMBER_RE.match(txt):
            val = float(txt.replace(",", "."))
            if 5 <= val <= 3000:  # range plausibile di quote in cm
                count += 1
    return count


def has_vector_content(doc: "fitz.Document") -> bool:
    for page in doc:
        drawings = page.get_drawings()
        if len(drawings) > 3:
            return True
    return False


def validate_pdf(path: str) -> ValidationResult:
    messages: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # file corrotto o non è un PDF
        return ValidationResult(
            is_valid=False, is_vector_pdf=False, scale_denominator=None,
            quote_count=0, messages=[f"Impossibile aprire il file: {exc}"],
        )

    is_vector = has_vector_content(doc)
    spans = _all_text_spans(doc)
    scale = find_scale(spans)
    quote_count = count_quote_numbers(spans)

    if not is_vector:
        messages.append(
            "Il PDF non sembra contenere geometrie vettoriali (potrebbe essere una "
            "scansione raster): il rilievo automatico delle quantità non è affidabile."
        )
    if scale is None:
        messages.append(
            "Non è stata trovata una scala metrica dichiarata nel disegno "
            "(es. 'SCALA 1:100'). Carica un elaborato con la scala indicata."
        )
    if quote_count < MIN_QUOTE_COUNT_FOR_VALID:
        messages.append(
            f"Sono state trovate solo {quote_count} quote leggibili sul disegno "
            f"(minimo richiesto: {MIN_QUOTE_COUNT_FOR_VALID}). Il disegno deve essere "
            "completo di quote per un rilievo affidabile."
        )

    is_valid = is_vector and scale is not None and quote_count >= MIN_QUOTE_COUNT_FOR_VALID
    if is_valid:
        messages.append(f"PDF conforme: vettoriale, scala 1:{scale}, {quote_count} quote rilevate.")

    doc.close()
    return ValidationResult(
        is_valid=is_valid, is_vector_pdf=is_vector, scale_denominator=scale,
        quote_count=quote_count, messages=messages,
    )
