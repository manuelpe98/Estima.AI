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

    @property
    def importo(self) -> float:
        return round(self.quantita * self.prezzo_unitario, 2)


@dataclass
class ProjectMeta:
    nome_progetto: str = "Progetto senza nome"
    committente: str = ""
    ubicazione: str = ""
    prezzario_nome: str = "Prezzario di esempio (placeholder, non ufficiale)"
    tipo_intervento: str = "nuova_costruzione"  # "nuova_costruzione" | "ristrutturazione"
