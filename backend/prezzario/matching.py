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

    # --- Impianti: NON un rilievo dettagliato (richiesta esplicita dell'utente: gli
    # impianti restano esclusi dal computo puntuale in questa versione) — vengono
    # sommati in un'UNICA voce a corpo, alla fine, come percentuale indicativa del
    # totale di TUTTE le altre lavorazioni già computate (vedi sotto, dopo fondazioni/
    # solai/cappotto/impermeabilizzazioni/copertura/demolizioni: manca solo questa voce).

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

    # --- Fondazioni ---
    if footprint_area_m2 > 0:
        volume_fondazioni = footprint_area_m2 * spessore_fondazione_m
        add(_find_voce(voci, "fondazioni", "standard"), volume_fondazioni,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x spessore medio fondazioni "
            f"{spessore_fondazione_m*100:.0f} cm (parametro confermato dall'utente)")

    # --- Solai (interpiano e/o contro terra: una sola voce a superficie di sedime,
    # NON moltiplicata per il numero di piani, perché il numero di piani non è
    # dedotto in modo affidabile dai soli elaborati di pianta in questa versione) ---
    if footprint_area_m2 > 0:
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
        note.append(
            f"È stata individuata una piscina in pianta ({round(piscina_area_m2,1)} m² di specchio d'acqua, "
            f"perimetro {round(piscina_perimetro_m,1)} m): scavo, vasca, impermeabilizzazione e bordo sono stimati "
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
        for el in structural_elements:
            if not (el.dim1_cm and el.dim2_cm):
                continue
            sezione_m2 = (el.dim1_cm / 100.0) * (el.dim2_cm / 100.0)
            lunghezza = altezza_interpiano if el.kind == "pilastro" else lunghezza_trave
            volume_cls += sezione_m2 * lunghezza * el.count
        if volume_cls > 0:
            add(_find_voce(voci, "strutture_cls", "standard"), volume_cls,
                "Volume calcestruzzo pilastri (sezione da abaco x altezza di interpiano) e travi "
                "(sezione da abaco x lunghezza media parametrica)")
            add(_find_voce(voci, "strutture_ferro", "standard"), volume_cls * incidenza_acciaio,
                f"Stima parametrica: {incidenza_acciaio} kg di acciaio per m³ di calcestruzzo")
            note.append(
                "Il computo delle strutture in elevazione in c.a. è una stima preliminare: la lunghezza delle "
                "travi e l'incidenza dell'acciaio sono valori parametrici confermati dall'utente, non misurati "
                "da un disegno esecutivo armato. Le opere di casseratura non sono comprese in questa versione."
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
        note.append(
            "Sono state aggiunte 4 voci segnaposto (scala esterna, recinzione, smaltimento acque, pavimentazioni "
            "esterne) con quantità e prezzo a 0, evidenziate nei file generati: sono opere spesso presenti in un "
            "progetto reale ma che il rilievo automatico da questa sola pianta non può misurare con affidabilità "
            "(richiedono la planimetria generale, la rete sottoservizi o le sezioni quotate) — completale a mano "
            "prima di considerare il computo definitivo, o eliminale se non pertinenti a questo progetto."
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

    return righe, note
