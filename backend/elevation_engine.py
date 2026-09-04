"""Rilievo di "bande" di altezza da un prospetto quotato (elevazione), per
poter dare una superficie MISURATA (non stimata) a un rivestimento di
facciata individuato solo visivamente in un render (vedi ai_assistant.py,
analizza_render — l'AI abbina un elemento del render a una di queste bande,
ma non inventa mai i numeri: i numeri vengono SOLO da qui).

Perché è un problema diverso dal rilievo di una pianta (geometry_engine.py):
un prospetto quotato NON riporta quote di lunghezza tra due punti (che vanno
convertite in metri tramite la scala del disegno), ma quote ALTIMETRICHE
assolute rispetto a un riferimento di progetto (es. "±0,00" per il piano di
riferimento, "+3,00" per l'attacco del primo piano, "+9,10" per la linea di
gronda): il valore numerico scritto sul disegno È GIÀ in metri, quindi non
serve conoscere né dedurre la scala per calcolare un dislivello — basta la
differenza tra due quote consecutive. Questo rende il rilievo più robusto
(indipendente da un'eventuale scala dichiarata sbagliata, già riscontrata su
disegni reali in questo progetto), ma introduce un problema nuovo: UNA sola
tavola contiene spesso PIÙ prospetti (est/nord/sud/ovest) affiancati, quindi
le quote vanno raggruppate per vista (per prossimità orizzontale) prima di
essere ordinate in verticale, altrimenti si mischiano quote di prospetti
diversi.

Limiti dichiarati (importanti, da non nascondere all'utente): non tutte le
quote altimetriche di un prospetto riguardano l'edificio (alcune sono quote
di marciapiede/strada/terreno/recinzione) — vengono scartate con un filtro
per parole chiave nel testo vicino, ma il filtro non è infallibile. Su
disegni con poche quote o quote non standard, l'estrazione può non trovare
nessuna banda utilizzabile: in quel caso il chiamante deve prevedere un
fallback (mai inventare un valore)."""
from __future__ import annotations
import re
import fitz

# Quota altimetrica: "±0,00", "+3,00", "-0,20", talvolta senza segno esplicito
# per lo zero ("0,00"). Il separatore decimale è la virgola (convenzione
# italiana): non un numero di quota in cm come nelle piante (QUOTE_NUMBER_RE
# in pdf_validation.py), che non ha segno né virgola.
QUOTA_RE = re.compile(r"^(\±|\+|\-)?\s*(\d{1,2}),(\d{2})$")

# Quote altimetriche che con quasi certezza NON riguardano la facciata
# dell'edificio (marciapiede, strada, confine di proprietà, terreno): se una
# quota ha uno di questi testi entro un raggio ravvicinato, viene scartata.
_KEYWORD_ESCLUSIONE = (
    "STRADA", "TERRENO", "PROPRIET", "RECINZIONE", "MURETTO", "CORDOLO", "MARCIAPIEDE",
)
_RAGGIO_KEYWORD_PT = 90.0  # punti PDF: la didascalia è di solito molto vicina alla quota

# Raggruppamento quote per vista (prospetti diversi affiancati sulla stessa
# tavola): due quote nella stessa vista se la loro distanza orizzontale è
# sotto questa soglia (in punti PDF) rispetto al centro del gruppo più vicino.
_CLUSTER_X_GAP_PT = 250.0

MIN_BANDA_M = 0.15  # sotto questa altezza una "banda" è quasi certamente rumore (due quote troppo vicine)
MAX_BANDA_M = 12.0  # oltre, è quasi certamente un errore di lettura (due quote di viste diverse mischiate)


def _quota_value(sign: str, intero: str, decimale: str) -> float:
    v = float(f"{intero}.{decimale}")
    return -v if sign == "-" else v


def _text_spans(page: "fitz.Page") -> list[dict]:
    spans = []
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text:
                    spans.append({"text": text, "bbox": span["bbox"]})
    return spans


def _bbox_center(bbox):
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _is_near_excluded_keyword(quota_center, spans: list[dict]) -> bool:
    qx, qy = quota_center
    for s in spans:
        if not any(k in s["text"].upper() for k in _KEYWORD_ESCLUSIONE):
            continue
        sx, sy = _bbox_center(s["bbox"])
        if ((sx - qx) ** 2 + (sy - qy) ** 2) ** 0.5 <= _RAGGIO_KEYWORD_PT:
            return True
    return False


def _cluster_by_x(quote: list[dict]) -> list[list[dict]]:
    """Raggruppa le quote per vista (prospetti affiancati): ordina per x e
    separa un nuovo gruppo quando lo scarto orizzontale supera la soglia."""
    if not quote:
        return []
    ordinate = sorted(quote, key=lambda q: q["x"])
    gruppi: list[list[dict]] = [[ordinate[0]]]
    for q in ordinate[1:]:
        if q["x"] - gruppi[-1][-1]["x"] > _CLUSTER_X_GAP_PT:
            gruppi.append([q])
        else:
            gruppi[-1].append(q)
    return gruppi


def _bande_da_gruppo(gruppo: list[dict]) -> list[dict]:
    """Da un gruppo di quote della STESSA vista, ordinate per altezza sulla
    pagina (y crescente verso il basso in PDF, quindi y decrescente = più in
    alto = quota più alta), calcola le bande tra valori consecutivi DISTINTI."""
    # una quota può comparire più volte con lo stesso valore (es. ripetuta su
    # entrambi i lati del disegno): si tiene una sola occorrenza per valore
    per_valore: dict[float, dict] = {}
    for q in gruppo:
        v = q["valore"]
        if v not in per_valore or q["y"] < per_valore[v]["y"]:
            per_valore[v] = q
    quote_uniche = sorted(per_valore.values(), key=lambda q: -q["valore"])  # dal più alto al più basso
    bande = []
    for a, b in zip(quote_uniche, quote_uniche[1:]):
        altezza = round(a["valore"] - b["valore"], 2)
        if MIN_BANDA_M <= altezza <= MAX_BANDA_M:
            bande.append({"da_m": b["valore"], "a_m": a["valore"], "altezza_m": altezza})
    return bande


def extract_elevation_bands(doc: "fitz.Document") -> list[dict]:
    """Estrae, da OGNI pagina del documento (un prospetto quotato può essere
    caricato come più pagine/viste separate), le bande di altezza misurabili
    tra quote altimetriche consecutive. Ritorna una lista di viste:
    [{"pagina": 0, "quote_totali": 7, "quote_scartate": 2, "bande": [...]}, ...]
    con una voce per ogni gruppo di quote ravvicinate orizzontalmente
    (presunta singola vista/prospetto) che ha prodotto almeno una banda
    valida. Lista vuota se non è stato possibile individuare nessuna banda
    affidabile — il chiamante deve trattarlo come "nessun dato", mai
    inventare un valore per compensare."""
    viste: list[dict] = []
    for page in doc:
        spans = _text_spans(page)
        quote: list[dict] = []
        scartate = 0
        for s in spans:
            m = QUOTA_RE.match(s["text"].replace(" ", ""))
            if not m:
                continue
            valore = _quota_value(m.group(1) or "", m.group(2), m.group(3))
            cx, cy = _bbox_center(s["bbox"])
            if _is_near_excluded_keyword((cx, cy), spans):
                scartate += 1
                continue
            quote.append({"valore": valore, "x": cx, "y": cy})
        if not quote:
            continue
        for gruppo in _cluster_by_x(quote):
            bande = _bande_da_gruppo(gruppo)
            if bande:
                viste.append({
                    "pagina": page.number,
                    "quote_totali": len(gruppo),
                    "quote_scartate": scartate,
                    "bande": bande,
                })
    return viste
