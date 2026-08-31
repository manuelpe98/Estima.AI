"""Genera le domande su materiali/finiture quando manca il capitolato.

Regola posta dall'utente: se il capitolato non è allegato, il sistema deve
CHIEDERE materiali e finiture invece di assumerli. Le domande sono per
categoria e si attivano solo se il testo del capitolato (se fornito) non
sembra già rispondere a quella categoria.
"""
from __future__ import annotations
from .models import CapitolatoQuestion

CATEGORY_KEYWORDS = {
    "pavimenti": ["pavimento", "gres", "parquet", "battiscopa", "pavimentazione"],
    "pareti_interne": ["intonaco", "tinteggiatura", "pittura", "rasatura"],
    "serramenti_esterni": ["infisso", "serramento esterno", "doppio vetro", "pvc", "alluminio", "triplo vetro"],
    "porte_interne": ["porta interna", "porta tamburata", "porta blindata"],
    "impianto_elettrico": ["impianto elettrico", "domotica", "punti luce"],
    "impianto_idrico": ["impianto idrico", "sanitari", "termoidraulico", "climatizzazione"],
    "tipo_struttura": ["cemento armato", "muratura portante", "struttura mista", "struttura in legno"],
    "copertura_tipo": ["copertura", "manto di copertura", "tetto"],
}

QUESTIONS: list[CapitolatoQuestion] = [
    CapitolatoQuestion(
        id="pavimenti", categoria="Pavimenti",
        testo="Che tipo di pavimentazione prevedi per gli ambienti principali?",
        opzioni=["Gres porcellanato standard", "Gres porcellanato effetto legno/pietra",
                 "Parquet prefinito", "Marmo/pietra naturale", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="pareti_interne", categoria="Pareti interne",
        testo="Che finitura è prevista per intonaco e tinteggiatura delle pareti interne?",
        opzioni=["Intonaco tradizionale + pittura lavabile", "Rasatura civile + pittura",
                 "Intonaco premiscelato + pittura decorativa", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="serramenti_esterni", categoria="Serramenti esterni",
        testo="Che tipologia di serramenti esterni (finestre) è prevista?",
        opzioni=["PVC doppio vetro basso emissivo", "Alluminio a taglio termico doppio vetro",
                 "Legno doppio vetro", "Alluminio/PVC triplo vetro", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="porte_interne", categoria="Porte interne",
        testo="Che tipologia di porte interne è prevista?",
        opzioni=["Porta tamburata laminata standard", "Porta tamburata laccata",
                 "Porta in legno massello", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="impianto_elettrico", categoria="Impianto elettrico",
        testo="Che livello di impianto elettrico è previsto?",
        opzioni=["Standard (normativa base)", "Predisposizione domotica",
                 "Domotica completa", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="impianto_idrico", categoria="Impianto idrico-sanitario",
        testo="Che livello di finiture per l'impianto idrico-sanitario è previsto?",
        opzioni=["Sanitari e rubinetteria standard", "Fascia media", "Fascia alta",
                 "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="tipo_struttura", categoria="Struttura verticale",
        testo="Che tipo di struttura verticale è prevista?",
        opzioni=["Cemento armato (pilastri e travi)", "Muratura portante",
                 "Struttura mista", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="copertura_tipo", categoria="Copertura",
        testo="Che tipo di copertura è prevista?",
        opzioni=["Tetto a falde, manto in laterizio", "Tetto a falde, manto in cemento",
                 "Copertura piana con guaina bituminosa", "Copertura metallica",
                 "Altro (specificare a parte)"],
    ),
]


def missing_questions(capitolato_text: str | None) -> list[CapitolatoQuestion]:
    if not capitolato_text:
        return list(QUESTIONS)
    text_low = capitolato_text.lower()
    result = []
    for q in QUESTIONS:
        keywords = CATEGORY_KEYWORDS.get(q.id, [])
        already_covered = any(kw in text_low for kw in keywords)
        if not already_covered:
            result.append(q)
    return result
