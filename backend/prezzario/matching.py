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

    pav_tipo = answers.get("pavimenti", "Altro (specificare a parte)")
    par_tipo = answers.get("pareti_interne", "Altro (specificare a parte)")
    ser_tipo = answers.get("serramenti_esterni", "Altro (specificare a parte)")
    por_tipo = answers.get("porte_interne", "Altro (specificare a parte)")
    ele_tipo = answers.get("impianto_elettrico", "Altro (specificare a parte)")
    idr_tipo = answers.get("impianto_idrico", "Altro (specificare a parte)")
    strut_tipo = answers.get("tipo_struttura", "Cemento armato (pilastri e travi)")
    cop_tipo = answers.get("copertura_tipo", "Altro (specificare a parte)")

    altezza_interna = parametri.get("altezza_interna_m", 2.70)
    altezza_interpiano = parametri.get("altezza_interpiano_strutturale_m", 3.00)
    profondita_scavo = parametri.get("profondita_scavo_m", 1.20)
    spessore_muro_m = parametri.get("spessore_muro_portante_cm", 30.0) / 100.0
    lunghezza_trave = parametri.get("lunghezza_media_travi_m", 4.00)
    incidenza_acciaio = parametri.get("incidenza_acciaio_kg_m3", 100.0)
    angolo_falda = parametri.get("angolo_falda_gradi", 25.0)

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
            f"{sum(o.count for o in con_misure)} finestre con dimensioni da abaco serramenti")
    if senza_misure:
        count_tot = sum(o.count for o in senza_misure)
        add(_find_voce(voci, "serramenti_esterni", "__FALLBACK_NO_DIM__"), count_tot,
            "Dimensioni non trovate nell'abaco serramenti: prezzo indicativo a corpo")
        if count_tot:
            note.append(f"{count_tot} finestre non hanno dimensioni nell'abaco serramenti: "
                        "valorizzate a corpo con prezzo indicativo, da correggere appena disponibili le misure reali.")

    porte = [o for o in openings if o.kind == "porta"]
    if porte:
        add(_find_voce_con_dettaglio(voci, "porte_interne", por_tipo, answers, "porte_interne"), sum(o.count for o in porte),
            f"{sum(o.count for o in porte)} porte rilevate da pianta")

    # --- Impianti (stima a corpo) ---
    if rooms:
        add(_find_voce_con_dettaglio(voci, "impianto_elettrico", ele_tipo, answers, "impianto_elettrico"), len(rooms),
            f"Stima a corpo per locale, {len(rooms)} locali rilevati")
        note.append("L'impianto elettrico è stimato a corpo per locale: valorizzazione preliminare, "
                    "non sostituisce un computo impiantistico dedicato con schema unifilare.")

    bagni_cucine = [r for r in rooms if any(h in r.label.upper() for h in BAGNO_CUCINA_HINTS)]
    if bagni_cucine:
        add(_find_voce_con_dettaglio(voci, "impianto_idrico", idr_tipo, answers, "impianto_idrico"), len(bagni_cucine),
            f"Stima a corpo per locale bagno/cucina, {len(bagni_cucine)} locali rilevati")
        note.append("L'impianto idrico-sanitario è stimato a corpo per i soli locali riconosciuti come "
                    "bagno/cucina dall'etichetta di pianta.")

    # --- Scavi ---
    if footprint_area_m2 > 0:
        volume_scavo = footprint_area_m2 * profondita_scavo
        add(_find_voce(voci, "scavi", "standard"), volume_scavo,
            f"Sedime edificio {round(footprint_area_m2,1)} m² (inviluppo dei vani rilevati) "
            f"x profondità {profondita_scavo} m")
        note.append(
            "Il sedime dell'edificio è stimato come inviluppo convesso dei vani rilevati in pianta: "
            "per edifici con pianta molto articolata questo sovrastima l'area di scavo reale e va verificato."
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

    return righe, note
