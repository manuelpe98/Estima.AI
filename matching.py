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
    "scale_interne": "Scale interne",
    "opere_esterne": "Opere esterne e sottoservizi",
    "cantiere": "Apprestamenti di cantiere",
    "spinottature": "Spinottature",
    "vespaio": "Vespaio aerato",
    "contropareti": "Contropareti interne",
    "pareti_divisorie": "Pareti divisorie interne",
    "velette": "Velette",
    "assistenza_muraria": "Assistenza muraria",
    "controsoffitti": "Controsoffitti",
    "acustica": "Materiali per requisiti acustici",
    "lattonerie": "Lattonerie (gronde, scossaline, pluviali)",
    "soglie_davanzali": "Soglie e davanzali",
    "rivestimento_facciata": "Rivestimento di facciata",
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
    tipo_intervento: str = "nuova_costruzione",
    render_facciate: list[dict] | None = None,
) -> tuple[list[ComputoVoce], list[str]]:
    righe: list[ComputoVoce] = []
    note: list[str] = []
    n = 1

    def add(v, quantita, note_riga, origine="assunta"):
        # 'origine' classifica la PROVENIENZA del dato (richiesta esplicita
        # dell'utente, da non mischiare tra categorie — vedi il commento su
        # ComputoVoce.origine in models.py): ogni chiamata qui sotto la passa
        # esplicitamente, non c'è un default "giusto" valido per tutte le voci.
        nonlocal n
        if v is None or quantita <= 0:
            return
        categoria_label = CATEGORIA_LABELS.get(v["categoria"], v["categoria"].replace("_", " ").capitalize())
        righe.append(ComputoVoce(n, v["codice"], categoria_label,
                                  v["descrizione"], v["unita_misura"], round(quantita, 2),
                                  v["prezzo"], note=note_riga, origine=origine))
        n += 1

    def add_placeholder(v, note_riga):
        # Come add(), ma per una voce che va SEMPRE elencata anche se il sistema
        # non può calcolarne la quantità: la quantità resta a 0 (davvero non
        # calcolabile) e la riga è marcata da_completare, per essere evidenziata
        # nei file generati e completata a mano invece di mancare silenziosamente
        # dal computo. Il PREZZO invece non viene azzerato: si usa il prezzo della
        # voce di prezzario abbinata (v["prezzo"]), come riferimento di partenza —
        # altrimenti l'utente si trova una riga con prezzo 0 senza sapere se
        # significa "nessun dato disponibile" o "gratis" (segnalato da Franco:
        # molte voci restavano senza alcun prezzo indicativo). Con quantità 0 il
        # totale calcolato non cambia comunque (0 x qualsiasi prezzo = 0): è solo
        # un aiuto in più per chi deve completare la riga a mano.
        # Origine sempre "non_disponibile": non è un dato assunto, è dichiaratamente
        # assente.
        nonlocal n
        if v is None:
            return
        categoria_label = CATEGORIA_LABELS.get(v["categoria"], v["categoria"].replace("_", " ").capitalize())
        righe.append(ComputoVoce(n, v["codice"], categoria_label,
                                  v["descrizione"], v["unita_misura"], 0.0,
                                  v["prezzo"], note=note_riga, da_completare=True, origine="non_disponibile"))
        n += 1

    def add_misurata_da_completare(v, quantita, note_riga, origine="derivata"):
        # Via di mezzo tra add() e add_placeholder(): serve per una riga di cui
        # si conosce una quantità REALE (misurata, non stimata — es. altezza di
        # facciata da una banda di prospetto quotato x perimetro esterno), ma non
        # ancora il materiale/prezzo esatto (dipende da cosa individuato nel
        # render, da confermare a mano). Diversamente da add(), non scarta le
        # quantità positive; diversamente da add_placeholder(), non azzera la
        # quantità: la riga resta comunque "da_completare" per evidenziare che il
        # prezzo (e la scelta del materiale in descrizione) va confermato a mano.
        # Il prezzo usa comunque v["prezzo"] (la voce di prezzario abbinata) come
        # riferimento anziché restare a 0: qui la quantità è reale, quindi un
        # prezzo di riferimento incide anche sul totale calcolato — più utile di
        # un totale che sottostima silenziosamente il costo di questa voce.
        nonlocal n
        if v is None or quantita <= 0:
            return
        categoria_label = CATEGORIA_LABELS.get(v["categoria"], v["categoria"].replace("_", " ").capitalize())
        righe.append(ComputoVoce(n, v["codice"], categoria_label,
                                  v["descrizione"], v["unita_misura"], round(quantita, 2),
                                  v["prezzo"], note=note_riga, da_completare=True, origine=origine))
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
    gru_si = answers.get("gru_cantiere", "No") == "Sì"

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
    costo_gru = parametri.get("costo_noleggio_gru_eur", 8000.0)
    spessore_magrone_m = parametri.get("spessore_magrone_cm", 10.0) / 100.0
    fattore_casseratura_fnd = parametri.get("fattore_casseratura_fondazioni", 2.0)
    incidenza_acciaio_fnd = parametri.get("incidenza_acciaio_fondazioni_kg_m3", 80.0)
    incidenza_acciaio_sol = parametri.get("incidenza_acciaio_solaio_kg_m3", 90.0)
    costo_bagno_chimico = parametri.get("costo_nolo_bagno_chimico_eur", 900.0)
    incidenza_assistenza_ele = parametri.get("incidenza_assistenza_elettrico_pct", 2.0)
    incidenza_assistenza_idr = parametri.get("incidenza_assistenza_idraulico_pct", 2.0)
    numero_piani = max(1, round(parametri.get("numero_piani", 1.0)))

    # --- Finiture (pavimenti, pareti, serramenti, porte) ---
    tot_area_pav = sum(r.area_m2 for r in rooms)
    add(_find_voce_con_dettaglio(voci, "pavimenti", pav_tipo, answers, "pavimenti"), tot_area_pav,
        f"Somma superfici di {len(rooms)} vani rilevati da pianta", origine="derivata")

    tot_perimetro = sum(r.perimeter_m for r in rooms)
    superficie_pareti = tot_perimetro * altezza_interna
    add(_find_voce_con_dettaglio(voci, "pareti_interne", par_tipo, answers, "pareti_interne"), superficie_pareti,
        f"Perimetro vani ({round(tot_perimetro,2)} m) x altezza interna {altezza_interna} m, "
        "al lordo di porte/finestre (non detratte in questa versione)", origine="inferita")
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
            f"{altezza_interna} m", origine="inferita")
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
            "interessano solo alcune pareti", origine="inferita")

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
            "quantità per i soli ambienti effettivamente interessati", origine="inferita")
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
            f"{sum(o.count for o in con_misure)} finestre con dimensioni note (da abaco serramenti o da quote in pianta)",
            origine="esplicita")
    if senza_misure:
        count_tot = sum(o.count for o in senza_misure)
        add(_find_voce(voci, "serramenti_esterni", "__FALLBACK_NO_DIM__"), count_tot,
            "Dimensioni non trovate: prezzo indicativo a corpo", origine="assunta")
        if count_tot:
            note.append(f"{count_tot} finestre non hanno dimensioni note (né da abaco né da quote in pianta): "
                        "valorizzate a corpo con prezzo indicativo, da correggere appena disponibili le misure reali.")

    porte = [o for o in openings if o.kind == "porta"]
    if porte:
        add(_find_voce_con_dettaglio(voci, "porte_interne", por_tipo, answers, "porte_interne"), sum(o.count for o in porte),
            f"{sum(o.count for o in porte)} porte rilevate da pianta", origine="esplicita")

    # --- Assistenza muraria per la posa di serramenti e porte (distinta dalla
    # fornitura e posa dei serramenti/porte stessi, sopra) ---
    if con_misure:
        area_assistenza_ser = sum((o.width_cm * o.height_cm / 10000.0) * o.count for o in con_misure)
        add(_find_voce(voci, "assistenza_muraria", "serramenti"), area_assistenza_ser,
            f"Stessa superficie dei {sum(o.count for o in con_misure)} serramenti con dimensioni note",
            origine="derivata")
    if porte:
        add(_find_voce(voci, "assistenza_muraria", "porte"), sum(o.count for o in porte),
            f"{sum(o.count for o in porte)} porte rilevate da pianta — eventuali porte con lavorazioni "
            "particolari (porta di ingresso, porte tagliafuoco, portoni basculanti) vanno scorporate a mano "
            "con una voce dedicata a prezzo maggiorato", origine="derivata")

    # --- Impianti: NON un rilievo dettagliato (richiesta esplicita dell'utente: gli
    # impianti restano esclusi dal computo puntuale in questa versione) — vengono
    # sommati in un'UNICA voce a corpo, alla fine, come percentuale indicativa del
    # totale di TUTTE le altre lavorazioni già computate (vedi sotto, dopo fondazioni/
    # solai/cappotto/impermeabilizzazioni/copertura/demolizioni: manca solo questa voce).

    # --- Approntamento di cantiere e bagno chimico (a corpo, prezzo dal parametro
    # dedicato: il costo reale dipende dalla dimensione/durata del cantiere, non
    # dalla pianta). Voci SEMPRE presenti, indipendentemente dal fatto che il
    # rilievo geometrico abbia trovato vani/sedime: OGNI cantiere edile reale ha un
    # costo di approntamento e un bagno chimico, anche quando l'estrazione
    # automatica dei vani fallisce o il progetto non ha ancora una pianta quotata
    # caricata correttamente — legarle a `footprint_area_m2 > 0` (comportamento
    # precedente) le faceva sparire insieme a TUTTO il resto del computo in quel
    # caso, mascherando il problema reale invece di segnalarlo. ---
    v_cantiere = _find_voce(voci, "cantiere", "approntamento")
    if v_cantiere:
        v_cantiere = dict(v_cantiere)
        v_cantiere["prezzo"] = costo_cantiere
        add(v_cantiere, 1, "Voce a corpo, prezzo dal parametro 'Costo di approntamento del cantiere' "
                            "(confermato dall'utente)", origine="assunta")
    v_bagno = _find_voce(voci, "cantiere", "bagno_chimico")
    if v_bagno:
        v_bagno = dict(v_bagno)
        v_bagno["prezzo"] = costo_bagno_chimico
        add(v_bagno, 1, "Voce a corpo, prezzo dal parametro 'Costo del nolo bagno chimico' "
                         "(confermato dall'utente)", origine="assunta")

    # --- Gru da cantiere (solo se confermata dall'utente: la necessità dipende dal
    # tipo di cantiere reale, non solo dal tipo di intervento — es. una nuova
    # costruzione di solito la richiede, una ristrutturazione interna di solito no,
    # ma non è una regola assoluta, quindi il sistema chiede conferma invece di
    # decidere da solo) ---
    if gru_si:
        v_gru = _find_voce(voci, "cantiere", "gru")
        if v_gru:
            v_gru = dict(v_gru)
            v_gru["prezzo"] = costo_gru
            add(v_gru, 1, "Voce a corpo, prezzo dal parametro 'Costo del nolo gru' (confermato dall'utente)",
                origine="assunta")

    # --- Scavi ---
    if footprint_area_m2 > 0:
        volume_scavo = footprint_area_m2 * profondita_scavo
        add(_find_voce(voci, "scavi", "standard"), volume_scavo,
            f"Sedime edificio {round(footprint_area_m2,1)} m² (somma dei vani rilevati in pianta) "
            f"x profondità {profondita_scavo} m", origine="inferita")
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
            "(parametro confermato dall'utente)", origine="inferita")
        add(_find_voce(voci, "fondazioni", "standard"), volume_fondazioni,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x spessore medio fondazioni "
            f"{spessore_fondazione_m*100:.0f} cm (parametro confermato dall'utente)", origine="inferita")
        if perimetro_esterno_m > 0:
            area_casseforme_fnd = perimetro_esterno_m * spessore_fondazione_m * fattore_casseratura_fnd
            add(_find_voce(voci, "fondazioni", "casseforme"), area_casseforme_fnd,
                f"Perimetro esterno ({round(perimetro_esterno_m,2)} m) x altezza fondazione "
                f"({spessore_fondazione_m*100:.0f} cm) x {fattore_casseratura_fnd:.0f} facce di casseratura "
                "(parametro confermato dall'utente) — non include eventuali setti/muri di fondazione interni",
                origine="inferita")
        add(_find_voce(voci, "fondazioni", "acciaio"), volume_fondazioni * incidenza_acciaio_fnd,
            f"Stima parametrica: {incidenza_acciaio_fnd:.0f} kg di acciaio per m³ di calcestruzzo di fondazione",
            origine="inferita")
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
            f"Sedime edificio {round(footprint_area_m2,1)} m²", origine="derivata")

    # --- Solai (interpiano e/o contro terra: superficie di sedime moltiplicata per
    # il numero di solai indicato nel parametro "numero_piani" — di default 1, da
    # correggere in base al numero reale di solai dell'edificio (non solo i piani
    # fuori terra: include anche solaio contro terra e/o di copertura se pertinenti).
    # Pacchetto completo (laterocemento/predalles) in un'unica voce, oppure
    # scomposto in casseforme/calcestruzzo/acciaio se il capitolato indica una
    # soletta piena gettata in opera. ---
    if footprint_area_m2 > 0 and tipo_solaio.startswith("Soletta piena"):
        area_solai_tot = footprint_area_m2 * numero_piani
        volume_solaio = area_solai_tot * (spessore_solaio_cm / 100.0)
        add(_find_voce(voci, "solai", "casseforme"), area_solai_tot,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x {numero_piani} solaio/i (parametro "
            "'Numero di piani', confermato dall'utente) = superficie del getto", origine="derivata")
        add(_find_voce(voci, "solai", "calcestruzzo"), volume_solaio,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x {numero_piani} solaio/i x spessore "
            f"{spessore_solaio_cm:.0f} cm (parametri confermati dall'utente)", origine="inferita")
        add(_find_voce(voci, "solai", "acciaio"), volume_solaio * incidenza_acciaio_sol,
            f"Stima parametrica: {incidenza_acciaio_sol:.0f} kg di acciaio per m³ di calcestruzzo di solaio",
            origine="inferita")
        note.append(
            f"Il solaio in soletta piena è calcolato su {numero_piani} solaio/i (parametro 'Numero di piani', "
            f"{'confermato dall’utente' if numero_piani > 1 else 'default 1 — aumentalo se l’edificio ha più solai'}) "
            "x la superficie del sedime rilevato da questa pianta: fondazioni e scavi NON sono moltiplicati per "
            "questo parametro (non scalano con il numero di piani), e pavimenti/pareti/serramenti restano quelli "
            "della sola pianta caricata — per un edificio multi-piano vanno comunque elaborate anche le piante "
            "degli altri livelli."
        )
    elif footprint_area_m2 > 0:
        area_solai_tot = footprint_area_m2 * numero_piani
        add(_find_voce(voci, "solai", "standard"), area_solai_tot,
            f"Sedime edificio {round(footprint_area_m2,1)} m² x {numero_piani} solaio/i (parametro "
            f"'Numero di piani', spessore medio {spessore_solaio_cm:.0f} cm, da relazione ex Legge 10/91 se "
            "disponibile)", origine="inferita")
        note.append(
            f"La voce solai è calcolata su {numero_piani} solaio/i (parametro 'Numero di piani', "
            f"{'confermato dall’utente' if numero_piani > 1 else 'default 1 — aumentalo se l’edificio ha più solai'}) "
            "x la superficie del sedime rilevato da questa pianta: fondazioni e scavi NON sono moltiplicati per "
            "questo parametro (non scalano con il numero di piani), e pavimenti/pareti/serramenti restano quelli "
            "della sola pianta caricata — per un edificio multi-piano vanno comunque elaborate anche le piante "
            "degli altri livelli."
        )

    # --- Cappotto termico esterno ---
    if perimetro_esterno_m > 0:
        area_cappotto = perimetro_esterno_m * altezza_interpiano
        add(_find_voce_con_dettaglio(voci, "cappotto_termico", cap_tipo, answers, "cappotto_termico"), area_cappotto,
            f"Perimetro esterno edificio ({round(perimetro_esterno_m,2)} m, contorno dell'unione dei vani, non "
            f"somma dei perimetri dei singoli vani) x altezza di interpiano ({altezza_interpiano} m), al lordo "
            f"di porte/finestre; spessore cappotto di riferimento {spessore_cappotto_cm:.0f} cm "
            "(da relazione ex Legge 10/91 se disponibile)", origine="inferita")
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
            f"Sedime edificio {round(footprint_area_m2,1)} m²", origine="derivata")

    # --- Piscina (se individuata in pianta: vedi extract_piscina) ---
    if piscina_area_m2 > 0:
        superficie_bagnata = piscina_area_m2 + piscina_perimetro_m * profondita_piscina
        volume_scavo_piscina = piscina_area_m2 * (profondita_piscina + 0.30)
        add(_find_voce(voci, "scavi", "piscina"), volume_scavo_piscina,
            f"Piscina {round(piscina_area_m2,1)} m² x (profondità {profondita_piscina} m + 30 cm per lo spessore "
            "della vasca), profondità parametrica da confermare", origine="inferita")
        add(_find_voce(voci, "piscina_vasca", "standard"), superficie_bagnata,
            f"Superficie bagnata: fondo {round(piscina_area_m2,1)} m² + pareti (perimetro {round(piscina_perimetro_m,1)} "
            f"m x profondità {profondita_piscina} m)", origine="inferita")
        add(_find_voce(voci, "impermeabilizzazioni", "piscina"), superficie_bagnata,
            "Stessa superficie bagnata della vasca (fondo + pareti)", origine="inferita")
        add(_find_voce(voci, "piscina_bordo", "standard"), piscina_perimetro_m * larghezza_bordo_piscina,
            f"Perimetro piscina ({round(piscina_perimetro_m,1)} m) x larghezza bordo ({larghezza_bordo_piscina} m)",
            origine="inferita")
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
                "(sezione da abaco x lunghezza media parametrica)", origine="inferita")
            add(_find_voce(voci, "strutture_cls", "casseforme"), area_casseforme_cls,
                "Superficie casseforme: perimetro della sezione (da abaco) x altezza di interpiano/lunghezza "
                "media, per pilastri e travi", origine="inferita")
            add(_find_voce(voci, "strutture_ferro", "standard"), volume_cls * incidenza_acciaio,
                f"Stima parametrica: {incidenza_acciaio} kg di acciaio per m³ di calcestruzzo", origine="inferita")
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
            f"x spessore muro ({spessore_muro_m*100:.0f} cm)", origine="inferita")
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
            f"{angolo_falda}° (fattore {fattore_falda:.2f})", origine="inferita")

    # --- Opere accessorie tipicamente presenti in un progetto reale ma non
    # quantificabili in automatico dalla sola pianta di progetto ---
    # Elencate SEMPRE (non solo quando i vani sono stati rilevati: un progetto
    # reale le richiede comunque, e se l'estrazione geometrica è fallita è ancora
    # più importante ricordarle esplicitamente invece di lasciare il computo privo
    # di ogni riferimento), come promemoria esplicito di cosa il rilievo NON copre
    # — invece di ometterle in silenzio: quantità a 0 (non misurabile dalla sola
    # pianta), da completare a mano (righe marcate da_completare, evidenziate nei
    # file generati). Il prezzo, quando la voce di prezzario abbinata ne ha uno,
    # viene comunque mostrato come riferimento di partenza (v. add_placeholder).
    add_placeholder(_find_voce(voci, "scala_esterna", "standard"),
                     "Individuata come possibile presenza in pianta (elemento non taggato con quota affidabile): "
                     "misura e valorizza a mano")
    add_placeholder(_find_voce(voci, "scale_interne", "standard"),
                     "Collega i piani dell'edificio: non quotata in modo misurabile automaticamente dalla sola "
                     "pianta caricata (in particolare se l'edificio ha più di un piano). Misura e valorizza a mano")
    add_placeholder(_find_voce(voci, "opere_esterne", "recinzione"),
                     "Non rappresentata nella pianta di progetto: misura e valorizza a mano dalla planimetria generale")
    add_placeholder(_find_voce(voci, "opere_esterne", "smaltimento_acque"),
                     "Reti di smaltimento acque bianche/nere e cavidotti elettrici esterni: non rappresentate nella "
                     "pianta di progetto, valorizza a mano dalla planimetria generale/rete sottoservizi")
    add_placeholder(_find_voce(voci, "opere_esterne", "pavimentazioni_esterne"),
                     "Non quantificata in modo affidabile dalla sola pianta architettonica: misura e valorizza a mano")
    add_placeholder(_find_voce(voci, "opere_esterne", "camerette_ispezione"),
                     "Non rappresentate nella pianta di progetto: conta e valorizza a mano dalla planimetria generale/rete sottoservizi")
    add_placeholder(_find_voce(voci, "opere_esterne", "pozzo_perdente"),
                     "Smaltimento acque meteoriche/reflue nel sottosuolo: presenza e numero dipendono dalla rete "
                     "sottoservizi e dalla planimetria generale, non dalla sola pianta di progetto: verifica e valorizza a mano")
    note.append(
        "Sono state aggiunte 7 voci segnaposto (scala esterna, scale interne, recinzione, smaltimento acque, "
        "pavimentazioni esterne, camerette di ispezione, pozzo perdente) con quantità a 0 (e, dove disponibile, il "
        "prezzo di riferimento del prezzario), evidenziate nei file generati: sono opere spesso presenti in un "
        "progetto reale ma che il rilievo automatico da questa sola "
        "pianta non può misurare con affidabilità (richiedono la planimetria generale, la rete sottoservizi o le "
        "sezioni quotate) — completale a mano prima di considerare il computo definitivo, o eliminale se non "
        "pertinenti a questo progetto."
    )

    # --- Lattonerie (gronde/scossaline/pluviali): tipicamente presenti ovunque ci
    # sia una copertura, ma lo sviluppo lineare reale (gronde, compluvi, displuvi)
    # non è desumibile dalla sola superficie di copertura in pianta — voce
    # segnaposto, non un calcolo. ---
    if roof_area_m2_plan > 0:
        add_placeholder(_find_voce(voci, "lattonerie", "standard"),
                         f"Copertura rilevata ({round(roof_area_m2_plan,1)} m² in pianta): gronde, scossaline, "
                         "pluviali e converse non hanno uno sviluppo lineare desumibile dalla sola superficie di "
                         "copertura. Misura e valorizza a mano da prospetti/sezioni quotate")

    # --- Soglie e davanzali in pietra (o altro materiale da capitolato): tipici di
    # ogni serramento esterno, ma quali aperture li richiedono (finestra normale
    # vs. porta-finestra a raso pavimento, logge, ecc.) è una scelta di progetto,
    # non deducibile in automatico — voce segnaposto, con lo sviluppo lineare
    # complessivo dei soli serramenti con dimensioni note riportato in nota come
    # riferimento di partenza. ---
    if con_misure:
        sviluppo_serramenti_m = sum((o.width_cm / 100.0) * o.count for o in con_misure)
        add_placeholder(_find_voce(voci, "soglie_davanzali", "standard"),
                         f"Sviluppo lineare complessivo dei {sum(o.count for o in con_misure)} serramenti con "
                         f"dimensioni note: {round(sviluppo_serramenti_m,2)} m (riferimento, non tutte le aperture "
                         "richiedono necessariamente soglia e davanzale — es. porte-finestre a raso pavimento). "
                         "Verifica quali aperture li richiedono e valorizza a mano")

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
            "materiali/lavorazioni per requisiti acustici: sono stati aggiunti come voci segnaposto (quantità a "
            "0 e, dove disponibile, il prezzo di riferimento del prezzario) — un testo descrittivo non permette "
            "di risalire in modo affidabile a una quantità reale, quindi vanno misurati e prezzati a mano, o "
            "eliminati se il materiale non è pertinente a questa parte del progetto."
        )

    # --- Rivestimenti di facciata individuati visivamente in un render e
    # abbinati dall'AI a una banda di altezza REALMENTE misurata su un prospetto
    # quotato caricato (vedi elevation_engine.py e ai_assistant.analizza_render):
    # a differenza delle altre voci segnaposto qui sopra, questa riga ha una
    # quantità VERA (altezza misurata x perimetro esterno rilevato dalla
    # pianta), non stimata — ma il materiale/prezzo restano da confermare a
    # mano (il render dice "c'è una pietra", non quale pietra o il suo prezzo),
    # quindi resta comunque da_completare. Ogni elemento arriva già validato
    # server-side (main.py) contro le bande candidate reali: qui ci si fida del
    # valore ricevuto. ---
    if render_facciate:
        for rf in render_facciate:
            area = rf.get("area_m2")
            if not area or area <= 0:
                continue
            descrizione_rf = (rf.get("descrizione") or "").strip()
            altezza_rf = rf.get("altezza_m")
            v_rf = _find_voce(voci, "rivestimento_facciata", "standard")
            if v_rf and descrizione_rf:
                v_rf = dict(v_rf)
                v_rf["descrizione"] = f"{v_rf['descrizione']} — individuato dal render: {descrizione_rf}"
            add_misurata_da_completare(
                v_rf, area,
                f"Superficie = altezza misurata sul prospetto quotato ({altezza_rf} m) x perimetro esterno "
                f"rilevato dalla pianta ({round(perimetro_esterno_m, 2)} m) = {round(area, 2)} m². "
                "Materiale ed elemento individuati SOLO visivamente dal render caricato: verifica di persona "
                "prima di considerare la voce definitiva, e specifica/correggi il materiale e il prezzo.",
                origine="derivata",
            )
        note.append(
            f"Dal render caricato, {len(render_facciate)} elemento/i di facciata sono stati abbinati a una banda "
            "di altezza realmente misurata sul prospetto quotato caricato (superficie = altezza misurata x "
            "perimetro esterno): aggiunti come voci con quantità reale ma prezzo e materiale da confermare a "
            "mano — il render indica DOVE, il prospetto quotato indica QUANTO, ma non quale materiale/prezzo "
            "applicare."
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
                f"{', '.join(r.label for r in demoliti)}", origine="derivata")
        if perim_demolito > 0:
            add(_find_voce(voci, "demolizioni", "intonaco"), perim_demolito * altezza_interna,
                "Intonaco pareti dei vani demoliti (perimetro x altezza interna)", origine="inferita")
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
                f"({round(subtotale_senza_impianti,2)} €) — parametro confermato dall'utente", origine="inferita")
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
                f"({round(subtotale_senza_impianti,2)} €) — parametro confermato dall'utente", origine="inferita")
        v_asm_idr = _find_voce(voci, "assistenza_muraria", "idraulico")
        if v_asm_idr and incidenza_assistenza_idr > 0:
            v_asm_idr = dict(v_asm_idr)
            v_asm_idr["prezzo"] = round(subtotale_senza_impianti * incidenza_assistenza_idr / 100.0, 2)
            add(v_asm_idr, 1,
                f"Stima a corpo: {incidenza_assistenza_idr:.1f}% del totale delle altre lavorazioni "
                f"({round(subtotale_senza_impianti,2)} €) — parametro confermato dall'utente", origine="inferita")

    # --- "Missing Scope Detector": non un calcolo, un controllo di plausibilità.
    # Il sistema si chiede "cosa ci si aspetterebbe normalmente in un progetto così,
    # che non sto trovando?" e lo segnala come lista di verifica — NON aggiunge
    # NULLA automaticamente al computo (a differenza delle voci segnaposto sopra,
    # che sono elementi individuati/probabili): qui si tratta di categorie di
    # lavorazione tipiche che il rilievo da sola pianta non può nemmeno provare a
    # dedurre, quindi vanno solo controllate a mano dal professionista. ---
    if footprint_area_m2 > 0:
        categorie_presenti = {r.categoria for r in righe}
        da_verificare: list[str] = []
        if "Impermeabilizzazioni" not in categorie_presenti:
            da_verificare.append("impermeabilizzazioni (coperture piane, terrazzi/balconi, vespaio o fondazioni contro terra)")
        if tot_area_pav > 0:
            da_verificare.append("battiscopa")
        if tipo_intervento == "ristrutturazione":
            da_verificare.append("opere di preparazione (rimozione pavimenti/rivestimenti esistenti, tracce)")
            da_verificare.append("smaltimento macerie e oneri di conferimento in discarica")
        if perimetro_esterno_m > 0 or roof_area_m2_plan > 0:
            da_verificare.append("ponteggi o altri apprestamenti per lavori in quota su facciate/copertura")
        if perimetro_esterno_m > 0:
            da_verificare.append("rivestimento di facciata alternativo alla sola rasatura del cappotto (es. pietra "
                                  "ricostruita, doghe, klinker), se previsto dal capitolato")
            da_verificare.append("isolamento termico delle pareti controterra (distinto dall'impermeabilizzazione: "
                                  "cantine, box, vani tecnici)")
        if roof_area_m2_plan > 0:
            da_verificare.append("sistema anticaduta permanente (linea vita) per la manutenzione in sicurezza della "
                                  "copertura, comignoli e torrini di esalazione")
        if contropareti_si or velette_si or lunghezza_pareti_divisorie > 0:
            da_verificare.append("dettagli in cartongesso non computati separatamente (controtelai a scomparsa per "
                                  "porte scorrevoli, botole di ispezione, profili paraspigolo, rinforzi per carichi sospesi)")
        da_verificare.append("altre assistenze murarie non già computate (es. posa sanitari, ascensore, canna fumaria)")
        if da_verificare:
            note.append(
                "⚠️ Possibili lavorazioni mancanti (lista di verifica, NON aggiunte automaticamente al computo — "
                "controlla se sono pertinenti a questo progetto e aggiungile a mano se necessario): "
                + "; ".join(da_verificare) + "."
            )

    return righe, note
