"""Validazione del PDF caricato: deve essere vettoriale, in scala dichiarata e quotato.

Regola posta dall'utente: se il PDF non è in scala e completo di quote, non è
idoneo al rilievo quantità automatico e va rifiutato con un messaggio chiaro,
invece di procedere con una stima silenziosa.
"""
from __future__ import annotations
import re
from collections import Counter
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


def find_scale_on_page(doc: "fitz.Document", page_number: int) -> int | None:
    """Come find_scale, ma limitato a UNA pagina specifica del documento.

    Serve quando più elaborati con scale diverse sono stati uniti in un solo
    PDF (es. planimetria generale 1:2000 + pianta di progetto 1:100): la
    scala usata per convertire le quote geometriche della pagina della pianta
    deve essere quella dichiarata su QUELLA pagina, non la prima scala
    incontrata scorrendo l'intero documento unito.
    """
    if page_number < 0 or page_number >= doc.page_count:
        return None
    page_spans = []
    d = doc[page_number].get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text:
                    page_spans.append({"text": text})
    return find_scale(page_spans)


STANDARD_SCALES = [1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 400, 500, 1000, 1250, 2000, 2500, 5000]
PT_TO_PAPER_MM = 25.4 / 72.0

# Soglie di confidenza: la scala "quotata" (dedotta dalle quote reali sul disegno)
# sostituisce quella dichiarata nel cartiglio SOLO se il segnale è schiacciante,
# altrimenti si preferisce sempre la scala dichiarata (più prevedibile per l'utente).
MIN_MATCHED_FOR_EMPIRICAL_SCALE = 20
MIN_VOTES_FOR_EMPIRICAL_SCALE = 15
MIN_MAJORITY_RATIO = 1.5


def _snap_to_standard_scale(value: float) -> int:
    return min(STANDARD_SCALES, key=lambda s: abs(s - value))


def detect_empirical_scale_on_page(
    page: "fitz.Page", min_len: float = 15.0, max_dist: float = 25.0
) -> tuple[int | None, int]:
    """Deduce la scala del disegno dalle quote effettivamente scritte sulla pianta,
    invece di fidarsi solo dell'annotazione "SCALA 1:..." nel cartiglio.

    Motivazione: su un cartiglio con più elaborati/riquadri, la scala dichiarata può
    riferirsi a una vista diversa da quella della pianta usata per il rilievo (è
    successo su un progetto reale: cartiglio "SCALA 1:200", pianta disegnata in
    realtà a 1:100). Le piante quotate contengono però numeri (le quote, in cm per
    convenzione italiana) posizionati vicino ai segmenti di misura corrispondenti:
    confrontando la lunghezza reale dichiarata (quota) con la lunghezza disegnata
    (in punti PDF) di ogni segmento vicino si può ricavare empiricamente la scala.

    Ritorna (scala_vincente_o_None, numero_di_coppie_quota-segmento_abbinate).
    La scala è restituita SOLO se il voto è una maggioranza netta e inequivocabile
    (altrimenti None, per non sovrascrivere la scala dichiarata con un falso segnale
    su disegni poco quotati o senza segmenti di misura riconoscibili).
    """
    spans: list[tuple[float, float, float]] = []
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip().replace(" ", "")
                if QUOTE_NUMBER_RE.match(text):
                    val = float(text.replace(",", "."))
                    if 5 <= val <= 3000:
                        x0, y0, x1, y1 = span["bbox"]
                        spans.append((val, (x0 + x1) / 2.0, (y0 + y1) / 2.0))

    segments: list[tuple[float, float, float]] = []  # (cx, cy, length_pt)
    for path in page.get_drawings():
        for item in path.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                length = ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5
                if length >= min_len:
                    segments.append(((p1.x + p2.x) / 2.0, (p1.y + p2.y) / 2.0, length))

    votes: Counter[int] = Counter()
    matched = 0
    for val, cx, cy in spans:
        best_dist = None
        best_len = None
        for sx, sy, length in segments:
            dist = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
            if dist <= max_dist and (best_dist is None or dist < best_dist):
                best_dist, best_len = dist, length
        if best_len:
            matched += 1
            scale_est = (val * 10.0) / (best_len * PT_TO_PAPER_MM)
            votes[_snap_to_standard_scale(scale_est)] += 1

    if matched < MIN_MATCHED_FOR_EMPIRICAL_SCALE or not votes:
        return None, matched
    ranked = votes.most_common(2)
    winner_scale, winner_votes = ranked[0]
    runner_up_votes = ranked[1][1] if len(ranked) > 1 else 0
    if winner_votes < MIN_VOTES_FOR_EMPIRICAL_SCALE:
        return None, matched
    if runner_up_votes > 0 and winner_votes < runner_up_votes * MIN_MAJORITY_RATIO:
        return None, matched
    return winner_scale, matched


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
