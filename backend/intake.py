"""Prima domanda del flusso (nuova costruzione o ristrutturazione) e
checklist dei documenti obbligatori conseguente, come richiesto: il computo
deve comprendere tutte le opere (anche strutture, scavi, coperture), quindi
servono anche prospetti/sezioni architettoniche e piante/sezioni strutturali,
non solo la pianta quotata."""
from __future__ import annotations
from dataclasses import dataclass

TIPI_INTERVENTO = ["nuova_costruzione", "ristrutturazione"]


@dataclass
class RequiredDocument:
    id: str
    label: str
    obbligatorio: bool
    note: str = ""


def required_documents(tipo_intervento: str) -> list[RequiredDocument]:
    if tipo_intervento not in TIPI_INTERVENTO:
        raise ValueError(f"tipo_intervento deve essere uno tra {TIPI_INTERVENTO}")

    if tipo_intervento == "nuova_costruzione":
        return [
            RequiredDocument("pianta_progetto", "Pianta quotata in scala (stato di progetto)", True),
            RequiredDocument("prospetti", "Prospetti architettonici quotati", True,
                              "Necessari per serramenti esterni e per un futuro calcolo delle facciate"),
            RequiredDocument("sezioni_arch", "Sezioni architettoniche quotate", True,
                              "Necessarie per altezze interne, coperture e scavi"),
            RequiredDocument("piante_strutturali", "Piante strutturali (pilastri/travi) con abaco", True,
                              "Necessarie per il computo delle strutture in elevazione"),
            RequiredDocument("sezioni_strutturali", "Sezioni strutturali quotate", True,
                              "Necessarie per profondità di fondazione e altezze di piano strutturali"),
            RequiredDocument("relazione_tecnica", "Relazione tecnica descrittiva dell'intervento", True,
                              "Descrive a parole cosa prevede il progetto (tipo di intervento, struttura, "
                              "materiali, finiture, eventuali apprestamenti di cantiere): il testo viene mostrato "
                              "come riferimento di lettura, non interpretato/strutturato automaticamente"),
            RequiredDocument("relazione_capitolato", "Capitolato materiali e finiture", False,
                              "Se assente, il sistema chiede materiali e finiture con un questionario"),
            RequiredDocument("relazione_legge10", "Relazione tecnica ex Legge 10/91 (o D.Lgs 192/2005 e s.m.i.)", False,
                              "Contiene le stratigrafie di murature, solai e copertura: usata come riferimento "
                              "per gli spessori da inserire nel computo, se presenti in modo riconoscibile"),
            RequiredDocument("relazione_acustica", "Relazione di previsione/valutazione di impatto acustico", False,
                              "Usata come riferimento per segnalare materiali/lavorazioni per l'isolamento acustico"),
            RequiredDocument("render", "Render o immagini fotorealistiche del progetto (se disponibili)", False,
                              "Un'AI osserva le immagini caricate e descrive materiali/elementi visibili con "
                              "impatto sul computo (rivestimenti di facciata, parapetti, infissi, pavimentazioni "
                              "esterne) come riferimento qualitativo: non calcola mai quantità o prezzi da sola, "
                              "e non modifica il computo automaticamente"),
            RequiredDocument("modello_3d", "Modello 3D — SketchUp (.skp), Revit (.rvt/.rfa) o Rhino (.3dm) "
                              "(se esistente)", False,
                              "Allegato come riferimento per la consultazione manuale: il sistema NON legge la "
                              "geometria di questi formati proprietari in questa versione (nessun rilievo o "
                              "verifica automatica basata sul modello)"),
        ]

    # ristrutturazione
    return [
        RequiredDocument("pianta_stato_di_fatto", "Pianta quotata dello STATO DI FATTO", True,
                          "Serve per il confronto con il progetto e per le demolizioni"),
        RequiredDocument("pianta_progetto", "Pianta quotata dello STATO DI PROGETTO", True),
        RequiredDocument("prospetti", "Prospetti architettonici quotati (stato di fatto e di progetto)", True),
        RequiredDocument("sezioni_arch", "Sezioni architettoniche quotate (stato di fatto e di progetto)", True),
        RequiredDocument("piante_strutturali", "Piante strutturali con abaco (se previste modifiche strutturali)", False,
                          "Obbligatoria solo se l'intervento modifica elementi strutturali"),
        RequiredDocument("sezioni_strutturali", "Sezioni strutturali quotate (se previste modifiche strutturali)", False),
        RequiredDocument("relazione_tecnica", "Relazione tecnica descrittiva dell'intervento", True,
                          "Descrive a parole cosa prevede il progetto (tipo di intervento, struttura, materiali, "
                          "finiture, eventuali apprestamenti di cantiere): il testo viene mostrato come "
                          "riferimento di lettura, non interpretato/strutturato automaticamente"),
        RequiredDocument("relazione_capitolato", "Capitolato materiali e finiture", False,
                          "Se assente, il sistema chiede materiali e finiture con un questionario"),
        RequiredDocument("relazione_legge10", "Relazione tecnica ex Legge 10/91 (o D.Lgs 192/2005 e s.m.i.)", False,
                          "Contiene le stratigrafie di murature, solai e copertura: usata come riferimento "
                          "per gli spessori da inserire nel computo, se presenti in modo riconoscibile"),
        RequiredDocument("relazione_acustica", "Relazione di previsione/valutazione di impatto acustico", False,
                          "Usata come riferimento per segnalare materiali/lavorazioni per l'isolamento acustico"),
        RequiredDocument("render", "Render o immagini fotorealistiche del progetto (se disponibili)", False,
                          "Un'AI osserva le immagini caricate e descrive materiali/elementi visibili con impatto "
                          "sul computo (rivestimenti di facciata, parapetti, infissi, pavimentazioni esterne) come "
                          "riferimento qualitativo: non calcola mai quantità o prezzi da sola, e non modifica il "
                          "computo automaticamente"),
        RequiredDocument("modello_3d", "Modello 3D — SketchUp (.skp), Revit (.rvt/.rfa) o Rhino (.3dm) "
                          "(se esistente)", False,
                          "Allegato come riferimento per la consultazione manuale: il sistema NON legge la "
                          "geometria di questi formati proprietari in questa versione (nessun rilievo o verifica "
                          "automatica basata sul modello)"),
    ]
