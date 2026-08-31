"""Parametri numerici che non sono deducibili in modo affidabile dai soli
elaborati grafici in questa versione (richiederebbero una lettura automatica
delle sezioni, non ancora implementata): vengono proposti con un valore di
default plausibile e l'utente li conferma o modifica prima di generare il
computo. Sono concettualmente diversi dalle domande di capitolato (materiali/
finiture): qui si tratta di misure, non di scelte di finitura.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ParametroNumerico:
    id: str
    label: str
    default: float
    unita: str
    note: str = ""


PARAMETRI: list[ParametroNumerico] = [
    ParametroNumerico("altezza_interna_m", "Altezza interna dei vani", 2.70, "m",
                       "Usata per la superficie di intonaco/tinteggiatura pareti"),
    ParametroNumerico("altezza_interpiano_strutturale_m", "Altezza di interpiano strutturale", 3.00, "m",
                       "Usata per il volume di pilastri e muratura portante"),
    ParametroNumerico("profondita_scavo_m", "Profondità media dello scavo di fondazione", 1.20, "m",
                       "Da confermare in base alla relazione geologica/strutturale"),
    ParametroNumerico("spessore_muro_portante_cm", "Spessore muratura portante perimetrale", 30.0, "cm",
                       "Usato solo se la struttura verticale scelta è 'muratura portante'"),
    ParametroNumerico("lunghezza_media_travi_m", "Lunghezza media delle travi in c.a.", 4.00, "m",
                       "Stima parametrica in assenza di misura diretta della campata da disegno"),
    ParametroNumerico("incidenza_acciaio_kg_m3", "Incidenza acciaio per c.a. (kg per m³ di calcestruzzo)", 100.0, "kg/m3",
                       "Valore parametrico tipico per un computo estimativo preliminare"),
    ParametroNumerico("angolo_falda_gradi", "Angolo medio delle falde di copertura", 25.0, "gradi",
                       "0 per copertura piana; usato per correggere la superficie in pianta"),
]


def merge_parametri(overrides: dict[str, float]) -> dict[str, float]:
    result = {p.id: p.default for p in PARAMETRI}
    for k, v in (overrides or {}).items():
        if k in result and v is not None:
            result[k] = float(v)
    return result
