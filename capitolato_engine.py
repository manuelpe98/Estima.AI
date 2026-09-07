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
    "cappotto_termico": ["cappotto", "isolamento a cappotto", "isolamento termico esterno", "eps", "polistirene",
                          "lana di roccia", "fibra di legno"],
    "tipo_solaio": ["laterocemento", "predalles", "soletta piena", "solaio in c.a."],
    "tipo_pareti_divisorie": ["parete divisoria", "tramezzo", "tramezzatura", "cartongesso", "laterizio forato"],
    "richiede_contropareti": ["controparete", "contropareti"],
    "vespaio_aerato": ["vespaio"],
    "velette": ["veletta", "velette", "gola luminosa"],
    "controsoffitti": ["controsoffitt", "contro soffitt"],
    "gru_cantiere": ["gru a torre", "autogru", "gru da cantiere", "noleggio gru", "nolo gru", "nolo della gru"],
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
                 "Porta in legno massello", "Porta rasomuro (a filo muro, a scomparsa)",
                 "Altro (specificare a parte)"],
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
    CapitolatoQuestion(
        id="cappotto_termico", categoria="Cappotto termico esterno",
        testo="Che materiale isolante è previsto per il cappotto termico esterno?",
        opzioni=["EPS/polistirene", "Lana di roccia", "Fibra di legno", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="tipo_solaio", categoria="Solai",
        testo="Come sono realizzati i solai?",
        opzioni=["Laterocemento (pacchetto completo)", "Predalles (pacchetto completo)",
                 "Soletta piena in cemento armato (getto in opera)", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="tipo_pareti_divisorie", categoria="Pareti divisorie interne",
        testo="Come sono realizzate le pareti divisorie interne (tramezzature)?",
        opzioni=["Muratura in laterizio forato", "Cartongesso su orditura metallica",
                 "Già esistenti / non richieste in questo intervento", "Altro (specificare a parte)"],
    ),
    CapitolatoQuestion(
        id="richiede_contropareti", categoria="Contropareti interne",
        testo="Sono previste contropareti interne in cartongesso (es. per il passaggio di impianti a parete)?",
        opzioni=["Sì", "No"],
    ),
    CapitolatoQuestion(
        id="vespaio_aerato", categoria="Vespaio aerato",
        testo="È prevista la formazione di un vespaio aerato sotto la pavimentazione del piano terra/interrato?",
        opzioni=["Sì", "No"],
    ),
    CapitolatoQuestion(
        id="velette", categoria="Velette",
        testo="Sono previste velette in cartongesso (es. per la chiusura di soglie finestre, per il "
              "passaggio di tende o per l'alloggiamento di illuminazione indiretta)?",
        opzioni=["Sì", "No"],
    ),
    CapitolatoQuestion(
        id="controsoffitti", categoria="Controsoffitti",
        testo="Sono previsti controsoffitti in cartongesso? (Il sistema non riconosce automaticamente in "
              "quali ambienti: se rispondi sì, la quantità proposta copre l'intera superficie dei vani e va "
              "corretta a mano per gli ambienti effettivamente interessati)",
        opzioni=["Sì", "No"],
    ),
    CapitolatoQuestion(
        id="gru_cantiere", categoria="Gru da cantiere",
        testo="È prevista una gru (a torre o autogru) per il cantiere? Il sistema non lo deduce automaticamente "
              "dal tipo di intervento (es. una nuova costruzione di solito la richiede, una ristrutturazione "
              "interna di solito no, ma dipende dal cantiere reale): confermalo tu.",
        opzioni=["Sì", "No"],
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
