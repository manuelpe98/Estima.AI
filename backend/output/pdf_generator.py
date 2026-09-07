"""Genera una versione PDF, stampabile e universalmente apribile, dell'elenco
voci del computo — pensata come alternativa rapida all'Excel per chi vuole
solo consultarlo o inoltrarlo (es. al cliente, in banca, in comune) senza
dover aprire un foglio di calcolo. Il contenuto tabellare rispecchia quello
del file Excel (stesse colonne principali, stessa evidenziazione in giallo
delle voci da completare a mano); la relazione discorsiva con la metodologia
completa resta nel file Word, a cui questo documento rimanda."""
from __future__ import annotations
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
)
from ..models import ComputoVoce, ProjectMeta, RoomComparison, ORIGINE_INFO

_DA_COMPLETARE_BG = colors.HexColor("#FFF2CC")
_DA_COMPLETARE_FG = colors.HexColor("#7F6000")
_ATTENZIONE_BG = colors.HexColor("#F8CBAD")
_ATTENZIONE_FG = colors.HexColor("#9C0006")
_HEADER_BG = colors.HexColor("#1F4E5F")
_GRID_COLOR = colors.HexColor("#BFBFBF")

# I font di base di reportlab (Helvetica) non includono le emoji usate per la
# colonna Affidabilità in Excel/Word (🟢🟡🟠⚪) né il simbolo ⚠: nel PDF
# comparirebbero come caratteri mancanti. Qui si usa lo stesso significato
# (colore + un pallino "•", che è un carattere normale della codifica
# Helvetica) invece dell'emoji colorata, per un risultato identico in
# sostanza ma senza dipendere da font aggiuntivi non garantiti sul server.
_ORIGINE_COLOR = {
    "esplicita": "#2E7D32",
    "derivata": "#2E7D32",
    "inferita": "#B8860B",
    "assunta": "#E07B00",
    "non_disponibile": "#808080",
}


def _origine_html(origine: str) -> str:
    label, _emoji = ORIGINE_INFO.get(origine, ("", ""))
    color = _ORIGINE_COLOR.get(origine, "#808080")
    return f'<font color="{color}">•</font> {label}'


def _legenda_affidabilita_html() -> str:
    voci = ("esplicita", "derivata", "inferita", "assunta", "non_disponibile")
    return "Legenda colonna Affidabilità (provenienza del dato): " + "; ".join(
        _origine_html(k) for k in voci) + "."


def _styles():
    ss = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("TitoloComputo", parent=ss["Title"], fontSize=16, spaceAfter=4),
        "meta": ParagraphStyle("MetaComputo", parent=ss["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("CellaComputo", parent=ss["Normal"], fontSize=8, leading=10),
        "cell_bold": ParagraphStyle("CellaComputoGrassetto", parent=ss["Normal"], fontSize=8, leading=10,
                                     textColor=_DA_COMPLETARE_FG, fontName="Helvetica-Bold"),
        "header_cell": ParagraphStyle("Intestazione", parent=ss["Normal"], fontSize=8.5, leading=10,
                                       textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_CENTER),
        "nota": ParagraphStyle("NotaMetodologica", parent=ss["Normal"], fontSize=8.5, leading=11,
                                fontName="Helvetica-Oblique"),
        "nota_critica": ParagraphStyle("NotaCritica", parent=ss["Normal"], fontSize=9, leading=12,
                                        textColor=_ATTENZIONE_FG, fontName="Helvetica-Bold"),
        "legenda": ParagraphStyle("Legenda", parent=ss["Normal"], fontSize=8, leading=10,
                                   fontName="Helvetica-Oblique"),
        "totale": ParagraphStyle("Totale", parent=ss["Normal"], fontSize=12, leading=15,
                                  fontName="Helvetica-Bold"),
    }
    return styles


def build_pdf(voci: list[ComputoVoce], meta: ProjectMeta, out_path: str,
              note_metodologiche: list[str] | None = None,
              confronto: list[RoomComparison] | None = None) -> str:
    styles = _styles()
    doc = SimpleDocTemplate(
        out_path, pagesize=landscape(A4),
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Computo metrico estimativo — {meta.nome_progetto}",
    )
    story = []

    story.append(Paragraph("Computo Metrico Estimativo", styles["title"]))
    tipo_lbl = "nuova costruzione" if meta.tipo_intervento == "nuova_costruzione" else "ristrutturazione"
    meta_lines = [f"<b>Progetto:</b> {meta.nome_progetto} ({tipo_lbl})"]
    if meta.committente:
        meta_lines.append(f"<b>Committente:</b> {meta.committente}")
    if meta.ubicazione:
        meta_lines.append(f"<b>Ubicazione:</b> {meta.ubicazione}")
    meta_lines.append(f"<b>Prezzario di riferimento:</b> {meta.prezzario_nome}")
    story.append(Paragraph("<br/>".join(meta_lines), styles["meta"]))
    story.append(Spacer(1, 8))

    if note_metodologiche:
        critiche = [n for n in note_metodologiche if n.startswith("ATTENZIONE")]
        normali = [n for n in note_metodologiche if not n.startswith("ATTENZIONE")]
        for nota in critiche:
            box = Table([[Paragraph(nota, styles["nota_critica"])]], colWidths=[doc.width])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), _ATTENZIONE_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, _ATTENZIONE_FG),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(box)
            story.append(Spacer(1, 6))
        if normali:
            story.append(Paragraph("<b>Note metodologiche:</b>", styles["meta"]))
            for nota in normali:
                story.append(Paragraph(f"• {nota}", styles["nota"]))
            story.append(Spacer(1, 8))

    # --- Tabella voci ---------------------------------------------------
    ha_commenti = any(getattr(v, "commento", "") for v in voci)
    intestazioni = ["N.", "Codice", "Categoria", "Descrizione", "U.M.", "Qtà",
                     "Prezzo un. (€)", "Importo (€)", "Affidabilità"]
    if ha_commenti:
        intestazioni.append("Commento")
    header_row = [Paragraph(h, styles["header_cell"]) for h in intestazioni]

    fixed_widths = [22, 58, 68, None, 28, 40, 55, 55, 85]
    if ha_commenti:
        fixed_widths.append(85)
    n_flex = fixed_widths.count(None)
    used = sum(w for w in fixed_widths if w is not None)
    flex_width = (doc.width - used) / n_flex if n_flex else 0
    col_widths = [w if w is not None else flex_width for w in fixed_widths]

    table_rows = [header_row]
    da_completare_rows = []
    totale = 0.0
    for idx, v in enumerate(voci, start=1):
        da_completare = getattr(v, "da_completare", False)
        cell_style = styles["cell_bold"] if da_completare else styles["cell"]
        descrizione = v.descrizione
        if da_completare:
            descrizione = "DA COMPLETARE A MANO — " + descrizione
            da_completare_rows.append(idx)  # idx = riga di dati, +1 per l'intestazione va calcolato dopo
        row = [
            Paragraph(str(v.numero), cell_style),
            Paragraph(v.codice, cell_style),
            Paragraph(v.categoria, cell_style),
            Paragraph(descrizione, cell_style),
            Paragraph(v.unita_misura, cell_style),
            Paragraph(f"{v.quantita:,.2f}", cell_style),
            Paragraph(f"{v.prezzo_unitario:,.2f}", cell_style),
            Paragraph(f"{v.importo:,.2f}", cell_style),
            Paragraph(_origine_html(getattr(v, "origine", "assunta")), cell_style),
        ]
        if ha_commenti:
            row.append(Paragraph(getattr(v, "commento", "") or "", cell_style))
        table_rows.append(row)
        totale += v.importo

    table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for riga_dati in da_completare_rows:
        table_style.append(("BACKGROUND", (0, riga_dati), (-1, riga_dati), _DA_COMPLETARE_BG))
    table.setStyle(TableStyle(table_style))
    story.append(table)
    story.append(Spacer(1, 10))

    righe_da_completare = len(da_completare_rows)
    if righe_da_completare:
        story.append(Paragraph(
            f"{righe_da_completare} voce/i evidenziata/e in giallo: da completare a mano (quantità non "
            "calcolabile dagli elaborati caricati — il prezzo, dove disponibile nel prezzario, è indicato "
            "comunque a titolo di riferimento).", styles["nota_critica"]))
        story.append(Spacer(1, 6))

    story.append(Paragraph(_legenda_affidabilita_html(), styles["legenda"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        f"TOTALE COMPUTO (al netto di IVA, oneri di sicurezza e spese tecniche): € {totale:,.2f}",
        styles["totale"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Documento preliminare/estimativo, soggetto a verifica da parte del tecnico incaricato prima di ogni "
        "utilizzo con valenza contrattuale. Per la metodologia completa e le avvertenze, vedi la relazione Word "
        "allegata.", styles["nota"]))

    doc.build(story)
    return out_path
