"""Confronto prezzi tra i preventivi di più imprese per lo stesso computo
metrico: la NUOVA funzionalità richiesta da Franco, distinta da
confronto_engine.py (che confronta stato di fatto/stato di progetto di un
rilievo — nome simile, scopo completamente diverso, non riutilizzabile qui).

Flusso pensato:
1. Il cliente carica il file 'computo_metrico.xlsx' già scaricato da Estima
   (quello generato da backend/output/excel_generator.py) come base di
   riferimento — leggi_computo_base() lo rilegge in modo puramente meccanico
   (nessuna AI: è già un file strutturato prodotto da Estima stessa).
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

import openpyxl

# Stesse intestazioni di colonna scritte da backend/output/excel_generator.py
# (COLUMNS): la ricerca della riga di intestazione è per CONTENUTO, non per
# numero di riga fisso, perché quella riga si sposta in base a quante note
# metodologiche precedono la tabella nel file originale.
_COLONNE_ATTESE = ("N.", "Codice", "Descrizione")
_MAX_RIGHE_RICERCA_INTESTAZIONE = 30


class ConfrontoPreventiviError(ValueError):
    """File di computo base non riconosciuto o vuoto: mostrata così com'è
    all'utente, mai propagata come errore tecnico generico."""


def leggi_computo_base(path: str) -> list[dict]:
    """Rilegge un file 'computo_metrico.xlsx' generato da Estima (qualunque
    versione/lingua delle note che lo precedono) e ne estrae le voci
    essenziali per il confronto: numero, codice, categoria, descrizione,
    unità di misura, quantità. Il prezzo unitario del computo originale non
    serve al confronto (quello che conta qui sono i prezzi DELLE IMPRESE) e
    non viene riletto. Solleva ConfrontoPreventiviError con un messaggio
    comprensibile se il file non ha la struttura attesa."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:
        raise ConfrontoPreventiviError(
            f"Il file '{path.rsplit('/', 1)[-1]}' non è un file Excel leggibile: {exc}"
        ) from exc
    ws = wb["Computo metrico"] if "Computo metrico" in wb.sheetnames else wb.active

    header_row = None
    intestazioni: dict[str, int] = {}
    max_col = min(ws.max_column or 12, 20)
    for r in range(1, min(ws.max_row or 1, _MAX_RIGHE_RICERCA_INTESTAZIONE) + 1):
        riga = {}
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and v.strip():
                riga[v.strip()] = c
        if all(col in riga for col in _COLONNE_ATTESE):
            header_row = r
            intestazioni = riga
            break
    if header_row is None:
        raise ConfrontoPreventiviError(
            "Il file caricato non sembra un computo metrico esportato da Estima.AI: non trovo le colonne "
            "'N.', 'Codice', 'Descrizione'. Carica il file .xlsx scaricato con il pulsante 'Excel' dal "
            "passaggio di revisione del computo."
        )

    def _col(nome: str, obbligatoria: bool = True) -> int | None:
        idx = intestazioni.get(nome)
        if idx is None and obbligatoria:
            raise ConfrontoPreventiviError(f"Colonna '{nome}' mancante nel file caricato.")
        return idx

    col_n = _col("N.")
    col_codice = _col("Codice")
    col_categoria = _col("Categoria", obbligatoria=False)
    col_descrizione = _col("Descrizione")
    col_um = _col("U.M.", obbligatoria=False)
    col_quantita = _col("Quantità", obbligatoria=False)

    voci: list[dict] = []
    for r in range(header_row + 1, (ws.max_row or header_row) + 1):
        n = ws.cell(row=r, column=col_n).value
        if n in (None, ""):
            continue
        try:
            numero = int(n)
        except (TypeError, ValueError):
            continue
        descrizione = str(ws.cell(row=r, column=col_descrizione).value or "").strip()
        if not descrizione:
            continue
        try:
            quantita = float(ws.cell(row=r, column=col_quantita).value or 0) if col_quantita else 0.0
        except (TypeError, ValueError):
            quantita = 0.0
        voci.append({
            "numero": numero,
            "codice": str(ws.cell(row=r, column=col_codice).value or "").strip(),
            "categoria": (str(ws.cell(row=r, column=col_categoria).value or "").strip()
                          if col_categoria else ""),
            "descrizione": descrizione,
            "unita_misura": str(ws.cell(row=r, column=col_um).value or "").strip() if col_um else "",
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
