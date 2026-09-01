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
from shapely.geometry import Polygon, Point, LineString, MultiLineString
from shapely.ops import unary_union, polygonize
from .models import RoomQuantity, OpeningQuantity, TaggedElement

PT_TO_PAPER_MM = 25.4 / 72.0

ROOM_LABEL_HINTS = [
    "SOGGIORNO", "CUCINA", "CAMERA", "BAGNO", "STUDIO", "INGRESSO", "RIPOSTIGLIO",
    "CORRIDOIO", "DISIMPEGNO", "TERRAZZO", "BALCONE", "LAVANDERIA", "GARAGE",
    "AUTORIMESSA", "LOCALE TECNICO", "CANTINA", "SALA", "TAVERNA", "COPERTURA", "TETTO",
    "PISCINA",
]
# Le etichette di vano vengono cercate per intera parola (\b...\b), non come
# semplice sottostringa: altrimenti hint corti come "STUDIO" combaciano anche
# dentro testi non pertinenti (es. l'indirizzo email nel cartiglio del
# disegno, "...@studiope.it", contiene letteralmente "studio").
_ROOM_LABEL_PATTERNS = [re.compile(rf"\b{re.escape(h)}\b") for h in ROOM_LABEL_HINTS]
# Le vere etichette di vano sono di solito diciture brevi (1-3 parole): un
# testo più lungo che contiene comunque una delle parole chiave (es. una
# didascalia o un titolo di tavola) non viene considerato un'etichetta di vano.
_MAX_ROOM_LABEL_LEN = 28

# Etichette per cui "il poligono più piccolo che contiene il punto" NON è il
# criterio giusto: la falda di un tetto è spesso disegnata con linee interne
# (colmi/displuvi) che la spezzerebbero in facce più piccole della ricostruzione
# planare, ma "copertura"/"tetto" indica sempre l'intera falda/il contorno
# esterno, non una sua sotto-porzione. Per questa etichetta si usa quindi solo
# il percorso già chiuso nel disegno (o, in mancanza, la faccia planare più
# GRANDE che contiene il punto, non la più piccola). La piscina invece segue
# la regola normale (poligono più piccolo): a differenza della falda, il
# rischio maggiore lì non è una sotto-porzione più piccola (es. gradino di
# risalita), ma un contorno enorme e sbagliato (es. il riquadro dell'intera
# vista di disegno), quindi va evitato il MASSIMO, non il minimo.
ROOF_LABEL_HINTS = ("COPERTURA", "TETTO")
_LARGEST_POLY_LABEL_HINTS = ROOF_LABEL_HINTS
# Sotto questa superficie un'etichetta "PISCINA" non è la vasca esterna ma più
# probabilmente il locale tecnico/filtrazione ("locale piscina"): resta un
# vano normale, non viene isolata come piscina.
MIN_PISCINA_AREA_M2 = 10.0

MIN_ROOM_AREA_M2 = 0.8
MAX_ROOM_AREA_M2 = 400.0

TAG_CODE_RE = re.compile(r"^([A-Z]{1,3})\s*0*([0-9]+)$")


def _is_room_label(text: str) -> bool:
    if len(text) > _MAX_ROOM_LABEL_LEN:
        return False
    upper = text.upper()
    return any(p.search(upper) for p in _ROOM_LABEL_PATTERNS)


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


def _planar_faces(page: "fitz.Page") -> list[Polygon]:
    """Ricostruisce le aree chiuse (facce) formate dall'INTERO reticolo di
    segmenti del disegno (muri, soglie, ecc.), non solo i percorsi già chiusi
    singolarmente. È necessario perché molti export CAD reali disegnano le
    pareti come tanti segmenti/rettangoli separati (uno per muro) invece che
    come un unico contorno chiuso per ciascun vano: in quel caso il vano
    esiste solo come spazio VUOTO delimitato da più elementi, non come un
    singolo oggetto vettoriale chiuso. Si raccolgono tutti i segmenti
    (incluse le rette di rettangoli e le corde delle curve), si "nodano" con
    un'unione geometrica e si poligonalizza il risultato per ottenere le
    facce chiuse del disegno."""
    segments: list[LineString] = []
    for d in page.get_drawings():
        for item in d.get("items", []):
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                if (p1.x, p1.y) != (p2.x, p2.y):
                    segments.append(LineString([(p1.x, p1.y), (p2.x, p2.y)]))
            elif op == "re":
                r = item[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
                for i in range(4):
                    segments.append(LineString([pts[i], pts[i + 1]]))
            elif op == "c":
                p1, p4 = item[1], item[4]
                if (p1.x, p1.y) != (p4.x, p4.y):
                    segments.append(LineString([(p1.x, p1.y), (p4.x, p4.y)]))
    if not segments:
        return []
    try:
        noded = unary_union(MultiLineString(segments))
        return [f for f in polygonize(noded) if f.is_valid and f.area > 0]
    except Exception:
        return []


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


def _candidates_at_point(polygons: list[Polygon], point: Point, scale_denominator: int
                          ) -> list[tuple[float, Polygon]]:
    out = []
    for poly in polygons:
        if not poly.contains(point):
            continue
        area_m2 = sqpt_to_m2(poly.area, scale_denominator)
        if MIN_ROOM_AREA_M2 <= area_m2 <= MAX_ROOM_AREA_M2:
            out.append((area_m2, poly))
    return out


def _extract_rooms_impl(page: "fitz.Page", scale_denominator: int
                         ) -> tuple[list[RoomQuantity], list[Polygon]]:
    # Si combinano SEMPRE due fonti di poligoni candidati per ogni etichetta:
    # (1) i percorsi GIA' chiusi nel disegno (preciso, funziona per la
    # maggior parte dei disegni), e (2) le facce ricostruite dall'intero
    # reticolo di segmenti (necessario per gli export CAD dettagliati dove il
    # vano non è un unico oggetto chiuso ma lo spazio tra più muri separati).
    # NON basta usare (2) solo quando (1) non trova nulla: su un disegno reale
    # può capitare che (1) trovi COMUNQUE un candidato — tipicamente il solo
    # perimetro esterno dell'edificio, se quello è disegnato come un'unica
    # polilinea chiusa mentre le pareti interne sono segmenti separati — e in
    # quel caso fermarsi al primo risultato non vuoto assegnerebbe a TUTTI i
    # vani interni la stessa area (l'intero edificio) invece della loro area
    # reale. Si prende quindi sempre il poligono più piccolo che contiene
    # l'etichetta tra ENTRAMBE le fonti insieme (poligoni più grandi che la
    # contengono sono il perimetro edificio, gruppi di vani, ecc.).
    closed_polys = _all_closed_polygons(page)
    planar_polys = _planar_faces(page)
    spans = _text_spans(page)
    room_labels = [s for s in spans if _is_room_label(s["text"])]

    rooms: list[RoomQuantity] = []
    room_polys: list[Polygon] = []
    for s in room_labels:
        cx, cy = _bbox_center(s["bbox"])
        point = Point(cx, cy)
        is_largest_poly_label = any(h in s["text"].upper() for h in _LARGEST_POLY_LABEL_HINTS)
        if is_largest_poly_label:
            # la falda/vasca va presa per intero: percorso già chiuso se c'è,
            # altrimenti la faccia planare più GRANDE (il contorno esterno,
            # non una sotto-porzione tagliata da una linea interna).
            candidates = _candidates_at_point(closed_polys, point, scale_denominator)
            if not candidates:
                candidates = _candidates_at_point(planar_polys, point, scale_denominator)
            if not candidates:
                continue
            area_m2, best_poly = max(candidates, key=lambda t: t[0])
        else:
            candidates = (_candidates_at_point(closed_polys, point, scale_denominator)
                          + _candidates_at_point(planar_polys, point, scale_denominator))
            if not candidates:
                continue
            # il poligono più piccolo che contiene l'etichetta è il vano stesso
            # (poligoni più grandi che la contengono sono il perimetro edificio,
            # gruppi di vani, ecc.)
            area_m2, best_poly = min(candidates, key=lambda t: t[0])
        perim_m = pt_to_m(best_poly.length, scale_denominator)
        rooms.append(RoomQuantity(label=s["text"], area_m2=round(area_m2, 2),
                                   perimeter_m=round(perim_m, 2)))
        room_polys.append(best_poly)
    return rooms, room_polys


def extract_rooms(doc: "fitz.Document", scale_denominator: int, plan_page: int = 0) -> list[RoomQuantity]:
    rooms, _ = _extract_rooms_impl(doc[plan_page], scale_denominator)
    return rooms


def extract_building_footprint_m2(rooms_polygons: list[Polygon], scale_denominator: int) -> float:
    """Stima il sedime dell'edificio come unione (non inviluppo convesso) dei
    vani rilevati. È un'approssimazione per difetto (esclude corridoi/
    disimpegni non taggati e lo spessore dei muri perimetrali): utile per una
    stima preliminare del volume di scavo, da verificare sempre nel passaggio
    di revisione — specialmente se l'edificio comprende corpi separati (es.
    autorimessa staccata dal corpo principale).

    NOTA: qui si usa deliberatamente l'UNIONE dei vani, non l'inviluppo
    convesso (comportamento precedente, ora corretto): con corpi di fabbrica
    separati l'inviluppo convesso include anche l'area vuota di terreno tra i
    corpi, producendo stime enormemente sovrastimate (es. casa + autorimessa
    staccata di ~780 m² di vani rilevati -> 2149 m² di sedime convesso,
    contro i ~628 m² dell'unione reale)."""
    if not rooms_polygons:
        return 0.0
    union = unary_union(rooms_polygons)
    return sqpt_to_m2(union.area, scale_denominator)


def extract_building_perimeter_m(rooms_polygons: list[Polygon], scale_denominator: int) -> float:
    """Perimetro ESTERNO dell'edificio (il contorno dell'involucro, non la
    somma dei perimetri dei singoli vani): serve per le lavorazioni che
    riguardano solo le pareti perimetrali (es. cappotto termico esterno), a
    differenza della somma dei perimetri dei vani — usata per l'intonaco
    interno — che conta più volte ogni parete divisoria interna (corretto per
    l'intonaco, che va su entrambe le facce, ma sbagliato per una lavorazione
    che riguarda solo l'esterno). Si calcola come perimetro del contorno
    ESTERNO dell'unione dei vani (i fori interni, es. un cortile chiuso, non
    vengono sommati); se l'edificio ha corpi separati (es. autorimessa
    staccata) si sommano i perimetri esterni di ciascun corpo."""
    if not rooms_polygons:
        return 0.0
    union = unary_union(rooms_polygons)
    geoms = list(union.geoms) if hasattr(union, "geoms") else [union]
    perimetro_pt = sum(g.exterior.length for g in geoms if hasattr(g, "exterior") and g.exterior is not None)
    return pt_to_m(perimetro_pt, scale_denominator)


def _group_shared_room_polygons(room_polys: list[Polygon]) -> list[list[int]]:
    groups: list[list[int]] = []
    for i, poly in enumerate(room_polys):
        matched_group = None
        for group in groups:
            ref_poly = room_polys[group[0]]
            if poly.equals(ref_poly) or (
                ref_poly.area > 0
                and abs(poly.area - ref_poly.area) / ref_poly.area < 0.001
                and poly.symmetric_difference(ref_poly).area / ref_poly.area < 0.02
            ):
                matched_group = group
                break
        if matched_group is not None:
            matched_group.append(i)
        else:
            groups.append([i])
    return groups


def merge_shared_rooms(rooms: list[RoomQuantity], room_polys: list[Polygon]
                        ) -> tuple[list[RoomQuantity], list[Polygon], list[str]]:
    """Vani diversi a cui è stato associato lo STESSO poligono disegnato
    (superficie identica) vengono uniti in UN'UNICA voce con etichetta
    combinata (es. 'CUCINA/SOGGIORNO'): è il caso tipico di un ambiente a
    pianta aperta senza parete divisoria, dove il rilievo topologico non ha
    modo di sapere dove tracciare un confine perché nel disegno — e nella
    realtà — quel confine non esiste. Per richiesta esplicita dell'utente
    questo NON è trattato come un errore da correggere a mano: il computo
    riporta direttamente la voce unita, con una nota di trasparenza (non un
    avviso) che spiega l'unione."""
    notes: list[str] = []
    groups = _group_shared_room_polygons(room_polys)

    merged_rooms: list[RoomQuantity] = []
    merged_polys: list[Polygon] = []
    for group in groups:
        if len(group) < 2:
            i = group[0]
            merged_rooms.append(rooms[i])
            merged_polys.append(room_polys[i])
            continue
        labels_originali = [rooms[i].label.strip().rstrip("/").strip() for i in group]
        # rimuove eventuali duplicati mantenendo l'ordine di apparizione
        labels_univoche = list(dict.fromkeys(labels_originali))
        combined_label = "/".join(labels_univoche)
        ref = rooms[group[0]]
        merged_rooms.append(RoomQuantity(
            label=combined_label, area_m2=ref.area_m2, perimeter_m=ref.perimeter_m,
            source="rilevata da poligono disegno (ambiente open space, vani uniti)",
        ))
        merged_polys.append(room_polys[group[0]])
        notes.append(
            f"Vani a pianta aperta uniti in un'unica voce di computo: {', '.join(f'{l!r}' for l in labels_univoche)} "
            f"condividevano la stessa area disegnata ({ref.area_m2} m², senza parete divisoria), quindi nel computo "
            f"compaiono come voce unica '{combined_label}' invece che come vani separati."
        )
    return merged_rooms, merged_polys, notes


def _min_rect_dims_m(poly: Polygon, scale_denominator: int) -> tuple[float, float]:
    """Lunghezza e larghezza (lunghezza >= larghezza) del rettangolo minimo
    che contiene il poligono, in metri. Usato per la piscina: quasi sempre di
    forma rettangolare, "8.00 x 4.00 m" si legge e si verifica molto più
    facilmente di un solo valore di perimetro."""
    try:
        rect = poly.minimum_rotated_rectangle
        coords = list(rect.exterior.coords)
    except Exception:
        return 0.0, 0.0
    if len(coords) < 3:
        return 0.0, 0.0
    lato1_pt = Point(coords[0]).distance(Point(coords[1]))
    lato2_pt = Point(coords[1]).distance(Point(coords[2]))
    lati_m = sorted([pt_to_m(lato1_pt, scale_denominator), pt_to_m(lato2_pt, scale_denominator)], reverse=True)
    return round(lati_m[0], 2), round(lati_m[1], 2)


def extract_piscina(rooms: list[RoomQuantity], room_polys: list[Polygon], scale_denominator: int
                     ) -> tuple[RoomQuantity | None, list[RoomQuantity], list[Polygon], float, float]:
    """Se una piscina è indicata in pianta (etichetta 'PISCINA'), la separa
    dall'elenco dei vani normali: non deve contribuire a pavimenti/pareti/
    impianti dei locali interni, ma va computata a parte (scavo, vasca,
    impermeabilizzazione, bordo). Un'etichetta 'PISCINA' con superficie sotto
    MIN_PISCINA_AREA_M2 è più probabilmente il locale tecnico/filtrazione
    ('locale piscina') e resta un vano normale. Se ci sono più etichette
    'PISCINA' plausibili (es. ripetuta in punti diversi del disegno), si
    prende la più grande come vasca e le altre restano vani normali.

    Oltre al vano piscina, ritorna anche lunghezza e larghezza (m) del
    rettangolo minimo che contiene la vasca: più leggibili del perimetro per
    chi rivede il computo (richiesta esplicita di Franco)."""
    candidate_idx = [i for i, r in enumerate(rooms)
                      if "PISCINA" in r.label.upper() and r.area_m2 >= MIN_PISCINA_AREA_M2]
    if not candidate_idx:
        return None, rooms, room_polys, 0.0, 0.0
    best_idx = max(candidate_idx, key=lambda i: rooms[i].area_m2)
    piscina = rooms[best_idx]
    lunghezza_m, larghezza_m = _min_rect_dims_m(room_polys[best_idx], scale_denominator)
    altri_idx = [i for i in range(len(rooms)) if i != best_idx]
    return piscina, [rooms[i] for i in altri_idx], [room_polys[i] for i in altri_idx], lunghezza_m, larghezza_m


def rooms_with_polygons(doc: "fitz.Document", scale_denominator: int, plan_page: int = 0
                         ) -> tuple[list[RoomQuantity], list[Polygon]]:
    """Come extract_rooms ma ritorna anche i poligoni geometrici (serve per il
    calcolo del sedime edificio)."""
    return _extract_rooms_impl(doc[plan_page], scale_denominator)


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


# --- Rilievo porte/finestre dalle quote di varco (senza sigla + abaco) -----
#
# Molti disegni reali NON usano sigle tipo "F1"/"P1" con abaco a parte (il
# rilievo tramite extract_openings/extract_tagged_elements in quel caso non
# trova nulla): riportano invece, accanto a ogni varco nel muro, due quote —
# larghezza in cm e, sotto, altezza in cm seguita da "h" (es. "80" / "210h")
# — esattamente come le altre quote della pianta. Verificato su un disegno
# reale (Studio Pè) confrontando visivamente ogni etichetta con il simbolo
# disegnato: le altezze osservate si dividono nettamente in due gruppi, "210h"
# e "230h" — sempre affiancate dal simbolo ad arco dell'anta porta — contro
# "150h" e "250h" — sempre un varco vetrato senza arco — e i valori
# corrispondono esattamente alle superfici "finestrata" riportate nella
# tabella dei rapporti aeroilluminanti dello stesso disegno.
OPENING_WIDTH_RANGE_CM = (50, 700)
OPENING_HEIGHT_RANGE_CM = (40, 300)
# Intervallo tipico dell'altezza di un'anta porta (interna, ingresso o
# carraia): un'altezza di varco fuori da questo intervallo (tipicamente più
# bassa, con davanzale, o un vetro a tutta altezza) è considerata finestra.
DOOR_HEIGHT_RANGE_CM = (195, 235)
_OPENING_HEIGHT_RE = re.compile(r"^(\d{2,4})[Hh]$")
_OPENING_WIDTH_RE = re.compile(r"^\d{2,4}$")
_OPENING_MAX_PAIR_DIST_PT = 20.0  # la coppia larghezza/altezza è sempre a pochi punti di distanza


def extract_dimensioned_openings(page: "fitz.Page") -> list[OpeningQuantity]:
    """Rileva porte e finestre dalle quote larghezza/altezza scritte accanto
    a ogni varco in pianta (vedi nota sopra), senza bisogno di un abaco con
    sigle. Ogni etichetta larghezza+altezza corrisponde a un varco realmente
    disegnato: aperture con la stessa larghezza e altezza vengono contate
    insieme in un'unica voce."""
    d = page.get_text("dict")
    height_spans: list[tuple[int, float, float]] = []
    width_spans: list[tuple[int, float, float]] = []
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            joined = "".join(s["text"] for s in spans).strip()
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            m = _OPENING_HEIGHT_RE.match(joined)
            if m:
                val = int(m.group(1))
                if OPENING_HEIGHT_RANGE_CM[0] <= val <= OPENING_HEIGHT_RANGE_CM[1]:
                    height_spans.append((val, cx, cy))
            elif _OPENING_WIDTH_RE.match(joined):
                val = int(joined)
                if OPENING_WIDTH_RANGE_CM[0] <= val <= OPENING_WIDTH_RANGE_CM[1]:
                    width_spans.append((val, cx, cy))

    used_widths: set[int] = set()
    counts: dict[tuple[str, int, int], int] = {}
    for h_val, hx, hy in height_spans:
        best_idx = None
        best_dist = None
        for idx, (w_val, wx, wy) in enumerate(width_spans):
            if idx in used_widths:
                continue
            dist = ((wx - hx) ** 2 + (wy - hy) ** 2) ** 0.5
            if dist <= _OPENING_MAX_PAIR_DIST_PT and (best_dist is None or dist < best_dist):
                best_dist, best_idx = dist, idx
        if best_idx is None:
            continue
        used_widths.add(best_idx)
        w_val = width_spans[best_idx][0]
        kind = "porta" if DOOR_HEIGHT_RANGE_CM[0] <= h_val <= DOOR_HEIGHT_RANGE_CM[1] else "finestra"
        key = (kind, w_val, h_val)
        counts[key] = counts.get(key, 0) + 1

    openings: list[OpeningQuantity] = []
    for (kind, w_val, h_val), count in sorted(counts.items(), key=lambda kv: (kv[0][0], -kv[0][1], -kv[0][2])):
        prefix = "P" if kind == "porta" else "F"
        openings.append(OpeningQuantity(
            code=f"{prefix}-{w_val}x{h_val}", kind=kind, count=count,
            width_cm=float(w_val), height_cm=float(h_val),
            source="quote larghezza/altezza lette in pianta (senza abaco)",
        ))
    return openings
