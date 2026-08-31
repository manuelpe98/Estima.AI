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
            RequiredDocument("relazione_capitolato", "Relazione tecnica / capitolato", False,
                              "Se assente, il sistema chiede materiali e finiture con un questionario"),
            RequiredDocument("modello_3d", "Modello 3D (se esistente)", False,
                              "Non ancora usato per il calcolo in questa versione, utile come riferimento"),
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
        RequiredDocument("relazione_capitolato", "Relazione tecnica / capitolato", False,
                          "Se assente, il sistema chiede materiali e finiture con un questionario"),
        RequiredDocument("modello_3d", "Modello 3D (se esistente)", False),
    ]
