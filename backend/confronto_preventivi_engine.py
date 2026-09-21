"""Confronto prezzi tra i preventivi di più imprese per lo stesso computo
metrico: la NUOVA funzionalità richiesta da Franco, distinta da
confronto_engine.py (che confronta stato di fatto/stato di progetto di un
rilievo — nome simile, scopo completamente diverso, non riutilizzabile qui).

Flusso pensato:
1. Il cliente carica un computo metrico in Excel come base di riferimento —
   NON deve necessariamente essere il file generato da Estima (richiesta
   esplicita di Franco: "basta che sia un file Excel", qualunque struttura di
   colonne abbia): leggi_computo_base() prova prima un riconoscimento
   meccanico ed economico delle intestazioni di colonna più comuni nei
   computi metrici italiani (funziona per il file di Estima e per la
   maggior parte dei computi fatti a mano o esportati da altri programmi,
   zero chiamate AI). Se questo tentativo fallisce — struttura davvero
   fuori dagli schemi — il chiamante (vedi l'endpoint
   /api/confronto/carica-base in backend/main.py) ripiega su
   ai_assistant.interpreta_computo_base_excel, che legge il foglio con
   un'AI: QUESTO fallback consuma crediti/quota AI, perché a differenza del
   riconoscimento meccanico richiede comprensione del contenuto, non solo
   un confronto di intestazioni.
2. Per ciascuna impresa, il cliente carica il preventivo ricevuto così com'è
   (PDF, Excel o foto/scansione, in QUALSIASI formato/struttura l'impresa lo
   abbia scritto): un'AI (vedi ai_assistant.interpreta_preventivo_impresa)
   abbina ogni prezzo alla voce di computo corrispondente. Questo È il punto
   in cui il confronto consuma crediti/quota AI (una chiamata per ogni
   preventivo caricato) — a differenza del resto di questo modulo, che è
   puro calcolo.
3. L'utente rivede/corregge a mano l'abbinamento proposto dall'AI (il
   frontend mostra la tabella estratta come modificabile prima di
   confermare): i dati che arrivano qui a costruisci_confronto() sono quindi
   sempre quelli confermati dall'utente, mai l'output grezzo dell'AI.
4. costruisci_confronto() assembla la tabella comparativa finale (per
   categoria, con i totali) che i generatori Excel/PDF trasformano in file —
   passaggio anch'esso puramente di calcolo, zero chiamate AI.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import unicodedata

import openpyxl

_MAX_RIGHE_RICERCA_INTESTAZIONE = 30

# Riconoscimento delle intestazioni di colonna per SINONIMI, non per testo esatto: il file
# caricato non deve necessariamente essere quello generato da Estima (richiesta esplicita di
# Franco: "basta che sia un file Excel qualsiasi") — deve solo assomigliare a un normale computo
# metrico italiano, con QUALUNQUE intestazione tra quelle più comuni nel settore (proprie di
# Estima, di PriMus/altri software, o scritte a mano). Il confronto testuale è case-insensitive
# e ignora spazi/punteggiatura di contorno (vedi _normalizza). "descrizione" e "quantita" sono le
# uniche colonne davvero indispensabili: senza una descrizione non c'è voce da mostrare, senza una
# quantità non è calcolabile alcun importo per il confronto.
_SINONIMI_COLONNE: dict[str, tuple[str, ...]] = {
    "numero": ("n.", "n°", "nr", "nr.", "num", "numero", "pos", "pos.", "voce", "n ord", "nrord"),
    "codice": ("codice", "cod", "cod.", "tariffa", "art", "art.", "articolo", "codicetariffa"),
    "categoria": ("categoria", "capitolo", "gruppo", "categoriadilavoro", "sezione"),
    "descrizione": ("descrizione", "denominazione", "lavorazione", "designazione",
                     "descrizionedeilavori", "descrizionelavorazione", "oggetto", "voce di computo",
                     "vocedicomputo"),
    "unita_misura": ("um", "u.m.", "unita", "unitadimisura", "unitàdimisura", "misura"),
    "quantita": ("quantita", "quantità", "qta", "qta.", "qtà", "quant", "quant."),
}


def _normalizza(testo: str) -> str:
    """minuscolo, senza accenti (NFKD + scarto dei segni diacritici) e senza punteggiatura/spazi:
    così "Unità", "unita", "UNITA'" e "Unità " normalizzano tutti a "unita" e si abbinano allo
    stesso sinonimo, invece di richiedere una variante accentata e una no per ogni voce."""
    senza_accenti = "".join(
        ch for ch in unicodedata.normalize("NFKD", testo.strip().lower()) if not unicodedata.combining(ch)
    )
    return "".join(ch for ch in senza_accenti if ch.isalnum())


_SINONIMI_NORMALIZZATI = {
    ruolo: {_normalizza(s) for s in sinonimi} for ruolo, sinonimi in _SINONIMI_COLONNE.items()
}


class ConfrontoPreventiviError(ValueError):
    """File di computo base non riconosciuto o vuoto: mostrata così com'è
    all'utente, mai propagata come errore tecnico generico (salvo il fallback
    AI gestito dall'endpoint, vedi il commento in cima al file)."""


def _trova_intestazioni(ws) -> tuple[int, dict[str, int]] | None:
    """Cerca, tra le prime righe del foglio, quella che assomiglia di più a
    un'intestazione di colonne di computo metrico: per ogni riga candidata
    associa ad ogni RUOLO (numero/codice/categoria/descrizione/unita_misura/
    quantita) la prima colonna il cui testo corrisponde a uno dei sinonimi
    noti. Ritorna (indice di riga, {ruolo: colonna}) della prima riga che
    copre almeno descrizione+quantita, o None se nessuna riga qualifica."""
    max_col = min(ws.max_column or 12, 30)
    for r in range(1, min(ws.max_row or 1, _MAX_RIGHE_RICERCA_INTESTAZIONE) + 1):
        ruoli: dict[str, int] = {}
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if not isinstance(v, str) or not v.strip():
                continue
            chiave = _normalizza(v)
            for ruolo, sinonimi in _SINONIMI_NORMALIZZATI.items():
                if ruolo not in ruoli and chiave in sinonimi:
                    ruoli[ruolo] = c
        if "descrizione" in ruoli and "quantita" in ruoli:
            return r, ruoli
    return None


def leggi_computo_base(path: str) -> list[dict]:
    """Rilegge un computo metrico in Excel — di Estima o di qualunque altra
    provenienza — e ne estrae le voci essenziali per il confronto: numero,
    codice, categoria, descrizione, unità di misura, quantità. Il prezzo
    unitario del computo originale non serve al confronto (quello che conta
    qui sono i prezzi DELLE IMPRESE) e non viene riletto. Puro riconoscimento
    meccanico delle intestazioni di colonna (vedi _trova_intestazioni): se il
    file ha una struttura troppo fuori dagli schemi per essere riconosciuta
    così, solleva ConfrontoPreventiviError — il chiamante decide se e come
    ripiegare sull'interpretazione AI (vedi il commento in cima al file)."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:
        raise ConfrontoPreventiviError(
            f"Il file '{path.rsplit('/', 1)[-1]}' non è un file Excel leggibile: {exc}"
        ) from exc

    fogli_da_provare = [wb["Computo metrico"]] if "Computo metrico" in wb.sheetnames else list(wb.worksheets)
    trovato = None
    ws = None
    for foglio in fogli_da_provare:
        trovato = _trova_intestazioni(foglio)
        if trovato:
            ws = foglio
            break
    if not trovato or ws is None:
        raise ConfrontoPreventiviError(
            "Non riesco a riconoscere automaticamente le colonne di questo file (mi servono almeno una "
            "colonna 'Descrizione' e una 'Quantità', con questi o nomi equivalenti)."
        )
    header_row, ruoli = trovato

    voci: list[dict] = []
    numero_auto = 0
    for r in range(header_row + 1, (ws.max_row or header_row) + 1):
        descrizione = str(ws.cell(row=r, column=ruoli["descrizione"]).value or "").strip()
        if not descrizione:
            continue
        quantita_raw = ws.cell(row=r, column=ruoli["quantita"]).value
        try:
            quantita = float(quantita_raw)
        except (TypeError, ValueError):
            # Riga senza una quantità numerica leggibile (es. intestazione di categoria,
            # sottototale, riga vuota di formattazione): non è una voce di computo vera e
            # propria, la si salta invece di inserirla con quantità 0 (che falserebbe il
            # confronto facendo sembrare "non quotata" una voce che in realtà non esiste).
            continue
        numero_auto += 1
        numero = numero_auto
        if "numero" in ruoli:
            try:
                numero = int(ws.cell(row=r, column=ruoli["numero"]).value)
            except (TypeError, ValueError):
                pass
        voci.append({
            "numero": numero,
            "codice": str(ws.cell(row=r, column=ruoli["codice"]).value or "").strip() if "codice" in ruoli else "",
            "categoria": (str(ws.cell(row=r, column=ruoli["categoria"]).value or "").strip()
                          if "categoria" in ruoli else ""),
            "descrizione": descrizione,
            "unita_misura": (str(ws.cell(row=r, column=ruoli["unita_misura"]).value or "").strip()
                              if "unita_misura" in ruoli else ""),
            "quantita": quantita,
        })

    if not voci:
        raise ConfrontoPreventiviError(
            "Nessuna voce riconosciuta nel file caricato: verifica di aver caricato il computo metrico "
            "completo (non un foglio vuoto o solo parzialmente compilato)."
        )
    return voci


@dataclass
class RigaImpresa:
    prezzo_unitario: float | None  # None = voce non quotata da questa impresa
    nota: str = ""


@dataclass
class ImpresaPreventivo:
    nome: str
    righe: dict[int, RigaImpresa] = field(default_factory=dict)  # chiave: numero voce
    totale_dichiarato: float | None = None  # totale scritto a mano dall'impresa sul proprio preventivo, se noto


def costruisci_confronto(voci: list[dict], imprese: list[ImpresaPreventivo]) -> dict:
    """Assembla la struttura pronta per i generatori Excel/PDF: voci
    raggruppate per categoria (nell'ordine di prima comparsa, come nel
    computo originale), ciascuna con l'importo calcolato per ogni impresa
    (prezzo_unitario * quantità, None se l'impresa non ha quotato quella
    voce), più i totali di riga/colonna. Puro calcolo: nessuna chiamata AI."""
    if not voci:
        raise ConfrontoPreventiviError("Nessuna voce di computo su cui basare il confronto.")
    if not imprese:
        raise ConfrontoPreventiviError("Serve almeno un'impresa da confrontare.")

    categorie_ordine: list[str] = []
    per_categoria: dict[str, list[dict]] = {}
    for v in voci:
        cat = v.get("categoria") or "Senza categoria"
        if cat not in per_categoria:
            per_categoria[cat] = []
            categorie_ordine.append(cat)
        riga = dict(v)
        riga["importi"] = {}
        for impresa in imprese:
            ri = impresa.righe.get(v["numero"])
            if ri is None or ri.prezzo_unitario is None:
                riga["importi"][impresa.nome] = None
            else:
                riga["importi"][impresa.nome] = round(ri.prezzo_unitario * v["quantita"], 2)
        per_categoria[cat].append(riga)

    totali = {impresa.nome: 0.0 for impresa in imprese}
    non_quotate: dict[str, list[int]] = {impresa.nome: [] for impresa in imprese}
    for v in voci:
        for impresa in imprese:
            ri = impresa.righe.get(v["numero"])
            if ri is None or ri.prezzo_unitario is None:
                non_quotate[impresa.nome].append(v["numero"])
            else:
                totali[impresa.nome] += round(ri.prezzo_unitario * v["quantita"], 2)

    return {
        "categorie": [{"nome": cat, "voci": per_categoria[cat]} for cat in categorie_ordine],
        "imprese_nomi": [impresa.nome for impresa in imprese],
        "totali": {nome: round(tot, 2) for nome, tot in totali.items()},
        "totali_dichiarati": {impresa.nome: impresa.totale_dichiarato for impresa in imprese},
        "non_quotate": non_quotate,
    }
