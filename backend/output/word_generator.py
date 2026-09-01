"""Genera la relazione descrittiva del computo in Word, in prosa discorsiva
(per coerenza con la convenzione già seguita per il caso Colombo)."""
from __future__ import annotations
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from ..models import ComputoVoce, ProjectMeta, RoomComparison


def build_word(voci: list[ComputoVoce], meta: ProjectMeta, note_metodologiche: list[str],
                validazione_msg: list[str], out_path: str,
                confronto: list[RoomComparison] | None = None) -> str:
    doc = Document()

    title = doc.add_heading("Computo Metrico Estimativo", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    tipo_lbl = "nuova costruzione" if meta.tipo_intervento == "nuova_costruzione" else "ristrutturazione"
    doc.add_paragraph(
        f"Il presente documento riporta il computo metrico estimativo relativo al progetto "
        f"\"{meta.nome_progetto}\" ({tipo_lbl})" + (f", per il committente {meta.committente}" if meta.committente else "") +
        (f", ubicato in {meta.ubicazione}" if meta.ubicazione else "") +
        f". Le quantità sono state rilevate in via automatica dagli elaborati grafici caricati "
        f"(pianta quotata in scala, ed eventuale pianta strutturale) e valorizzate sulla base del "
        f"prezzario \"{meta.prezzario_nome}\". Il documento ha carattere preliminare/estimativo ed è "
        "soggetto a verifica da parte del tecnico incaricato prima di ogni utilizzo con valenza contrattuale."
    )

    doc.add_heading("Metodologia e fonti", level=1)
    doc.add_paragraph(
        "Le superfici dei singoli vani, il sedime dell'edificio e il conteggio di serramenti ed elementi "
        "strutturali puntuali (pilastri, travi) sono stati ricavati per via geometrica dagli elaborati "
        "caricati, verificati come elaborati vettoriali in scala e completi di quote. Le scelte di "
        "materiali, finiture e i parametri dimensionali non deducibili dal disegno (altezze di interpiano, "
        "profondità di scavo, incidenze parametriche) sono stati raccolti tramite questionario strutturato "
        "e confermati dall'utente, e sono riportati nelle note metodologiche e nelle singole voci."
    )
    if note_metodologiche:
        for nota in note_metodologiche:
            doc.add_paragraph(nota, style="Intense Quote")

    if validazione_msg:
        doc.add_heading("Esito della verifica degli elaborati grafici", level=1)
        doc.add_paragraph(" ".join(validazione_msg))

    if confronto:
        doc.add_heading("Confronto stato di fatto / stato di progetto", level=1)
        doc.add_paragraph(
            "Il confronto tra i vani rilevati nello stato di fatto e nello stato di progetto individua i "
            "vani demoliti (presenti solo nello stato di fatto), i vani di nuova formazione (presenti solo "
            "nel progetto) e i vani con superficie variata, riportati di seguito. Solo i vani demoliti "
            "generano automaticamente le relative voci di demolizione nel computo; i vani con superficie "
            "variata sono segnalati per una verifica puntuale, non essendo automaticamente quantificabile "
            "l'entità dell'intervento di adeguamento."
        )
        table = doc.add_table(rows=1, cols=4)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        for i, h in enumerate(["Vano", "Stato", "Area stato di fatto (m²)", "Area stato di progetto (m²)"]):
            hdr[i].text = h
        for c in confronto:
            row = table.add_row().cells
            row[0].text = c.label
            row[1].text = c.stato.replace("_", " ")
            row[2].text = f"{c.area_sdf_m2:.2f}" if c.area_sdf_m2 is not None else "-"
            row[3].text = f"{c.area_sdp_m2:.2f}" if c.area_sdp_m2 is not None else "-"
        doc.add_paragraph()

    ha_commenti = any(getattr(v, "commento", "") for v in voci)
    n_cols = 8 if ha_commenti else 7
    doc.add_heading("Elenco voci di computo", level=1)
    table = doc.add_table(rows=1, cols=n_cols)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    intestazioni = ["N.", "Codice", "Categoria", "Descrizione", "U.M.", "Q.tà", "Importo (€)"]
    if ha_commenti:
        intestazioni.append("Commento")
    for i, h in enumerate(intestazioni):
        hdr[i].text = h

    totale = 0.0
    for v in voci:
        row = table.add_row().cells
        row[0].text = str(v.numero)
        row[1].text = v.codice
        row[2].text = v.categoria
        row[3].text = v.descrizione
        row[4].text = v.unita_misura
        row[5].text = f"{v.quantita:,.2f}"
        row[6].text = f"{v.importo:,.2f}"
        if ha_commenti:
            row[7].text = getattr(v, "commento", "") or ""
        totale += v.importo

    doc.add_paragraph()
    tot_p = doc.add_paragraph()
    tot_run = tot_p.add_run(f"Totale computo (al netto di IVA, oneri di sicurezza e spese tecniche): € {totale:,.2f}")
    tot_run.bold = True
    tot_run.font.size = Pt(12)

    doc.add_heading("Avvertenze", level=1)
    doc.add_paragraph(
        "Il presente computo copre le opere di finitura (pavimenti, pareti interne, serramenti, porte "
        "interne), le strutture in elevazione, gli scavi di fondazione e la copertura, oltre a una stima "
        "forfettaria degli impianti elettrico e idrico-sanitario, nei limiti di ciò che è quantificabile "
        "a partire dagli elaborati caricati e dai parametri confermati dall'utente. Restano fuori da questa "
        "versione: le opere di fondazione di dettaglio, le casserature, l'impiantistica di dettaglio e, per "
        "le ristrutturazioni, le demolizioni parziali dei vani con superficie variata (segnalate ma non "
        "quantificate automaticamente). Il prezzario utilizzato, se non caricato esplicitamente "
        "dall'utente, è un prezzario di esempio a scopo dimostrativo e non ha valore ufficiale."
    )

    doc.save(out_path)
    return out_path
