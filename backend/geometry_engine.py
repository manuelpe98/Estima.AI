"""Motore di rilievo quantità da un PDF vettoriale in scala e quotato.

Nota di progetto (richiesta esplicitamente da Franco): il riconoscimento dei
vani NON si basa sullo spessore delle linee. Distinguere i muri in base al
peso penna è fragile, perché la convenzione varia da studio a studio e da
esportazione a esportazione (spessori dati per stile grafico, non per
semantica dell'elemento) — usarlo come criterio avrebbe reso il rilievo
inaffidabile proprio sui disegni reali che dovrà leggere. Al suo posto si usa
un criterio topologico: per ogni etichetta di vano si cerca, tra TUTTI i
poligoni chiusi del disegno, quello più piccolo che la contiene e la cui
superficie reale è in un intervallo plausibile per un vano abitativo — questo
generalizza meglio a stili di disegno diversi.

Ambito: da pianta e sezioni quotate si ricavano superfici/perimetri dei vani,
sedime dell'edificio (per gli scavi), superficie di copertura e conteggio di
elementi puntuali taggati con sigla + abaco (porte, finestre, pilastri,
travi). Quantità strutturali esecutive (armature di dettaglio, fondazioni
speciali) restano fuori da questo MVP e sono trattate come stime parametriche
dichiarate come tali.
"""
from __future__ import annotations
import re
import fitz
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from .models import RoomQuantity, OpeningQuantity, TaggedElement

PT_TO_PAPER_MM = 25.4 / 72.0

ROOM_LABEL_HINTS = [
    "SOGGIORNO", "CUCINA", "CAMERA", "BAGNO", "STUDIO", "INGRESSO", "RIPOSTIGLIO",
    "CORRIDOIO", "DISIMPEGNO", "TERRAZZO", "BALCONE", "LAVANDERIA", "GARAGE",
    "CANTINA", "SALA", "TAVERNA", "COPERTURA", "TETTO",
]
MIN_ROOM_AREA_M2 = 0.8
MAX_ROOM_AREA_M2 = 400.0

TAG_CODE_RE = re.compile(r"^([A-Z]{1,3})\s*0*([0-9]+)$")


def pt_to_m(length_pt: float, scale_denominator: int) -> float:
    return length_pt * PT_TO_PAPER_MM * scale_denominator / 1000.0


def sqpt_to_m2(area_sqpt: float, scale_denominator: int) -> float:
    factor = PT_TO_PAPER_MM * scale_denominator / 1000.0
    return area_sqpt * (factor ** 2)


def _polygons_from_drawing(drawing: dict) -> list[Polygon]:
    """Estrae tutti i poligoni chiusi rappresentabili in un singolo 'drawing'
    (che può contenere più sotto-percorsi, es. un rettangolo con un foro)."""
    polys = []
    for item in drawing.get("items", []):
        if item[0] == "re":
            rect = item[1]
            polys.append(Polygon([(rect.x0, rect.y0), (rect.x1, rect.y0),
                                   (rect.x1, rect.y1), (rect.x0, rect.y1)]))
    if polys:
        return polys
    points = []
    for item in drawing.get("items", []):
        if item[0] == "l":
            p1, p2 = item[1], item[2]
            if not points:
                points.append((p1.x, p1.y))
            points.append((p2.x, p2.y))
    if len(points) >= 4:
        try:
            poly = Polygon(points)
            if poly.is_valid and poly.area > 0:
                return [poly]
        except Exception:
            return []
    return []


def _all_closed_polygons(page: "fitz.Page") -> list[Polygon]:
    """Tutti i poligoni chiusi del disegno, senza filtrare per spessore linea
    o tipo (stroke/fill): il riconoscimento del vano avviene a valle, per
    contenimento dell'etichetta e plausibilità della superficie."""
    out = []
    for d in page.get_drawings():
        out.extend(_polygons_from_drawing(d))
    return out


def _text_spans(page: "fitz.Page") -> list[dict]:
    spans = []
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text:
                    spans.append({"text": text, "bbox": span["bbox"]})
    return spans


def _bbox_center(bbox):
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def extract_rooms(doc: "fitz.Document", scale_denominator: int, plan_page: int = 0) -> list[RoomQuantity]:
    page = doc[plan_page]
    polygons = _all_closed_polygons(page)
    spans = _text_spans(page)
    room_labels = [
        s for s in spans
        if any(hint in s["text"].upper() for hint in ROOM_LABEL_HINTS)
    ]

    rooms: list[RoomQuantity] = []
    for s in room_labels:
        cx, cy = _bbox_center(s["bbox"])
        point = Point(cx, cy)
        candidates = []
        for poly in polygons:
            if not poly.contains(point):
                continue
            area_m2 = sqpt_to_m2(poly.area, scale_denominator)
            if MIN_ROOM_AREA_M2 <= area_m2 <= MAX_ROOM_AREA_M2:
                candidates.append((area_m2, poly))
        if not candidates:
            continue
        # il poligono più piccolo che contiene l'etichetta è il vano stesso
        # (poligoni più grandi che la contengono sono il perimetro edificio,
        # gruppi di vani, ecc.)
        area_m2, best_poly = min(candidates, key=lambda t: t[0])
        perim_m = pt_to_m(best_poly.length, scale_denominator)
        rooms.append(RoomQuantity(label=s["text"], area_m2=round(area_m2, 2),
                                   perimeter_m=round(perim_m, 2)))
    return rooms


def extract_building_footprint_m2(rooms_polygons: list[Polygon], scale_denominator: int) -> float:
    """Stima il sedime dell'edificio come inviluppo convesso dell'unione dei
    vani rilevati. È un'approssimazione (sovrastima per edifici molto
    articolati, sottostima lo spessore dei muri perimetrali): utile per una
    stima preliminare del volume di scavo, da verificare per sagome complesse."""
    if not rooms_polygons:
        return 0.0
    union = unary_union(rooms_polygons).convex_hull
    return sqpt_to_m2(union.area, scale_denominator)


def rooms_with_polygons(doc: "fitz.Document", scale_denominator: int, plan_page: int = 0
                         ) -> tuple[list[RoomQuantity], list[Polygon]]:
    """Come extract_rooms ma ritorna anche i poligoni geometrici (serve per il
    calcolo del sedime edificio)."""
    page = doc[plan_page]
    polygons = _all_closed_polygons(page)
    spans = _text_spans(page)
    room_labels = [s for s in spans if any(h in s["text"].upper() for h in ROOM_LABEL_HINTS)]

    rooms: list[RoomQuantity] = []
    room_polys: list[Polygon] = []
    for s in room_labels:
        cx, cy = _bbox_center(s["bbox"])
        point = Point(cx, cy)
        candidates = []
        for poly in polygons:
            if poly.contains(point):
                area_m2 = sqpt_to_m2(poly.area, scale_denominator)
                if MIN_ROOM_AREA_M2 <= area_m2 <= MAX_ROOM_AREA_M2:
                    candidates.append((area_m2, poly))
        if not candidates:
            continue
        area_m2, best_poly = min(candidates, key=lambda t: t[0])
        perim_m = pt_to_m(best_poly.length, scale_denominator)
        rooms.append(RoomQuantity(label=s["text"], area_m2=round(area_m2, 2),
                                   perimeter_m=round(perim_m, 2)))
        room_polys.append(best_poly)
    return rooms, room_polys


def extract_tagged_elements(
    doc: "fitz.Document",
    plan_page: int,
    legend_page: int | None,
    code_kinds: dict[str, str],
) -> list[TaggedElement]:
    """Riconosce elementi puntuali taggati con una sigla a disegno (es. 'P1',
    'F2', 'PL1', 'TR3') e ne recupera le dimensioni da un abaco su una pagina
    dedicata, se presente. `code_kinds` mappa il prefisso della sigla al tipo
    di elemento, es. {'P': 'porta', 'F': 'finestra'} oppure
    {'PL': 'pilastro', 'TR': 'trave'}.
    """
    plan_spans = _text_spans(doc[plan_page])
    counts: dict[str, int] = {}
    kinds: dict[str, str] = {}
    for s in plan_spans:
        m = TAG_CODE_RE.match(s["text"].strip().upper())
        if m and m.group(1) in code_kinds:
            code = f"{m.group(1)}{m.group(2)}"
            counts[code] = counts.get(code, 0) + 1
            kinds[code] = code_kinds[m.group(1)]

    dims: dict[str, tuple[float, float]] = {}
    if legend_page is not None and legend_page < doc.page_count:
        legend_text = doc[legend_page].get_text("text").upper().replace(" ", "")
        prefixes = "|".join(sorted(code_kinds.keys(), key=len, reverse=True))
        legend_re = re.compile(rf"(({prefixes})0*[0-9]+)\D{{0,10}}(\d{{2,4}})\s*[xX]\s*(\d{{2,4}})")
        for m in legend_re.finditer(legend_text):
            code = m.group(1)
            dims[code] = (float(m.group(3)), float(m.group(4)))

    elements = []
    for code, count in counts.items():
        w, h = dims.get(code, (None, None))
        elements.append(TaggedElement(code=code, kind=kinds[code], count=count,
                                       dim1_cm=w, dim2_cm=h))
    return elements


def extract_openings(doc: "fitz.Document", plan_page: int = 0, legend_page: int | None = None) -> list[OpeningQuantity]:
    elements = extract_tagged_elements(doc, plan_page, legend_page, {"P": "porta", "F": "finestra"})
    return [OpeningQuantity(code=e.code, kind=e.kind, count=e.count,
                             width_cm=e.dim1_cm, height_cm=e.dim2_cm) for e in elements]
