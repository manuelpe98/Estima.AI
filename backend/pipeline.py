"""Orchestrazione end-to-end: dai documenti caricati al computo metrico
estimativo completo (finiture, strutture, scavi, copertura, impianti a corpo
e, per le ristrutturazioni, confronto stato di fatto / stato di progetto)."""
from __future__ import annotations
from dataclasses import dataclass, field
import fitz

from .models import ValidationResult, ProjectMeta, RoomComparison
from .pdf_validation import validate_pdf
from .geometry_engine import (
    rooms_with_polygons, extract_openings, extract_tagged_elements,
    extract_building_footprint_m2,
)
from .capitolato_engine import missing_questions
from .parametri_engine import merge_parametri
from .confronto_engine import compare_stati
from .prezzario import db as prezzario_db
from .prezzario.matching import build_computo
from .output.excel_generator import build_excel, build_primus_export
from .output.word_generator import build_word


@dataclass
class PipelineResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    validations: dict[str, ValidationResult] = field(default_factory=dict)
    rooms: list = field(default_factory=list)
    openings: list = field(default_factory=list)
    structural_elements: list = field(default_factory=list)
    footprint_area_m2: float = 0.0
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
) -> PipelineResult:
    result = PipelineResult()
    meta.tipo_intervento = tipo_intervento
    parametri = merge_parametri(parametri_overrides)

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
    lp = legend_page if (legend_page is not None and legend_page < doc.page_count) else None
    rooms, room_polys = rooms_with_polygons(doc, v_progetto.scale_denominator, plan_page=0)
    openings = extract_openings(doc, plan_page=0, legend_page=lp)
    footprint = extract_building_footprint_m2(room_polys, v_progetto.scale_denominator)
    roof_area = _extract_roof_area(list(zip(rooms, room_polys)))
    doc.close()

    # --- Copertura dedicata, se caricata separatamente ---
    if pdf_copertura_path and v_copertura and v_copertura.is_valid:
        doc_cop = fitz.open(pdf_copertura_path)
        rooms_cop, polys_cop = rooms_with_polygons(doc_cop, v_copertura.scale_denominator, plan_page=0)
        doc_cop.close()
        area_dedicata = _extract_roof_area(list(zip(rooms_cop, polys_cop)))
        if area_dedicata == 0 and polys_cop:
            # nessuna etichetta "copertura" trovata: usa il poligono più grande della pagina come sagoma tetto
            area_dedicata = max(r.area_m2 for r in rooms_cop)
        if area_dedicata > 0:
            roof_area = area_dedicata
    if roof_area == 0.0 and footprint > 0:
        roof_area = footprint
        result.note_metodologiche = getattr(result, "note_metodologiche", [])

    # --- Stato di fatto (ristrutturazione) ---
    rooms_sdf = None
    if pdf_stato_di_fatto_path and v_sdf and v_sdf.is_valid:
        doc_sdf = fitz.open(pdf_stato_di_fatto_path)
        rooms_sdf, _ = rooms_with_polygons(doc_sdf, v_sdf.scale_denominator, plan_page=0)
        doc_sdf.close()
        result.confronto = compare_stati(rooms_sdf, rooms)

    # --- Elementi strutturali ---
    structural_elements = []
    if pdf_strutturale_path and v_strutturale and v_strutturale.is_valid:
        doc_s = fitz.open(pdf_strutturale_path)
        slp = structural_legend_page if (structural_legend_page is not None and structural_legend_page < doc_s.page_count) else None
        structural_elements = extract_tagged_elements(
            doc_s, plan_page=0, legend_page=slp, code_kinds={"PL": "pilastro", "TR": "trave"},
        )
        doc_s.close()

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
        footprint_area_m2=footprint, structural_elements=structural_elements,
        roof_area_m2_plan=roof_area, rooms_sdf=rooms_sdf,
    )

    build_excel(righe, meta, excel_out)
    build_primus_export(righe, meta, primus_out)
    all_validation_messages = []
    for v in result.validations.values():
        all_validation_messages.extend(v.messages)
    build_word(righe, meta, note, all_validation_messages, word_out, confronto=result.confronto)

    result.rooms = rooms
    result.openings = openings
    result.structural_elements = structural_elements
    result.footprint_area_m2 = round(footprint, 2)
    result.roof_area_m2 = round(roof_area, 2)
    result.questions_asked = questions
    result.voci = righe
    result.note_metodologiche = note
    result.excel_path = excel_out
    result.primus_path = primus_out
    result.word_path = word_out
    result.totale = round(sum(v.importo for v in righe), 2)
    return result
