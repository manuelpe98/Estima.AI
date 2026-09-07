"""Modelli dati condivisi dalla pipeline di computo metrico."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationResult:
    is_valid: bool
    is_vector_pdf: bool
    scale_denominator: Optional[int]
    quote_count: int
    messages: list[str] = field(default_factory=list)


@dataclass
class RoomQuantity:
    label: str
    area_m2: float
    perimeter_m: float
    source: str = "rilevata da poligono disegno"
    # Piano di appartenenza (es. "TERRA", "PRIMO", "INTERRATO"), assegnato SOLO
    # quando la tavola contiene più piante affiancate sullo stesso foglio (vedi
    # geometry_engine._piano_label_positions): il vano viene associato al
    # titolo di piano più vicino sulla pagina. None quando la tavola contiene
    # una sola pianta (informazione non necessaria) o quando non è stato
    # possibile determinarlo.
    piano: Optional[str] = None


@dataclass
class OpeningQuantity:
    code: str
    kind: str  # "porta" | "finestra"
    count: int
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    source: str = "conteggio sigle a disegno"


@dataclass
class TaggedElement:
    """Elemento generico riconosciuto tramite sigla a disegno + abaco
    (porte/finestre, ma anche pilastri/travi su pianta strutturale)."""
    code: str
    kind: str
    count: int
    dim1_cm: Optional[float] = None
    dim2_cm: Optional[float] = None


@dataclass
class RoomComparison:
    label: str
    area_sdf_m2: Optional[float]
    area_sdp_m2: Optional[float]
    stato: str  # "invariato" | "nuovo" | "demolito" | "superficie_variata"


@dataclass
class CapitolatoQuestion:
    id: str
    categoria: str
    testo: str
    opzioni: list[str] = field(default_factory=list)


# Etichetta leggibile + colore per ciascun valore di ComputoVoce.origine (vedi il
# commento sul campo per la definizione di ciascuna categoria). Usata dai
# generatori di output (Excel/Word) e dall'API per mostrare la stessa
# classificazione ovunque, senza duplicarne la logica.
ORIGINE_INFO: dict[str, tuple[str, str]] = {
    "esplicita": ("Esplicita (da elaborato/abaco)", "🟢"),
    "derivata": ("Derivata (calcolata da dati misurati)", "🟢"),
    "inferita": ("Inferita (regola costruttiva/incidenza tipica)", "🟡"),
    "assunta": ("Assunta (valore indicativo generico)", "🟠"),
    "non_disponibile": ("N/D — da completare a mano", "⚪"),
}


@dataclass
class ComputoVoce:
    numero: int
    codice: str
    categoria: str
    descrizione: str
    unita_misura: str
    quantita: float
    prezzo_unitario: float
    note: str = ""
    # Commento libero dell'utente in fase di revisione (prima della generazione
    # dei file finali), es. per segnalare una correzione da fare o il motivo di
    # una modifica manuale a quantità/prezzo: distinto da 'note', che sono le
    # note metodologiche generate automaticamente dal sistema.
    commento: str = ""
    # True per una voce che il sistema NON può quantificare/prezzare in modo
    # affidabile dai soli elaborati caricati (es. opere accessorie non
    # rappresentate in pianta, o misurabili solo con dati che il rilievo
    # automatico non ha): la riga viene comunque generata, con quantità a 0
    # (il prezzo, quando la voce di prezzario abbinata ne ha uno, viene invece
    # mostrato come riferimento di partenza anziché azzerato), per garantire
    # che la VOCE non manchi dal computo — ma va evidenziata (colore) e
    # completata a mano da chi rivede il computo.
    da_completare: bool = False
    # Provenienza del dato (da NON mischiare tra loro, richiesta esplicita
    # dell'utente): in che modo il sistema è arrivato a questa quantità/prezzo,
    # così chi rivede il computo sa quanto fidarsi di ogni singola riga.
    #   "esplicita"       — letta direttamente da un elaborato (es. sezione di un
    #                        pilastro dall'abaco, dimensioni di un serramento
    #                        dall'abaco serramenti, conteggio vani/aperture)
    #   "derivata"        — calcolata con una formula geometrica a partire da dati
    #                        espliciti/misurati (es. superficie = area vani sommate,
    #                        volume = area sedime x spessore confermato dall'utente)
    #   "inferita"        — calcolata usando una regola costruttiva o un'incidenza
    #                        tecnica tipica (es. kg di acciaio per m³), non
    #                        verificata sui documenti di QUESTO progetto
    #   "assunta"         — nessun dato specifico di questo progetto è disponibile:
    #                        usato un valore indicativo generico (es. prezzo a
    #                        corpo per serramenti senza dimensioni note)
    #   "non_disponibile" — voce segnaposto (vedi da_completare): non quantificata
    origine: str = "assunta"

    @property
    def importo(self) -> float:
        return round(self.quantita * self.prezzo_unitario, 2)


@dataclass
class ProjectMeta:
    nome_progetto: str = "Progetto senza nome"
    committente: str = ""
    ubicazione: str = ""
    prezzario_nome: str = "Prezzario Regione Lombardia 2022 (selezione di riferimento)"
    tipo_intervento: str = "nuova_costruzione"  # "nuova_costruzione" | "ristrutturazione"
