"""Orchestrazione end-to-end: dai documenti caricati al computo metrico
estimativo completo (finiture, strutture, scavi, copertura, impianti a corpo
e, per le ristrutturazioni, confronto stato di fatto / stato di progetto).

La pipeline è divisa in due fasi, così l'utente può VERIFICARE e correggere
i vani/aperture/elementi rilevati automaticamente prima che vengano usati per
calcolare i prezzi (richiesto dopo aver verificato che, su disegni CAD reali
molto dettagliati, il rilievo geometrico automatico non è sempre preciso al
100% — es. due ambienti attigui possono risultare uniti in un'unica area):

- `extract_quantities(...)`: dai PDF ai vani/aperture/elementi strutturali
  rilevati (nessun prezzo, nessun file generato). Usata dall'endpoint
  `/api/estrai-vani` per mostrare all'utente cosa è stato riconosciuto.
- `build_from_quantities(...)`: da vani/aperture/elementi (eventualmente
  corretti a mano dall'utente) ai file finali (Excel, PriMus, Word). Usata
  dall'endpoint `/api/generate`.
- `run_pipeline(...)`: le esegue entrambe in sequenza con la firma originale,
  usata dai test e da chi non ha bisogno del passaggio di verifica intermedio.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import fitz

from .models import ValidationResult, ProjectMeta, RoomComparison, RoomQuantity, OpeningQuantity, TaggedElement
from .pdf_validation import validate_pdf, find_scale_on_page, detect_empirical_scale_on_page
from .geometry_engine import (
    rooms_with_polygons, extract_openings, extract_tagged_elements, extract_dimensioned_openings,
    extract_building_footprint_m2, extract_building_perimeter_m, merge_shared_rooms, extract_piscina,
    ROOM_LABEL_HINTS, DOOR_HEIGHT_RANGE_CM,
)
from .capitolato_engine import missing_questions
from .parametri_engine import merge_parametri
from .confronto_engine import compare_stati
from .prezzario import db as prezzario_db
from .prezzario.matching import build_computo
from .output.excel_generator import build_excel, build_primus_export
from .output.word_generator import build_word


def _resolve_scale(doc: "fitz.Document", page_number: int, declared_scale: int | None,
                    label: str, note_metodologiche: list[str]) -> int:
    """Determina la scala da usare per convertire le misure di UNA pagina: parte
    dalla scala dichiarata sulla pagina stessa (o, in mancanza, da quella passata
    come fallback), ma se le quote effettivamente scritte sul disegno indicano —
    con un segnale statistico schiacciante e inequivocabile — una scala diversa,
    usa quella (vedi `detect_empirical_scale_on_page`): capita che il cartiglio
    riporti la scala di un altro elaborato/riquadro dello stesso foglio."""
    scale_dichiarata = find_scale_on_page(doc, page_number) or declared_scale or 100
    if page_number < 0 or page_number >= doc.page_count:
        return scale_dichiarata
    scala_quotata, matched = detect_empirical_scale_on_page(doc[page_number])
    if scala_quotata is not None and scala_quotata != scale_dichiarata:
        note_metodologiche.append(
            f"{label}: la scala dichiarata nel cartiglio (1:{scale_dichiarata}) non corrisponde alle quote "
            f"effettivamente presenti sul disegno ({matched} quote analizzate): è stata usata la scala 1:{scala_quotata}, "
            "dedotta con certezza dalle misure reali riportate in pianta, più affidabile del solo testo del cartiglio."
        )
        return scala_quotata
    return scale_dichiarata


@dataclass
class ExtractionResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    validations: dict[str, ValidationResult] = field(default_factory=dict)
    rooms: list[RoomQuantity] = field(default_factory=list)
    openings: list[OpeningQuantity] = field(default_factory=list)
    structural_elements: list[TaggedElement] = field(default_factory=list)
    footprint_area_m2: float = 0.0
    perimetro_esterno_m: float = 0.0
    piscina_area_m2: float = 0.0
    piscina_perimetro_m: float = 0.0
    piscina_lunghezza_m: float = 0.0
    piscina_larghezza_m: float = 0.0
    roof_area_m2: float = 0.0
    rooms_sdf: list[RoomQuantity] | None = None
    confronto: list[RoomComparison] = field(default_factory=list)
    note_metodologiche: list[str] = field(default_factory=list)

    @property
    def validation_messages(self) -> list[str]:
        out = []
        for v in self.validations.values():
            out.extend(v.messages)
        return out


@dataclass
class PipelineResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    validations: dict[str, ValidationResult] = field(default_factory=dict)
    rooms: list = field(default_factory=list)
    openings: list = field(default_factory=list)
    structural_elements: list = field(default_factory=list)
    footprint_area_m2: float = 0.0
    perimetro_esterno_m: float = 0.0
    piscina_area_m2: float = 0.0
    piscina_perimetro_m: float = 0.0
    piscina_lunghezza_m: float = 0.0
    piscina_larghezza_m: float = 0.0
    roof_area_m2: float = 0.0
    confronto: list = field(default_factory=list)
    questions_asked: list = field(default_factory=list)
    voci: list = field(default_factory=list)
    note_metodologiche: list = field(default_factory=list)
    excel_path: str | None = None
    primus_path: str | None = None
    word_path: str | None = None
    totale: float = 0.0


def validate_only(pdf_path: str) -> ValidationResult:
    return validate_pdf(pdf_path)


def questions_for_project(capitolato_text: str | None):
    return missing_questions(capitolato_text)


def _extract_roof_area(rooms_with_polys, hint_words=("COPERTURA", "TETTO")):
    for room, poly in rooms_with_polys:
        if any(h in room.label.upper() for h in hint_words):
            return room.area_m2
    return 0.0


def extract_quantities(
    tipo_intervento: str,
    pdf_progetto_path: str,
    pdf_stato_di_fatto_path: str | None = None,
    pdf_strutturale_path: str | None = None,
    pdf_copertura_path: str | None = None,
    legend_page: int | None = 1,
    structural_legend_page: int | None = 1,
) -> ExtractionResult:
    """Dai PDF caricati (già validi/uniti) ai vani, aperture ed elementi
    strutturali rilevati. Non calcola prezzi né genera file: serve a mostrare
    all'utente cosa è stato riconosciuto, prima che lo confermi o lo corregga."""
    result = ExtractionResult()

    # --- Validazione di tutti i PDF forniti ---
    v_progetto = validate_pdf(pdf_progetto_path)
    result.validations["progetto"] = v_progetto
    if not v_progetto.is_valid:
        result.ok = False
        result.errors.append("Pianta di progetto non conforme.")

    v_sdf = None
    if tipo_intervento == "ristrutturazione":
        if not pdf_stato_di_fatto_path:
            result.ok = False
            result.errors.append("Per una ristrutturazione è obbligatorio caricare la pianta dello stato di fatto.")
        else:
            v_sdf = validate_pdf(pdf_stato_di_fatto_path)
            result.validations["stato_di_fatto"] = v_sdf
            if not v_sdf.is_valid:
                result.ok = False
                result.errors.append("Pianta dello stato di fatto non conforme.")

    v_strutturale = None
    if pdf_strutturale_path:
        v_strutturale = validate_pdf(pdf_strutturale_path)
        result.validations["strutturale"] = v_strutturale
        if not v_strutturale.is_valid:
            result.ok = False
            result.errors.append("Pianta strutturale non conforme.")

    v_copertura = None
    if pdf_copertura_path:
        v_copertura = validate_pdf(pdf_copertura_path)
        result.validations["copertura"] = v_copertura
        if not v_copertura.is_valid:
            result.ok = False
            result.errors.append("Pianta di copertura non conforme.")

    if not result.ok:
        return result

    # --- Estrazione geometria: stato di progetto ---
    doc = fitz.open(pdf_progetto_path)
    # Se sono stati caricati più elaborati uniti in un solo PDF (es. planimetria
    # generale + pianta di progetto, a scale diverse), usa la scala dichiarata
    # sulla pagina della pianta (pagina 0) invece della prima trovata nell'intero
    # documento unito: altrimenti il rilievo geometrico userebbe una scala
    # sbagliata e non troverebbe nessun vano plausibile.
    scale_dichiarata_pagina = find_scale_on_page(doc, 0)
    scale_pagina_piano = scale_dichiarata_pagina or v_progetto.scale_denominator
    if scale_dichiarata_pagina is not None and scale_pagina_piano != v_progetto.scale_denominator:
        result.note_metodologiche.append(
            f"Il documento di progetto contiene scale diverse su pagine diverse (probabilmente più elaborati "
            f"uniti insieme): per il rilievo di vani e sedime è stata usata la scala dichiarata sulla prima "
            f"pagina (1:{scale_pagina_piano})."
        )
    scale_pagina_piano = _resolve_scale(doc, 0, scale_pagina_piano, "Pianta di progetto", result.note_metodologiche)
    lp = legend_page if (legend_page is not None and legend_page < doc.page_count) else None
    rooms, room_polys = rooms_with_polygons(doc, scale_pagina_piano, plan_page=0)
    rooms, room_polys, merge_notes = merge_shared_rooms(rooms, room_polys)
    piscina, rooms, room_polys, piscina_lunghezza_m, piscina_larghezza_m = extract_piscina(
        rooms, room_polys, scale_pagina_piano)
    if piscina:
        dim_txt = (f"{piscina_lunghezza_m:.2f} x {piscina_larghezza_m:.2f} (m)"
                   if piscina_lunghezza_m > 0 else f"perimetro {piscina.perimeter_m} m")
        result.note_metodologiche.append(
            f"È stata individuata una piscina in pianta (etichetta 'PISCINA', {piscina.area_m2} m², "
            f"dimensioni {dim_txt}): esclusa dai vani normali (non contribuisce a pavimenti/pareti interne/"
            "impianti a corpo per locale) e computata a parte (scavo, vasca, impermeabilizzazione, bordo) con "
            "profondità e larghezza del bordo parametriche — da confermare nei parametri dimensionali, la "
            "pianta non riporta la profondità della vasca."
        )
    openings = extract_openings(doc, plan_page=0, legend_page=lp)
    if not openings:
        # Nessuna sigla + abaco (F1/P1...) trovata: molti disegni reali non la usano.
        # Si ricava porte/finestre direttamente dalle quote larghezza/altezza scritte
        # accanto a ogni varco in pianta (vedi extract_dimensioned_openings).
        openings = extract_dimensioned_openings(doc[0])
        if openings:
            n_porte = sum(o.count for o in openings if o.kind == "porta")
            n_finestre = sum(o.count for o in openings if o.kind == "finestra")
            result.note_metodologiche.append(
                f"Porte e finestre: non è stato trovato un abaco con sigle (F1/P1...) sul disegno, quindi sono "
                f"state rilevate dalle quote larghezza/altezza scritte accanto a ogni varco in pianta "
                f"({n_porte} porte, {n_finestre} finestre riconosciute, per numero di aperture — non di vani). "
                "Un'apertura è classificata come finestra se l'altezza del varco è fuori dall'intervallo tipico "
                f"di un'anta porta ({DOOR_HEIGHT_RANGE_CM[0]}-{DOOR_HEIGHT_RANGE_CM[1]} cm): verifica nel "
                "passaggio di revisione, specialmente eventuali porte-finestre a tutta altezza."
            )
        else:
            result.note_metodologiche.append(
                "ATTENZIONE: non sono state trovate né sigle con abaco (F1/P1...) né quote larghezza/altezza "
                "riconoscibili accanto ai varchi: porte e finestre non sono state rilevate automaticamente. "
                "Aggiungile a mano nel passaggio di verifica."
            )
    footprint = extract_building_footprint_m2(room_polys, scale_pagina_piano)
    perimetro_esterno = extract_building_perimeter_m(room_polys, scale_pagina_piano)
    roof_area = _extract_roof_area(list(zip(rooms, room_polys)))
    doc.close()

    if rooms:
        result.note_metodologiche.append(
            f"Il sedime edificio ({round(footprint, 2)} m², usato per lo scavo) è stimato come somma delle aree "
            "dei vani rilevati: NON include corridoi/disimpegni non taggati né lo spessore dei muri perimetrali, "
            "quindi è una stima per difetto — verifica e correggi il valore nel campo 'Sedime edificio' prima di "
            "procedere, specialmente se l'edificio comprende corpi separati (es. autorimessa staccata dalla casa)."
        )

    if not rooms:
        result.note_metodologiche.append(
            "ATTENZIONE: nessun vano è stato riconosciuto sulla prima pagina del documento di progetto, quindi "
            "il computo delle finiture, degli scavi e degli impianti risulta vuoto. Le cause più frequenti sono: "
            "(1) se hai caricato più file per la pianta di progetto, la prima pagina del PRIMO file selezionato "
            "non è la pianta quotata con le etichette dei vani (es. è una planimetria generale o un prospetto: "
            "in questo caso ricarica selezionando per primo il file la cui prima pagina è la pianta); "
            "(2) le etichette dei vani nel disegno non usano una delle diciture riconosciute "
            f"({', '.join(ROOM_LABEL_HINTS[:8])}, …); (3) i vani non sono disegnati come poligoni chiusi "
            "nel file vettoriale esportato. Puoi comunque aggiungere i vani a mano nel passaggio di verifica."
        )
    else:
        result.note_metodologiche.extend(merge_notes)

    # --- Copertura dedicata, se caricata separatamente ---
    if pdf_copertura_path and v_copertura and v_copertura.is_valid:
        doc_cop = fitz.open(pdf_copertura_path)
        scale_pagina_cop = find_scale_on_page(doc_cop, 0) or v_copertura.scale_denominator
        scale_pagina_cop = _resolve_scale(doc_cop, 0, scale_pagina_cop, "Pianta di copertura", result.note_metodologiche)
        rooms_cop, polys_cop = rooms_with_polygons(doc_cop, scale_pagina_cop, plan_page=0)
        doc_cop.close()
        area_dedicata = _extract_roof_area(list(zip(rooms_cop, polys_cop)))
        if area_dedicata == 0 and polys_cop:
            # nessuna etichetta "copertura" trovata: usa il poligono più grande della pagina come sagoma tetto
            area_dedicata = max(r.area_m2 for r in rooms_cop)
        if area_dedicata > 0:
            roof_area = area_dedicata
    if roof_area == 0.0 and footprint > 0:
        roof_area = footprint

    # --- Stato di fatto (ristrutturazione) ---
    rooms_sdf = None
    confronto: list[RoomComparison] = []
    if pdf_stato_di_fatto_path and v_sdf and v_sdf.is_valid:
        doc_sdf = fitz.open(pdf_stato_di_fatto_path)
        scale_pagina_sdf = find_scale_on_page(doc_sdf, 0) or v_sdf.scale_denominator
        scale_pagina_sdf = _resolve_scale(doc_sdf, 0, scale_pagina_sdf, "Stato di fatto", result.note_metodologiche)
        rooms_sdf, _ = rooms_with_polygons(doc_sdf, scale_pagina_sdf, plan_page=0)
        doc_sdf.close()
        confronto = compare_stati(rooms_sdf, rooms)

    # --- Elementi strutturali ---
    structural_elements = []
    if pdf_strutturale_path and v_strutturale and v_strutturale.is_valid:
        doc_s = fitz.open(pdf_strutturale_path)
        slp = structural_legend_page if (structural_legend_page is not None and structural_legend_page < doc_s.page_count) else None
        structural_elements = extract_tagged_elements(
            doc_s, plan_page=0, legend_page=slp, code_kinds={"PL": "pilastro", "TR": "trave"},
        )
        doc_s.close()

    result.rooms = rooms
    result.openings = openings
    result.structural_elements = structural_elements
    result.footprint_area_m2 = round(footprint, 2)
    result.perimetro_esterno_m = round(perimetro_esterno, 2)
    result.piscina_area_m2 = round(piscina.area_m2, 2) if piscina else 0.0
    result.piscina_perimetro_m = round(piscina.perimeter_m, 2) if piscina else 0.0
    result.piscina_lunghezza_m = piscina_lunghezza_m if piscina else 0.0
    result.piscina_larghezza_m = piscina_larghezza_m if piscina else 0.0
    result.roof_area_m2 = round(roof_area, 2)
    result.rooms_sdf = rooms_sdf
    result.confronto = confronto
    return result


def compute_voci(
    tipo_intervento: str,
    meta: ProjectMeta,
    answers: dict[str, str],
    parametri_overrides: dict[str, float],
    rooms: list[RoomQuantity],
    openings: list[OpeningQuantity],
    structural_elements: list[TaggedElement],
    footprint_area_m2: float,
    roof_area_m2: float,
    rooms_sdf: list[RoomQuantity] | None,
    confronto: list[RoomComparison],
    note_metodologiche: list[str],
    validation_messages: list[str],
    db_path: str,
    prezzario_id: int | None,
    capitolato_text: str | None = None,
    perimetro_esterno_m: float = 0.0,
    piscina_area_m2: float = 0.0,
    piscina_perimetro_m: float = 0.0,
    piscina_lunghezza_m: float = 0.0,
    piscina_larghezza_m: float = 0.0,
    acustica_materiali: list[str] | None = None,
) -> PipelineResult:
    """Da vani/aperture/elementi (rilevati automaticamente e/o corretti
    dall'utente nel passaggio di verifica) alle righe di computo VALORIZZATE,
    SENZA generare ancora i file finali: serve a mostrare il computo
    all'utente in un passaggio di revisione (dove può correggere quantità/
    prezzi e aggiungere un commento per riga) prima di scaricarlo, con
    `build_files_from_voci`."""
    result = PipelineResult()
    meta.tipo_intervento = tipo_intervento
    parametri = merge_parametri(parametri_overrides)
    questions = missing_questions(capitolato_text)

    conn = prezzario_db.get_connection(db_path)
    if prezzario_id is None:
        prezzario_id = prezzario_db.ensure_placeholder_seed(conn)
        meta.prezzario_nome = prezzario_db.get_prezzario_meta(conn, prezzario_id)["nome"]
    else:
        pmeta = prezzario_db.get_prezzario_meta(conn, prezzario_id)
        if pmeta:
            meta.prezzario_nome = pmeta["nome"]
    voci_prezzario = prezzario_db.get_voci(conn, prezzario_id)

    righe, note = build_computo(
        rooms, openings, answers, parametri, voci_prezzario,
        footprint_area_m2=footprint_area_m2, structural_elements=structural_elements,
        roof_area_m2_plan=roof_area_m2, rooms_sdf=rooms_sdf,
        perimetro_esterno_m=perimetro_esterno_m,
        piscina_area_m2=piscina_area_m2, piscina_perimetro_m=piscina_perimetro_m,
        piscina_lunghezza_m=piscina_lunghezza_m, piscina_larghezza_m=piscina_larghezza_m,
        acustica_materiali=acustica_materiali,
    )
    # le note raccolte durante l'estrazione (es. avviso "nessun vano riconosciuto",
    # scale diverse su pagine diverse) vanno CONSERVATE, non sostituite da quelle
    # di build_computo: le mettiamo per prime, così restano in evidenza.
    tutte_le_note = list(note_metodologiche) + note

    result.rooms = rooms
    result.openings = openings
    result.structural_elements = structural_elements
    result.footprint_area_m2 = round(footprint_area_m2, 2)
    result.perimetro_esterno_m = round(perimetro_esterno_m, 2)
    result.piscina_area_m2 = round(piscina_area_m2, 2)
    result.piscina_perimetro_m = round(piscina_perimetro_m, 2)
    result.piscina_lunghezza_m = piscina_lunghezza_m
    result.piscina_larghezza_m = piscina_larghezza_m
    result.roof_area_m2 = round(roof_area_m2, 2)
    result.confronto = confronto
    result.questions_asked = questions
    result.voci = righe
    result.note_metodologiche = tutte_le_note
    result.validations = {}
    result.totale = round(sum(v.importo for v in righe), 2)
    return result


def build_files_from_voci(
    voci: list,
    meta: ProjectMeta,
    note_metodologiche: list[str],
    validation_messages: list[str],
    confronto: list[RoomComparison],
    excel_out: str,
    primus_out: str,
    word_out: str,
) -> PipelineResult:
    """Genera i file finali (Excel, PriMus, Word) direttamente da una lista di
    righe di computo GIÀ CALCOLATA (da `compute_voci`, eventualmente corretta
    a mano dall'utente nel passaggio di revisione — quantità, prezzi,
    descrizioni, commenti): non ricalcola nulla dai vani/aperture originali,
    così le correzioni dell'utente sono quelle che finiscono nei file."""
    build_excel(voci, meta, excel_out)
    build_primus_export(voci, meta, primus_out)
    build_word(voci, meta, note_metodologiche, validation_messages, word_out, confronto=confronto)

    result = PipelineResult()
    result.voci = voci
    result.note_metodologiche = note_metodologiche
    result.confronto = confronto
    result.excel_path = excel_out
    result.primus_path = primus_out
    result.word_path = word_out
    result.totale = round(sum(v.importo for v in voci), 2)
    return result


def build_from_quantities(
    tipo_intervento: str,
    meta: ProjectMeta,
    answers: dict[str, str],
    parametri_overrides: dict[str, float],
    rooms: list[RoomQuantity],
    openings: list[OpeningQuantity],
    structural_elements: list[TaggedElement],
    footprint_area_m2: float,
    roof_area_m2: float,
    rooms_sdf: list[RoomQuantity] | None,
    confronto: list[RoomComparison],
    note_metodologiche: list[str],
    validation_messages: list[str],
    db_path: str,
    prezzario_id: int | None,
    excel_out: str,
    primus_out: str,
    word_out: str,
    capitolato_text: str | None = None,
    perimetro_esterno_m: float = 0.0,
    piscina_area_m2: float = 0.0,
    piscina_perimetro_m: float = 0.0,
    piscina_lunghezza_m: float = 0.0,
    piscina_larghezza_m: float = 0.0,
    acustica_materiali: list[str] | None = None,
) -> PipelineResult:
    """Da vani/aperture/elementi ai file finali del computo, in un solo passo
    (calcola le voci e genera subito i file, senza passaggio di revisione
    intermedio): comodo per i test e per chi non ha bisogno di rivedere/
    commentare le voci prima di scaricare. Equivalente a chiamare in sequenza
    `compute_voci` e `build_files_from_voci`."""
    computed = compute_voci(
        tipo_intervento=tipo_intervento, meta=meta, answers=answers,
        parametri_overrides=parametri_overrides, rooms=rooms, openings=openings,
        structural_elements=structural_elements, footprint_area_m2=footprint_area_m2,
        roof_area_m2=roof_area_m2, rooms_sdf=rooms_sdf, confronto=confronto,
        note_metodologiche=note_metodologiche, validation_messages=validation_messages,
        db_path=db_path, prezzario_id=prezzario_id, capitolato_text=capitolato_text,
        perimetro_esterno_m=perimetro_esterno_m,
        piscina_area_m2=piscina_area_m2, piscina_perimetro_m=piscina_perimetro_m,
        piscina_lunghezza_m=piscina_lunghezza_m, piscina_larghezza_m=piscina_larghezza_m,
        acustica_materiali=acustica_materiali,
    )
    final = build_files_from_voci(
        voci=computed.voci, meta=meta, note_metodologiche=computed.note_metodologiche,
        validation_messages=validation_messages, confronto=confronto,
        excel_out=excel_out, primus_out=primus_out, word_out=word_out,
    )
    result = computed
    result.excel_path = final.excel_path
    result.primus_path = final.primus_path
    result.word_path = final.word_path
    result.totale = final.totale
    return result


def run_pipeline(
    tipo_intervento: str,
    pdf_progetto_path: str,
    db_path: str,
    meta: ProjectMeta,
    answers: dict[str, str],
    parametri_overrides: dict[str, float],
    pdf_stato_di_fatto_path: str | None = None,
    pdf_strutturale_path: str | None = None,
    pdf_copertura_path: str | None = None,
    capitolato_text: str | None = None,
    prezzario_id: int | None = None,
    legend_page: int | None = 1,
    structural_legend_page: int | None = 1,
    excel_out: str = "computo.xlsx",
    primus_out: str = "elenco_prezzi_primus.xlsx",
    word_out: str = "computo.docx",
    acustica_materiali: list[str] | None = None,
) -> PipelineResult:
    """Esegue estrazione e generazione in un solo passaggio (senza il
    passaggio di verifica intermedio): usata dai test e da chi non ha
    bisogno di rivedere i vani rilevati prima di generare il computo."""
    extraction = extract_quantities(
        tipo_intervento=tipo_intervento,
        pdf_progetto_path=pdf_progetto_path,
        pdf_stato_di_fatto_path=pdf_stato_di_fatto_path,
        pdf_strutturale_path=pdf_strutturale_path,
        pdf_copertura_path=pdf_copertura_path,
        legend_page=legend_page,
        structural_legend_page=structural_legend_page,
    )
    if not extraction.ok:
        return PipelineResult(ok=False, errors=extraction.errors, validations=extraction.validations)

    return build_from_quantities(
        tipo_intervento=tipo_intervento,
        meta=meta, answers=answers, parametri_overrides=parametri_overrides,
        rooms=extraction.rooms, openings=extraction.openings,
        structural_elements=extraction.structural_elements,
        footprint_area_m2=extraction.footprint_area_m2, roof_area_m2=extraction.roof_area_m2,
        rooms_sdf=extraction.rooms_sdf, confronto=extraction.confronto,
        note_metodologiche=extraction.note_metodologiche,
        validation_messages=extraction.validation_messages,
        db_path=db_path, prezzario_id=prezzario_id,
        excel_out=excel_out, primus_out=primus_out, word_out=word_out,
        capitolato_text=capitolato_text,
        perimetro_esterno_m=extraction.perimetro_esterno_m,
        piscina_area_m2=extraction.piscina_area_m2, piscina_perimetro_m=extraction.piscina_perimetro_m,
        piscina_lunghezza_m=extraction.piscina_lunghezza_m, piscina_larghezza_m=extraction.piscina_larghezza_m,
        acustica_materiali=acustica_materiali,
    )
