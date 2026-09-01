"""Abbina quantità rilevate (vani, aperture, strutture, copertura, sedime) +
risposte capitolato + parametri numerici alle voci di prezzario, producendo
le righe del computo metrico estimativo."""
from __future__ import annotations
import math
from ..models import RoomQuantity, OpeningQuantity, TaggedElement, ComputoVoce

BAGNO_CUCINA_HINTS = ["BAGNO", "CUCINA"]

CATEGORIA_LABELS = {
    "pavimenti": "Pavimenti",
    "pareti_interne": "Pareti interne",
    "serramenti_esterni": "Serramenti esterni",
    "porte_interne": "Porte interne",
    "impianto_elettrico": "Impianto elettrico",
    "impianto_idrico": "Impianto idrico-sanitario",
    "scavi": "Scavi",
    "strutture_cls": "Strutture in elevazione (calcestruzzo)",
    "strutture_ferro": "Strutture in elevazione (acciaio)",
    "strutture_muratura": "Strutture in elevazione (muratura portante)",
    "copertura": "Copertura",
    "demolizioni": "Demolizioni",
    "fondazioni": "Fondazioni",
    "solai": "Solai",
    "cappotto_termico": "Cappotto termico esterno",
    "impermeabilizzazioni": "Impermeabilizzazioni",
    "impianti_a_corpo": "Impianti (a corpo)",
    "piscina_vasca": "Piscina — vasca strutturale",
    "piscina_bordo": "Piscina — bordo perimetrale",
    "scala_esterna": "Scala esterna",
    "opere_esterne": "Opere esterne e sottoservizi",
    "cantiere": "Approntamento di cantiere",
    "spinottature": "Spinottature",
    "vespaio": "Vespaio aerato",
    "contropareti": "Contropareti interne",
    "pareti_divisorie": "Pareti divisorie interne",
    "velette": "Velette",
    "assistenza_muraria": "Assistenza muraria",
    "controsoffitti": "Controsoffitti",
    "acustica": "Materiali per requisiti acustici",
}


def _find_voce(voci: list[dict], categoria: str, sotto_tipo: str) -> dict | None:
    for v in voci:
        if v["categoria"] == categoria and v["sotto_tipo"] == sotto_tipo:
            return v
    return None


def _find_voce_con_dettaglio(voci: list[dict], categoria: str, sotto_tipo: str,
                              answers: dict[str, str], domanda_id: str) -> dict | None:
    """Come _find_voce, ma quando l'utente ha scelto "Altro (specificare a parte)"
    e ha scritto un dettaglio nella relativa casella di testo, lo riporta nella
    descrizione della voce generata (la voce di prezzo resta quella generica
    segnaposto, da correggere manualmente con il prezzo reale)."""
    v = _find_voce(voci, categoria, sotto_tipo)
    if v and sotto_tipo.startswith("Altro"):
        dettaglio = (answers.get(f"{domanda_id}_dettaglio") or "").strip()
        if dettaglio:
            v = dict(v)
            v["descrizione"] = f"{v['descrizione']} — indicato dall'utente: {dettaglio}"
    return v


def build_computo(
    rooms: list[RoomQuantity],
    openings: list[OpeningQuantity],
    answers: dict[str, str],
    parametri: dict[str, float],
    voci: list[dict],
    footprint_area_m2: float = 0.0,
    structural_elements: list[TaggedElement] | None = None,
    roof_area_m2_plan: float = 0.0,
    rooms_sdf: list[RoomQuantity] | None = None,
    perimetro_esterno_m: float = 0.0,
    piscina_area_m2: float = 0.0,
    piscina_perimetro_m: float = 0.0,
    piscina_lunghezza_m: float = 0.0,
    piscina_larghezza_m: float = 0.0,
    acustica_materiali: list[str] | None = None,
) -> tuple[list[ComputoVoce], list[str]]:
    righe: list[ComputoVoce] = []
    note: list[str] = []
    n = 1

    def add(v, quantita, note_riga):
        nonlocal n
        if v is None or quantita <= 0:
            return
        categoria_label = CATEGORIA_LABELS.get(v["categoria"], v["categoria"].replace("_", " ").capitalize())
        righe.append(ComputoVoce(n, v["codice"], categoria_label,
                                  v["descrizione"], v["unita_misura"], round(quantita, 2),
                                  v["prezzo"], note=note_riga))
        n += 1

    def add_placeholder(v, note_riga):
        # Come add(), ma per una voce che va SEMPRE elencata anche se il sistema
        # non può calcolarne la quantità: quantità e prezzo restano a 0 e la riga
        # è marcata da_completare, per essere evidenziata nei file generati e
        # completata a mano invece di mancare silenziosamente dal computo.
        nonlocal n
        if v is None:
            return
        categoria_label = CATEGORIA_LABELS.get(v["categoria"], v["categoria"].replace("_", " ").capitalize())
        righe.append(ComputoVoce(n, v["codice"], categoria_label,
                                  v["descrizione"], v["unita_misura"], 0.0,
                                  0.0, note=note_riga, da_completare=True))
        n += 1

    pav_tipo = answers.get("pavimenti", "Altro (specificare a parte)")
    par_tipo = answers.get("pareti_interne", "Altro (specificare a parte)")
    ser_tipo = answers.get("serramenti_esterni", "Altro (specificare a parte)")
    por_tipo = answers.get("porte_interne", "Altro (specificare a parte)")
    ele_tipo = answers.get("impianto_elettrico", "Altro (specificare a parte)")
    idr_tipo = answers.get("impianto_idrico", "Altro (specificare a parte)")
    strut_tipo = answers.get("tipo_struttura", "Cemento armato (pilastri e travi)")
    cop_tipo = answers.get("copertura_tipo", "Altro (specificare a parte)")
    cap_tipo = answers.get("cappotto_termico", "Altro (specificare a parte)")
    tipo_solaio = answers.get("tipo_solaio", "Laterocemento (pacchetto completo)")
    tipo_pareti_div = answers.get("tipo_pareti_divisorie", "Già esistenti / non richieste in questo intervento")
    contropareti_si = answers.get("richiede_contropareti", "No") == "Sì"
    vespaio_si = answers.get("vespaio_aerato", "No") == "Sì"
    velette_si = answers.get("velette", "No") == "Sì"
    controsoffitti_si = answers.get("controsoffitti", "No") == "Sì"

    altezza_interna = parametri.get("altezza_interna_m", 2.70)
    altezza_interpiano = parametri.get("altezza_interpiano_strutturale_m", 3.00)
    profondita_scavo = parametri.get("profondita_scavo_m", 1.20)
    spessore_muro_m = parametri.get("spessore_muro_portante_cm", 30.0) / 100.0
    lunghezza_trave = parametri.get("lunghezza_media_travi_m", 4.00)
    incidenza_acciaio = parametri.get("incidenza_acciaio_kg_m3", 100.0)
    angolo_falda = parametri.get("angolo_falda_gradi", 25.0)
    spessore_fondazione_m = parametri.get("spessore_fondazione_m", 0.50)
    spessore_solaio_cm = parametri.get("spessore_solaio_cm", 25.0)
    spessore_cappotto_cm = parametri.get("spessore_cappotto_cm", 12.0)
    incidenza_impianti_pct = parametri.get("incidenza_impianti_pct", 18.0)
    profondita_piscina = parametri.get("profondita_piscina_m", 1.50)
    larghezza_bordo_piscina = parametri.get("larghezza_bordo_piscina_m", 1.00)
    costo_cantiere = parametri.get("costo_approntamento_cantiere_eur", 15000.0)
    spessore_magrone_m = parametri.get("spessore_magrone_cm", 10.0) / 100.0
    fattore_casseratura_fnd = parametri.get("fattore_casseratura_fondazioni", 2.0)
    incidenza_acciaio_fnd = parametri.get("incidenza_acciaio_fondazioni_kg_m3", 80.0)
    incidenza_acciaio_sol = parametri.get("incidenza_acciaio_solaio_kg_m3", 90.0)
    costo_bagno_chimico = parametri.get("costo_nolo_bagno_chimico_eur", 900.0)
    incidenza_assistenza_ele = parametri.get("incidenza_assistenza_elettrico_pct", 2.0)
    incidenza_assistenza_idr = parametri.get("incidenza_assistenza_idraulico_pct", 2.0)

    # --- Finiture (pavimenti, pareti, serramenti, porte) ---
    tot_area_pav = sum(r.area_m2 for r in rooms)
    add(_find_voce_con_dettaglio(voci, "pavimenti", pav_tipo, answers, "pavimenti"), tot_area_pav,
        f"Somma superfici di {len(rooms)} vani rilevati da pianta")

    tot_perimetro = sum(r.perimeter_m for r in rooms)
    superficie_pareti = tot_perimetro * altezza_interna
    add(_find_voce_con_dettaglio(voci, "pareti_interne", par_tipo, answers, "pareti_interne"), superficie_pareti,
        f"Perimetro vani ({round(tot_perimetro,2)} m) x altezza interna {altezza_interna} m, "
        "al lordo di porte/finestre (non detratte in questa versione)")
    if superficie_pareti > 0:
        note.append(
            f"La superficie delle pareti interne è stimata con altezza interna di {altezza_interna} m "
            "(parametro confermato dall'utente) e non detrae l'ingombro di porte e finestre."
        )

    # --- Pareti divisorie interne (costruzione, distinta dalla finitura sopra) ---
    # Lunghezza delle pareti divisorie stimata come (perimetro totale dei vani − perimetro
    # esterno dell'involucro) / 2: le pareti condivise tra due vani vengono contate due
    # volte nella somma dei perimetri dei singoli vani (una volta per ciascun vano
    # adiacente), mentre le pareti perimetrali una volta sola — sottraendo il perimetro
    # esterno e dividendo per due si isola quindi la lunghezza reale delle sole pareti
    # divisorie interne (approssimazione geometrica, da verificare).
    lunghezza_pareti_divisorie = max(0.0, (tot_perimetro - perimetro_esterno_m) / 2.0)
    if lunghezza_pareti_divisorie > 0 and not tipo_pareti_div.startswith("Già esistenti"):
        area_pareti_divisorie = lunghezza_pareti_divisorie * altezza_interna
        add(_find_voce_con_dettaglio(voci, "pareti_divisorie", tipo_pareti_div, answers, "tipo_pareti_divisorie"),
            area_pareti_divisorie,
            f"Lunghezza pareti divisorie stimata (perimetro vani {round(tot_perimetro,2)} m − perimetro esterno "
            f"{round(perimetro_esterno_m,2)} m) / 2 = {round(lunghezza_pareti_divisorie,2)} m, x altezza interna "
            f"{altezza_interna} m")
        note.append(
            "La lunghezza delle pareti divisorie interne è una stima geometrica ((perimetro totale dei vani − "
            "perimetro esterno) / 2), non la misura dell'asse reale dei tramezzi: va verificata sul disegno."
        )

    # --- Contropareti interne (solo se richieste dal capitolato) ---
    if contropareti_si and perimetro_esterno_m > 0:
        area_contropareti = perimetro_esterno_m * altezza_interna
        add(_find_voce(voci, "contropareti", "standard"), area_contropareti,
            f"Perimetro esterno ({round(perimetro_esterno_m,2)} m) x altezza interna ({altezza_interna} m) — "
            "stima per il rivestimento dell'intero perimetro interno, da correggere se le contropareti "
            "interessano solo alcune pareti")

    # --- Velette (solo se richieste dal capitolato: sviluppo lineare non desumibile
    # dalla pianta, sempre come voce segnaposto da completare a mano) ---
    if velette_si:
        add_placeholder(_find_voce(voci, "velette", "standard"),
                         "Richieste dal capitolato ma non misurabili dalla sola pianta (posizione e sviluppo "
                         "lineare dipendono dal progetto di dettaglio): misura e valorizza a mano")

    # --- Controsoffitti (solo se richiesti dal capitolato): il sistema non legge le
    # quote di altezza interna riportate in pianta/sezioni (formati troppo vari da
    # disegno a disegno per un riconoscimento affidabile in questa versione), quindi
    # NON sa distinguere automaticamente quali ambienti hanno un'altezza ridotta da
    # controsoffitto: propone l'intera superficie dei vani, da correggere a mano
    # per i soli ambienti effettivamente interessati. ---
    if controsoffitti_si and tot_area_pav > 0:
        add(_find_voce(voci, "controsoffitti", "standard"), tot_area_pav,
            f"Ipotesi sull'intera superficie dei vani ({round(tot_area_pav,1)} m²): il sistema non riconosce "
            "automaticamente quali ambienti hanno altezza interna ridotta da controsoffitto — correggi la "
            "quantità per i soli ambienti effettivamente interessati")
        note.append(
            "La voce controsoffitti è stata generata sull'intera superficie dei vani perché il rilievo "
            "automatico non legge le quote di altezza interna riportate in pianta/sezioni (per riconoscerle "
            "servirebbe un formato di annotazione affidabile e coerente su tutti i disegni, che al momento "
            "non è implementato): se in questo progetto il controsoffitto interessa solo alcuni ambienti "
            "(es. dove l'altezza interna è inferiore rispetto agli altri locali), correggi la quantità a mano "
            "nel passaggio di revisione."
        )

    finestre = [o for o in openings if o.kind == "finestra"]
    con_misure = [o for o in finestre if o.width_cm and o.height_cm]
    senza_misure = [o for o in finestre if not (o.width_cm and o.height_cm)]
    if con_misure:
        area_tot = sum((o.width_cm * o.height_cm / 10000.0) * o.count for o in con_misure)
        add(_find_voce_con_dettaglio(voci, "serramenti_esterni", ser_tipo, answers, "serramenti_esterni"), area_tot,
            f"{sum(o.count for o in con_misure)} finestre con dimensioni note (da abaco serramenti o da quote in pianta)")
    if senza_misure:
        count_tot = sum(o.count for o in senza_misure)
        add(_find_voce(voci, "serramenti_esterni", "__FALLBACK_NO_DIM__"), count_tot,
            "Dimensioni non trovate: prezzo indicativo a corpo")
        if count_tot:
            note.append(f"{count_tot} finestre non hanno dimensioni note (né da abaco né da quote in pianta): "
                        "valorizzate a corpo con prezzo indicativo, da correggere appena disponibili le misure reali.")

    porte = [o for o in openings if o.kind == "porta"]
    if porte:
        add(_find_voce_con_dettaglio(voci, "porte_interne", por_tipo, answers, "porte_interne"), sum(o.count for o in porte),
            f"{sum(o.count for o in porte)} porte rilevate da pianta")

    # --- Assistenza muraria per la posa di serramenti e porte (distinta dalla
    # fornitura e posa dei serramenti/porte stessi, sopra) ---
    if con_misure:
        area_assistenza_ser = sum((o.width_cm * o.height_cm / 10000.0) * o.count for o in con_misure)
        add(_find_voce(voci, "assistenza_muraria", "serramenti"), area_assistenza_ser,
            f"Stessa superficie dei {sum(o.count for o in con_misure)} serramenti con dimensioni note")
    if porte:
        add(_find_voce(voci, "assistenza_muraria", "porte"), sum(o.count for o in porte),
            f"{sum(o.count for o in porte)} porte rilevate da pianta — eventuali porte con lavorazioni "
            "particolari (porta di ingresso, porte tagliafuoco, portoni basculanti) vanno scorporate a mano "
            "con una voce dedicata a prezzo maggiorato")

    # --- Impianti: NON un rilievo dettagliato (richiesta esplicita dell'utente: gli
    # impianti restano esclusi dal computo puntuale in questa versione) — vengono
    # sommati in un'UNICA voce a corpo, alla fine, come percentuale indicativa del
    # totale di TUTTE le altre lavorazioni già computate (vedi sotto, dopo fondazioni/
    # solai/cappotto/impermeabilizzazioni/copertura/demolizioni: manca solo questa voce).

    # --- Approntamento di cantiere (a corpo, prezzo dal parametro dedicato: il costo
    # reale dipende dalla dimensione/durata del cantiere, non dalla sola pianta) ---
    if footprint_area_m2 > 0:
        v_cantiere = _find_voce(voci, "cantiere", "approntamento")
        if v_cantiere:
            v_cantiere = dict(v_cantiere)
            v_cantiere["prezzo"] = costo_cantiere
            add(v_cantiere, 1, "Voce a corpo, prezzo dal parametro 'Costo di approntamento del cantiere' "
                                "(confermato dall'utente)")
        v_bagno = _find_voce(voci, "cantiere", "bagno_chimico")
        if v_bagno:
            v_bagno = dict(v_bagno)
            v_bagno["prezzo"] = costo_bagno_chimico
            add(v_bagno, 1, "Voce a corpo, prezzo dal parametro 'Costo del nolo bagno chimico' "
                             "(confermato dall'utente)")

    # --- Scavi ---
    if footprint_area_m2 > 0:
        volume_scavo = footprint_area_m2 * profondita_scavo
        add(_find_voce(voci, "scavi", "standard"), volume_scavo,
            f"Sedime edificio {round(footprint_area_m2,1)} m² (somma dei vani rilevati in pianta) "
            f"x profondità {profondita_scavo} m")
        note.append(
            "Il sedime dell'edificio è stimato come somma delle aree dei vani rilevati in pianta: non include "
            "corridoi/disimpegni non taggati né lo spessore dei muri perimetrali (sottostima), e non tiene conto "
            "di scavi per opere accessorie non rappresentate a pianta (es. piscina, muri di contenimento, "
            "rampe/scale esterne): il volume di scavo va sempre verificato e corretto per queste voci."
        )

    # --- Fondazioni: magrone, calcestruzzo, casseforme e acciaio come voci distinte ---
    if footprint_area_m2 > 0:
        volume_fondazioni = footprint_area_m2 * spessore_fondazione_m
        volume_magrone = footprint_area_m2 * spessore_magrone_m
        add(_find_voce(voci, "fondazioni", "magrone"), volume_magrone,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x spessore magrone {spessore_magrone_m*100:.0f} cm "
            "(parametro confermato dall'utente)")
        add(_find_voce(voci, "fondazioni", "standard"), volume_fondazioni,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x spessore medio fondazioni "
            f"{spessore_fondazione_m*100:.0f} cm (parametro confermato dall'utente)")
        if perimetro_esterno_m > 0:
            area_casseforme_fnd = perimetro_esterno_m * spessore_fondazione_m * fattore_casseratura_fnd
            add(_find_voce(voci, "fondazioni", "casseforme"), area_casseforme_fnd,
                f"Perimetro esterno ({round(perimetro_esterno_m,2)} m) x altezza fondazione "
                f"({spessore_fondazione_m*100:.0f} cm) x {fattore_casseratura_fnd:.0f} facce di casseratura "
                "(parametro confermato dall'utente) — non include eventuali setti/muri di fondazione interni")
        add(_find_voce(voci, "fondazioni", "acciaio"), volume_fondazioni * incidenza_acciaio_fnd,
            f"Stima parametrica: {incidenza_acciaio_fnd:.0f} kg di acciaio per m³ di calcestruzzo di fondazione")
        add_placeholder(
            _find_voce(voci, "spinottature", "standard"),
            "Quantità dipendente dal progetto strutturale esecutivo (ripresa dei getti), non desumibile dalla "
            "sola pianta architettonica: misura e valorizza a mano"
        )
        note.append(
            "Fondazioni: magrone, calcestruzzo, casseforme e acciaio sono voci separate, calcolate con "
            "parametri dimensionali confermati dall'utente (spessori, incidenza acciaio, facce di "
            "casseratura) — non da un progetto strutturale esecutivo, che resta l'unica fonte affidabile per "
            "un computo definitivo."
        )

    # --- Vespaio aerato (solo se richiesto dal capitolato) ---
    if vespaio_si and footprint_area_m2 > 0:
        add(_find_voce(voci, "vespaio", "standard"), footprint_area_m2,
            f"Sedime edificio {round(footprint_area_m2,1)} m²")

    # --- Solai (interpiano e/o contro terra: una sola voce a superficie di sedime,
    # NON moltiplicata per il numero di piani, perché il numero di piani non è
    # dedotto in modo affidabile dai soli elaborati di pianta in questa versione).
    # Pacchetto completo (laterocemento/predalles) in un'unica voce, oppure
    # scomposto in casseforme/calcestruzzo/acciaio se il capitolato indica una
    # soletta piena gettata in opera. ---
    if footprint_area_m2 > 0 and tipo_solaio.startswith("Soletta piena"):
        volume_solaio = footprint_area_m2 * (spessore_solaio_cm / 100.0)
        add(_find_voce(voci, "solai", "casseforme"), footprint_area_m2,
            f"Sedime edificio {round(footprint_area_m2,1)} m² (superficie del getto)")
        add(_find_voce(voci, "solai", "calcestruzzo"), volume_solaio,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x spessore {spessore_solaio_cm:.0f} cm "
            "(parametro confermato dall'utente)")
        add(_find_voce(voci, "solai", "acciaio"), volume_solaio * incidenza_acciaio_sol,
            f"Stima parametrica: {incidenza_acciaio_sol:.0f} kg di acciaio per m³ di calcestruzzo di solaio")
        note.append(
            "Il solaio in soletta piena è calcolato su UN solo livello (superficie del sedime): per edifici "
            "su più piani va moltiplicato per il numero di solai interpiano/contro terra effettivamente "
            "presenti, non dedotto automaticamente in questa versione — correggi la quantità nel passaggio "
            "di revisione."
        )
    elif footprint_area_m2 > 0:
        add(_find_voce(voci, "solai", "standard"), footprint_area_m2,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x 1 solaio (spessore medio "
            f"{spessore_solaio_cm:.0f} cm, da relazione ex Legge 10/91 se disponibile)")
        note.append(
            "La voce solai è calcolata su UN solo livello (superficie del sedime): per edifici su più piani "
            "va moltiplicata per il numero di solai interpiano/contro terra effettivamente presenti, non "
            "dedotto automaticamente in questa versione — correggi la quantità nel passaggio di revisione."
        )

    # --- Cappotto termico esterno ---
    if perimetro_esterno_m > 0:
        area_cappotto = perimetro_esterno_m * altezza_interpiano
        add(_find_voce_con_dettaglio(voci, "cappotto_termico", cap_tipo, answers, "cappotto_termico"), area_cappotto,
            f"Perimetro esterno edificio ({round(perimetro_esterno_m,2)} m, contorno dell'unione dei vani, non "
            f"somma dei perimetri dei singoli vani) x altezza di interpiano ({altezza_interpiano} m), al lordo "
            f"di porte/finestre; spessore cappotto di riferimento {spessore_cappotto_cm:.0f} cm "
            "(da relazione ex Legge 10/91 se disponibile)")
        note.append(
            "La superficie del cappotto termico esterno usa il perimetro ESTERNO dell'involucro (contorno "
            "dell'unione dei vani rilevati), non la somma dei perimetri dei singoli vani (che conterebbe anche "
            "le pareti divisorie interne): è comunque una stima per edificio a un piano, al lordo di porte/"
            "finestre e senza detrarre eventuali logge/portici, da verificare."
        )
    elif tot_perimetro > 0:
        note.append(
            "ATTENZIONE: non è stato possibile calcolare il perimetro esterno dell'involucro (dato mancante): "
            "nessuna voce di cappotto termico è stata generata automaticamente, va aggiunta manualmente."
        )

    # --- Impermeabilizzazioni contro terra ---
    if footprint_area_m2 > 0:
        add(_find_voce(voci, "impermeabilizzazioni", "standard"), footprint_area_m2,
            f"Sedime edificio {round(footprint_area_m2,1)} m²")

    # --- Piscina (se individuata in pianta: vedi extract_piscina) ---
    if piscina_area_m2 > 0:
        superficie_bagnata = piscina_area_m2 + piscina_perimetro_m * profondita_piscina
        volume_scavo_piscina = piscina_area_m2 * (profondita_piscina + 0.30)
        add(_find_voce(voci, "scavi", "piscina"), volume_scavo_piscina,
            f"Piscina {round(piscina_area_m2,1)} m² x (profondità {profondita_piscina} m + 30 cm per lo spessore "
            "della vasca), profondità parametrica da confermare")
        add(_find_voce(voci, "piscina_vasca", "standard"), superficie_bagnata,
            f"Superficie bagnata: fondo {round(piscina_area_m2,1)} m² + pareti (perimetro {round(piscina_perimetro_m,1)} "
            f"m x profondità {profondita_piscina} m)")
        add(_find_voce(voci, "impermeabilizzazioni", "piscina"), superficie_bagnata,
            "Stessa superficie bagnata della vasca (fondo + pareti)")
        add(_find_voce(voci, "piscina_bordo", "standard"), piscina_perimetro_m * larghezza_bordo_piscina,
            f"Perimetro piscina ({round(piscina_perimetro_m,1)} m) x larghezza bordo ({larghezza_bordo_piscina} m)")
        piscina_dim_txt = (f"{piscina_lunghezza_m:.2f} x {piscina_larghezza_m:.2f} (m)"
                            if piscina_lunghezza_m > 0 else f"perimetro {round(piscina_perimetro_m,1)} m")
        note.append(
            f"È stata individuata una piscina in pianta ({round(piscina_area_m2,1)} m² di specchio d'acqua, "
            f"dimensioni {piscina_dim_txt}): scavo, vasca, impermeabilizzazione e bordo sono stimati "
            f"usando una profondità parametrica di {profondita_piscina} m (la pianta non riporta la profondità — "
            "verifica dalle sezioni quotate o dagli esecutivi cementi armati e correggi il parametro se diverso). "
            "L'impianto di filtrazione/trattamento acqua della piscina resta escluso, come gli altri impianti."
        )

    # --- Strutture in elevazione ---
    if strut_tipo.startswith("Cemento armato") and not structural_elements:
        note.append(
            "È stata indicata una struttura in cemento armato ma non sono stati riconosciuti pilastri/travi "
            "(sigle PL#/TR#) nella pianta strutturale caricata (o non è stata caricata): nessuna voce di "
            "struttura in elevazione è stata generata, va verificato l'abaco pilastri/travi."
        )
    elif strut_tipo.startswith("Cemento armato") and structural_elements:
        volume_cls = 0.0
        area_casseforme_cls = 0.0
        for el in structural_elements:
            if not (el.dim1_cm and el.dim2_cm):
                continue
            sezione_m2 = (el.dim1_cm / 100.0) * (el.dim2_cm / 100.0)
            perimetro_sezione_m = 2 * (el.dim1_cm + el.dim2_cm) / 100.0
            lunghezza = altezza_interpiano if el.kind == "pilastro" else lunghezza_trave
            volume_cls += sezione_m2 * lunghezza * el.count
            area_casseforme_cls += perimetro_sezione_m * lunghezza * el.count
        if volume_cls > 0:
            add(_find_voce(voci, "strutture_cls", "standard"), volume_cls,
                "Volume calcestruzzo pilastri (sezione da abaco x altezza di interpiano) e travi "
                "(sezione da abaco x lunghezza media parametrica)")
            add(_find_voce(voci, "strutture_cls", "casseforme"), area_casseforme_cls,
                "Superficie casseforme: perimetro della sezione (da abaco) x altezza di interpiano/lunghezza "
                "media, per pilastri e travi")
            add(_find_voce(voci, "strutture_ferro", "standard"), volume_cls * incidenza_acciaio,
                f"Stima parametrica: {incidenza_acciaio} kg di acciaio per m³ di calcestruzzo")
            note.append(
                "Il computo delle strutture in elevazione in c.a. è una stima preliminare: la lunghezza delle "
                "travi, la superficie di casseratura e l'incidenza dell'acciaio sono valori parametrici "
                "confermati dall'utente o derivati dall'abaco, non misurati da un disegno esecutivo armato."
            )
        missing_dims = [el for el in structural_elements if not (el.dim1_cm and el.dim2_cm)]
        if missing_dims:
            note.append(
                f"{sum(e.count for e in missing_dims)} elementi strutturali non hanno sezione nell'abaco "
                "e non sono stati valorizzati: verificare l'abaco pilastri/travi."
            )
    elif strut_tipo.startswith("Muratura portante") and tot_perimetro > 0:
        volume_muratura = tot_perimetro * altezza_interpiano * spessore_muro_m
        add(_find_voce(voci, "strutture_muratura", "standard"), volume_muratura,
            f"Perimetro vani ({round(tot_perimetro,2)} m) x altezza interpiano ({altezza_interpiano} m) "
            f"x spessore muro ({spessore_muro_m*100:.0f} cm)")
        note.append(
            "Il volume di muratura portante è stimato dal perimetro complessivo dei vani, non dall'asse reale "
            "dei muri perimetrali: è una stima preliminare da verificare sul disegno strutturale."
        )
    elif not strut_tipo.startswith("Cemento armato") and (structural_elements or tot_perimetro > 0):
        dettaglio = (answers.get("tipo_struttura_dettaglio") or "").strip()
        extra = f" ({dettaglio})" if dettaglio else ""
        note.append(
            f"Il tipo di struttura verticale indicato ('{strut_tipo}'{extra}) non rientra tra quelli "
            "calcolabili automaticamente in questa versione (cemento armato o muratura portante): nessuna "
            "voce di struttura in elevazione è stata generata per questo progetto, va computata manualmente."
        )

    # --- Copertura ---
    if roof_area_m2_plan > 0:
        fattore_falda = 1.0 / math.cos(math.radians(min(angolo_falda, 60)))
        area_reale = roof_area_m2_plan * fattore_falda
        add(_find_voce_con_dettaglio(voci, "copertura", cop_tipo, answers, "copertura_tipo"), area_reale,
            f"Superficie in pianta {round(roof_area_m2_plan,1)} m² corretta per angolo di falda "
            f"{angolo_falda}° (fattore {fattore_falda:.2f})")

    # --- Opere accessorie individuate ma non quantificabili in automatico ---
    # Elencate SEMPRE quando i vani sono stati rilevati (l'edificio esiste), come
    # promemoria esplicito di cosa il rilievo NON copre — invece di ometterle in
    # silenzio: quantità e prezzo restano a 0, da completare a mano (righe
    # marcate da_completare, evidenziate nei file generati).
    if rooms or footprint_area_m2 > 0:
        add_placeholder(_find_voce(voci, "scala_esterna", "standard"),
                         "Individuata come possibile presenza in pianta (elemento non taggato con quota affidabile): "
                         "misura e valorizza a mano")
        add_placeholder(_find_voce(voci, "opere_esterne", "recinzione"),
                         "Non rappresentata nella pianta di progetto: misura e valorizza a mano dalla planimetria generale")
        add_placeholder(_find_voce(voci, "opere_esterne", "smaltimento_acque"),
                         "Non rappresentata nella pianta di progetto: valorizza a mano dalla planimetria generale/rete sottoservizi")
        add_placeholder(_find_voce(voci, "opere_esterne", "pavimentazioni_esterne"),
                         "Non quantificata in modo affidabile dalla sola pianta architettonica: misura e valorizza a mano")
        add_placeholder(_find_voce(voci, "opere_esterne", "camerette_ispezione"),
                         "Non rappresentate nella pianta di progetto: conta e valorizza a mano dalla planimetria generale/rete sottoservizi")
        note.append(
            "Sono state aggiunte 5 voci segnaposto (scala esterna, recinzione, smaltimento acque, pavimentazioni "
            "esterne, camerette di ispezione) con quantità e prezzo a 0, evidenziate nei file generati: sono opere "
            "spesso presenti in un progetto reale ma che il rilievo automatico da questa sola pianta non può "
            "misurare con affidabilità (richiedono la planimetria generale, la rete sottoservizi o le sezioni "
            "quotate) — completale a mano prima di considerare il computo definitivo, o eliminale se non "
            "pertinenti a questo progetto."
        )

    # --- Materiali per requisiti acustici individuati nella relazione acustica
    # caricata (vedi acustica_engine.py): sempre come voce segnaposto, perché da un
    # testo descrittivo non si può risalire in modo affidabile a una quantità reale. ---
    if acustica_materiali:
        for materiale in acustica_materiali:
            add_placeholder(_find_voce(voci, "acustica", "materiale_generico"),
                             f"Individuato nella relazione acustica caricata: {materiale}. Misura e valorizza "
                             "a mano in base al prodotto/materiale specifico indicato nella relazione")
        note.append(
            f"Dalla relazione acustica caricata sono stati individuati {len(acustica_materiali)} riferimenti a "
            "materiali/lavorazioni per requisiti acustici: sono stati aggiunti come voci segnaposto (quantità e "
            "prezzo a 0) — un testo descrittivo non permette di risalire in modo affidabile a una quantità "
            "reale, quindi vanno misurati e prezzati a mano, o eliminati se il materiale non è pertinente a "
            "questa parte del progetto."
        )

    # --- Demolizioni (solo ristrutturazione, confronto con stato di fatto) ---
    if rooms_sdf:
        sdp_labels = {r.label.upper() for r in rooms}
        demoliti = [r for r in rooms_sdf if r.label.upper() not in sdp_labels]
        area_demolita = sum(r.area_m2 for r in demoliti)
        perim_demolito = sum(r.perimeter_m for r in demoliti)
        if area_demolita > 0:
            add(_find_voce(voci, "demolizioni", "pavimento"), area_demolita,
                f"Vani presenti nello stato di fatto e non più presenti nel progetto: "
                f"{', '.join(r.label for r in demoliti)}")
        if perim_demolito > 0:
            add(_find_voce(voci, "demolizioni", "intonaco"), perim_demolito * altezza_interna,
                "Intonaco pareti dei vani demoliti (perimetro x altezza interna)")
        if demoliti:
            note.append(
                f"Individuati {len(demoliti)} vani presenti nello stato di fatto e assenti nel progetto: "
                "trattati come completamente demoliti. I vani presenti in entrambi gli stati con superficie "
                "diversa sono segnalati a parte ma non generano automaticamente una riga di demolizione parziale."
            )

    # --- Impianti: voce unica a corpo, percentuale indicativa del totale di TUTTE
    # le altre lavorazioni già computate sopra (richiesta esplicita dell'utente: gli
    # impianti restano esclusi dal rilievo dettagliato, sostituiti da questa unica
    # voce). Va calcolata per ultima, sul subtotale di tutto il resto del computo. ---
    subtotale_senza_impianti = sum(v.importo for v in righe)
    if subtotale_senza_impianti > 0 and incidenza_impianti_pct > 0:
        importo_impianti = round(subtotale_senza_impianti * incidenza_impianti_pct / 100.0, 2)
        v_impianti = _find_voce(voci, "impianti_a_corpo", "standard")
        if v_impianti:
            v_impianti = dict(v_impianti)
            v_impianti["prezzo"] = importo_impianti
            add(v_impianti, 1,
                f"Stima a corpo: {incidenza_impianti_pct:.0f}% del totale delle altre lavorazioni "
                f"({round(subtotale_senza_impianti,2)} €) — parametro confermato dall'utente")
            note.append(
                "Gli impianti (elettrico, idrico-sanitario, termico/climatizzazione) NON sono rilevati nel "
                "dettaglio in questa versione: sono riportati in un'UNICA voce a corpo, calcolata come "
                f"percentuale indicativa ({incidenza_impianti_pct:.0f}%, parametro modificabile) del totale delle "
                "altre lavorazioni. È una stima di massima: va sostituita con un computo impiantistico dedicato "
                "(schema unifilare, schema idrico, dimensionamento termico) appena disponibile."
            )

    # --- Assistenza muraria per elettricista e idraulico: voci SEPARATE (come nel
    # computo di riferimento), distinte dalla voce impianti_a_corpo sopra — quella è
    # il costo dell'impianto in sé, questa è il solo aiuto muratore (tracce, fori,
    # ripristini). Calcolate sullo stesso subtotale (esclusi impianti/assistenze),
    # non l'una sull'altra. ---
    if subtotale_senza_impianti > 0:
        v_asm_ele = _find_voce(voci, "assistenza_muraria", "elettrico")
        if v_asm_ele and incidenza_assistenza_ele > 0:
            v_asm_ele = dict(v_asm_ele)
            v_asm_ele["prezzo"] = round(subtotale_senza_impianti * incidenza_assistenza_ele / 100.0, 2)
            add(v_asm_ele, 1,
                f"Stima a corpo: {incidenza_assistenza_ele:.1f}% del totale delle altre lavorazioni "
                f"({round(subtotale_senza_impianti,2)} €) — parametro confermato dall'utente")
        v_asm_idr = _find_voce(voci, "assistenza_muraria", "idraulico")
        if v_asm_idr and incidenza_assistenza_idr > 0:
            v_asm_idr = dict(v_asm_idr)
            v_asm_idr["prezzo"] = round(subtotale_senza_impianti * incidenza_assistenza_idr / 100.0, 2)
            add(v_asm_idr, 1,
                f"Stima a corpo: {incidenza_assistenza_idr:.1f}% del totale delle altre lavorazioni "
                f"({round(subtotale_senza_impianti,2)} €) — parametro confermato dall'utente")

    return righe, note
