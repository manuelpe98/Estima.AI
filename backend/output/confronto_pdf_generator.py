"""Versione PDF del confronto prezzi tra preventivi — stessa tabella del file
Excel (vedi confronto_excel_generator.py), pensata per essere consultata o
inoltrata senza dover aprire un foglio di calcolo. Landscape A3 come il file
di esempio fornito da Franco: con più di 2-3 imprese affiancate, A4 sarebbe
troppo stretto per restare leggibile."""
from __future__ import annotations
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

_HEADER_BG = colors.HexColor("#1F4E5F")
_CATEGORIA_BG = colors.HexColor("#E2E8EC")
_CATEGORIA_FG = colors.HexColor("#1F4E5F")
_TOTALE_BG = colors.HexColor("#FFF2CC")
_GRID_COLOR = colors.HexColor("#BFBFBF")
_NON_QUOTATA_FG = colors.HexColor("#9C9080")


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("TitoloConfronto", parent=ss["Title"], fontSize=15, spaceAfter=4),
        "meta": ParagraphStyle("MetaConfronto", parent=ss["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("CellaConfronto", parent=ss["Normal"], fontSize=7.5, leading=9),
        "cell_right": ParagraphStyle("CellaConfrontoDestra", parent=ss["Normal"], fontSize=7.5, leading=9,
                                      alignment=TA_RIGHT),
        "cell_non_quotata": ParagraphStyle("CellaNonQuotata", parent=ss["Normal"], fontSize=7.5, leading=9,
                                            textColor=_NON_QUOTATA_FG, fontName="Helvetica-Oblique",
                                            alignment=TA_CENTER),
        "header_cell": ParagraphStyle("IntestazioneConfronto", parent=ss["Normal"], fontSize=8, leading=10,
                                       textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_CENTER),
        "categoria": ParagraphStyle("Categoria", parent=ss["Normal"], fontSize=9, leading=11,
                                     textColor=_CATEGORIA_FG, fontName="Helvetica-Bold"),
        "totale": ParagraphStyle("TotaleRiga", parent=ss["Normal"], fontSize=8.5, leading=11,
                                  fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "nota": ParagraphStyle("NotaConfronto", parent=ss["Normal"], fontSize=8, leading=10,
                                fontName="Helvetica-Oblique"),
    }


def build_confronto_pdf(confronto: dict, meta: dict, out_path: str) -> str:
    styles = _styles()
    doc = SimpleDocTemplate(
        out_path, pagesize=landscape(A3),
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Confronto preventivi — {meta.get('nome_progetto', '')}",
    )
    story = []
    imprese = confronto["imprese_nomi"]

    story.append(Paragraph("Confronto prezzi tra preventivi", styles["title"]))
    meta_lines = [f"<b>Progetto:</b> {meta.get('nome_progetto') or 'Progetto senza nome'}"]
    if meta.get("committente"):
        meta_lines.append(f"<b>Committente:</b> {meta['committente']}")
    meta_lines.append(f"<b>Imprese confrontate:</b> {', '.join(imprese)}")
    story.append(Paragraph("<br/>".join(meta_lines), styles["meta"]))
    story.append(Spacer(1, 8))

    intestazioni = ["N.", "Codice", "Descrizione", "U.M.", "Qtà"]
    for nome in imprese:
        intestazioni.append(f"{nome}\nunitario")
        intestazioni.append(f"{nome}\ntotale")
    header_row = [Paragraph(h.replace("\n", "<br/>"), styles["header_cell"]) for h in intestazioni]

    fixed = [16, 42, None, 28, 32]
    per_impresa_width = 42
    fixed += [per_impresa_width, per_impresa_width] * len(imprese)
    n_flex = fixed.count(None)
    used = sum(w for w in fixed if w is not None)
    flex_width = (doc.width - used) / n_flex if n_flex else 0
    col_widths = [w if w is not None else flex_width for w in fixed]

    table_rows = [header_row]
    span_commands = []
    background_commands = [("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG)]
    r = 1
    for categoria in confronto["categorie"]:
        table_rows.append([Paragraph(categoria["nome"], styles["categoria"])] + [""] * (len(intestazioni) - 1))
        span_commands.append(("SPAN", (0, r), (-1, r)))
        background_commands.append(("BACKGROUND", (0, r), (-1, r), _CATEGORIA_BG))
        r += 1
        for voce in categoria["voci"]:
            row = [
                Paragraph(str(voce["numero"]), styles["cell"]),
                Paragraph(voce.get("codice", ""), styles["cell"]),
                Paragraph(voce["descrizione"], styles["cell"]),
                Paragraph(voce.get("unita_misura", ""), styles["cell"]),
                Paragraph(f"{voce.get('quantita', 0):,.2f}", styles["cell_right"]),
            ]
            for nome in imprese:
                importo = voce["importi"].get(nome)
                if importo is None:
                    row.append(Paragraph("—", styles["cell_non_quotata"]))
                    row.append(Paragraph("—", styles["cell_non_quotata"]))
                else:
                    quantita = voce.get("quantita") or 0
                    prezzo_unitario = round(importo / quantita, 2) if quantita else 0
                    row.append(Paragraph(f"{prezzo_unitario:,.2f} €", styles["cell_right"]))
                    row.append(Paragraph(f"{importo:,.2f} €", styles["cell_right"]))
            table_rows.append(row)
            r += 1

    totale_row = [Paragraph("TOTALE", styles["totale"]), "", "", "", ""]
    for nome in imprese:
        totale_row.append("")
        totale_row.append(Paragraph(f"{confronto['totali'].get(nome, 0):,.2f} €", styles["totale"]))
    table_rows.append(totale_row)
    background_commands.append(("BACKGROUND", (0, r), (-1, r), _TOTALE_BG))
    span_commands.append(("SPAN", (0, r), (4, r)))

    table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    table_style = [
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ] + span_commands + background_commands
    table.setStyle(TableStyle(table_style))
    story.append(table)
    story.append(Spacer(1, 10))

    non_quotate = confronto.get("non_quotate") or {}
    if any(non_quotate.values()):
        story.append(Paragraph("<b>Voci non quotate da alcune imprese:</b>", styles["meta"]))
        for nome in imprese:
            numeri = non_quotate.get(nome) or []
            if numeri:
                story.append(Paragraph(f"• {nome}: voce/i n. " + ", ".join(str(n) for n in numeri), styles["nota"]))
        story.append(Spacer(1, 6))

    dichiarati = confronto.get("totali_dichiarati") or {}
    if any(v is not None for v in dichiarati.values()):
        story.append(Paragraph(
            "<b>Totale dichiarato direttamente dall'impresa sul proprio preventivo</b> (controllo incrociato "
            "col totale ricalcolato in tabella):", styles["meta"]))
        for nome, val in dichiarati.items():
            if val is not None:
                story.append(Paragraph(f"• {nome}: € {val:,.2f}", styles["nota"]))
        story.append(Spacer(1, 6))

    story.append(Paragraph(
        "Documento preliminare/estimativo basato sui prezzi indicati dalle singole imprese nei rispettivi "
        "preventivi: da verificare col tecnico incaricato prima di ogni utilizzo con valenza contrattuale.",
        styles["nota"]))

    doc.build(story)
    return out_path
