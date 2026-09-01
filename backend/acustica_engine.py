"""Lettura di riferimento della relazione di valutazione/previsione di impatto
acustico (o relazione sui requisiti acustici passivi, D.P.C.M. 5/12/1997):
serve a segnalare materiali e lavorazioni specifiche per l'isolamento acustico
(es. pannelli fonoisolanti, materassini anticalpestio, bande desolidarizzanti)
che il computo generato dalla sola pianta architettonica non può altrimenti
sapere che servono.

Vale la stessa nota di cautela già fatta per legge10_engine.py: questi
documenti hanno impaginazioni molto diverse tra loro e a volte sono PDF non
vettoriali (scansioni) senza testo estraibile. Per questo NON si tenta di
dedurre quantità o prezzi dal testo: si riconoscono solo MENZIONI di
materiali/prodotti acustici tipici (con il testo di contesto in cui compaiono,
come riferimento), che l'utente può scegliere di trasformare in una voce
segnaposto del computo (quantità e prezzo sempre da completare a mano — non è
possibile risalire da un testo descrittivo a una quantità reale)."""
from __future__ import annotations
import fitz

STRAT_KEYWORDS = [
    "ACUSTIC", "FONOISOLANTE", "FONOASSORBENTE", "ISOLAMENTO ACUSTICO", "REQUISITI ACUSTICI",
    "CALPESTIO", "RUMORE", "D.P.C.M", "DPCM",
]

MAX_BLOCCHI_RIFERIMENTO = 40

# Materiali/prodotti tipici per l'isolamento acustico: se il testo li nomina,
# vale la pena segnalarli come possibile voce aggiuntiva del computo — non
# perché siano CERTAMENTE necessari in questo progetto, ma perché comparire
# nella relazione acustica è un segnale che il progettista li ha previsti.
_MATERIALI_HINTS: dict[str, list[str]] = {
    "Pannello/materassino fonoisolante (pareti/contropareti)": [
        "PANNELLO FONOISOLANTE", "MATERASSINO FONOISOLANTE", "LANA MINERALE FONOISOLANTE",
        "MASSA MOLLA MASSA", "MASSA-MOLLA-MASSA",
    ],
    "Membrana/materassino anticalpestio (sotto massetto)": [
        "ANTICALPESTIO", "MATERASSINO ACUSTICO", "TAPPETINO ACUSTICO", "ISOLAMENTO AL CALPESTIO",
    ],
    "Banda/nastro desolidarizzante perimetrale": [
        "BANDA DESOLIDARIZZANTE", "BANDA PERIMETRALE", "NASTRO DESOLIDARIZZANTE", "GIUNTO DESOLIDARIZZANTE",
    ],
    "Massetto galleggiante": [
        "MASSETTO GALLEGGIANTE", "PAVIMENTO GALLEGGIANTE",
    ],
    "Serramenti/vetrocamera con prestazione acustica maggiorata": [
        "VETRO ACUSTICO", "VETROCAMERA ACUSTIC", "SERRAMENTO ACUSTIC", "ABBATTIMENTO ACUSTICO SERRAMENTI",
    ],
    "Porte con prestazione acustica maggiorata": [
        "PORTA ACUSTICA", "PORTA FONOISOLANTE", "REI ACUSTIC",
    ],
    "Cassonetti/tapparelle insonorizzati": [
        "CASSONETTO ACUSTICO", "CASSONETTO INSONORIZZATO", "CASSONETTO COIBENTATO",
    ],
}


def extract_acustica_reference(pdf_paths: list[str]) -> dict:
    """Estrae dai PDF forniti i blocchi di testo utili come riferimento sui
    requisiti acustici e le menzioni di materiali/prodotti acustici tipici.
    Ritorna sempre una struttura valida anche se non si trova nulla (es. PDF
    scansionato senza testo)."""
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

    full_text_upper = "\n".join(all_lines).upper()

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

    materiali_rilevati: list[dict] = []
    for materiale, hints in _MATERIALI_HINTS.items():
        for i, line in enumerate(all_lines):
            upper = line.upper()
            match = next((h for h in hints if h in upper), None)
            if not match:
                continue
            start = max(0, i - 1)
            end = min(len(all_lines), i + 2)
            contesto = " / ".join(l.strip() for l in all_lines[start:end] if l.strip())
            materiali_rilevati.append({"materiale": materiale, "contesto": contesto[:300]})
            break  # una sola segnalazione per materiale, con il primo contesto trovato

    note = []
    if pagine_totali == 0:
        note.append("Il file caricato per la relazione acustica non è stato letto (formato non valido o vuoto).")
    elif pagine_senza_testo == pagine_totali:
        note.append(
            "Il documento della relazione acustica caricato non contiene testo estraibile (probabilmente una "
            "scansione/immagine): non è stato possibile individuare automaticamente i materiali citati. "
            "Consulta il documento a parte per le lavorazioni/materiali acustici da aggiungere al computo."
        )
    elif not relevant:
        note.append(
            "Nel documento caricato non sono stati trovati riferimenti riconoscibili a requisiti o materiali "
            "acustici: verifica manualmente il documento."
        )
    elif not materiali_rilevati:
        note.append(
            "Sono stati trovati passaggi relativi ai requisiti acustici, ma nessun materiale/prodotto tipico "
            "riconosciuto tra quelli cercati automaticamente: consulta i passaggi individuati qui sotto e "
            "aggiungi a mano le voci di computo eventualmente necessarie."
        )

    return {
        "testo_riferimento": relevant,
        "materiali_rilevati": materiali_rilevati,
        "note": note,
    }
