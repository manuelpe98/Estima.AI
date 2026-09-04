"""Lettura di riferimento della relazione tecnica descrittiva dell'intervento
(il documento in cui il progettista descrive a parole cosa prevede il
progetto: tipo di intervento, struttura, materiali principali, finiture,
eventuali apprestamenti di cantiere).

Caricarla è OBBLIGATORIO (richiesta esplicita dell'utente): serve a dare al
sistema — e a chiunque riveda il computo — un riferimento testuale su cosa
il progetto prevede realmente, al di là di quello che si può dedurre dalla
sola pianta quotata. Vale la stessa nota di cautela già fatta per
legge10_engine.py e acustica_engine.py: NON si tenta di interpretare o
strutturare automaticamente il contenuto (nessuna risposta alle domande di
capitolato viene dedotta da qui, per evitare di dare per "confermato" un
requisito solo perché il termine compare nel testo). Il testo estratto è
mostrato integralmente come riferimento di lettura per l'utente.
"""
from __future__ import annotations
import fitz

MAX_CARATTERI_TESTO = 20000


def extract_relazione_tecnica(pdf_paths: list[str]) -> dict:
    """Estrae il testo integrale (fino a un limite) dei PDF forniti, per essere
    mostrato come riferimento di lettura. Ritorna sempre una struttura valida
    anche se non si trova nulla (es. PDF scansionato senza testo)."""
    all_text_parts: list[str] = []
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
            else:
                all_text_parts.append(text.strip())
        doc.close()

    testo_completo = "\n\n".join(all_text_parts)
    troncato = len(testo_completo) > MAX_CARATTERI_TESTO
    if troncato:
        testo_completo = testo_completo[:MAX_CARATTERI_TESTO]

    note = []
    if pagine_totali == 0:
        note.append("La relazione tecnica caricata non è stata letta (formato non valido o vuoto).")
    elif pagine_senza_testo == pagine_totali:
        note.append(
            "Il documento della relazione tecnica caricato non contiene testo estraibile (probabilmente una "
            "scansione/immagine): non è stato possibile mostrarne il contenuto come riferimento testuale. "
            "Consulta il documento originale a parte."
        )
    elif troncato:
        note.append(
            f"Il testo della relazione tecnica è stato troncato ai primi {MAX_CARATTERI_TESTO} caratteri per "
            "la sola visualizzazione di riferimento: il documento originale caricato è comunque completo."
        )

    return {
        "testo": testo_completo,
        "note": note,
    }
