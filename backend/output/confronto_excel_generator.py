"""Genera il file Excel di confronto prezzi tra i preventivi delle imprese —
stessa impostazione a colonne del file di esempio fornito da Franco
(categorie, poi per ogni voce la quantità e, per ciascuna impresa, prezzo
unitario e totale affiancati, con i totali finali in fondo), adattata al
formato PIATTO che Estima usa per il computo (una riga per voce con la
quantità già finale, senza le righe di dettaglio "misurazioni" di PriMus,
che qui non esistono)."""
from __future__ import annotations
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill(start_color="1F4E5F", end_color="1F4E5F", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)
CATEGORIA_FILL = PatternFill(start_color="E2E8EC", end_color="E2E8EC", fill_type="solid")
CATEGORIA_FONT = Font(bold=True, color="1F4E5F")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
NON_QUOTATA_FONT = Font(italic=True, color="9C9080")
TOTALE_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
TOTALE_FONT = Font(bold=True)
EUR_FMT = '€#,##0.00;(€#,##0.00);-'

# Una tinta diversa per il blocco di colonne di ciascuna impresa (ciclica se
# ce ne sono più di 4), solo per distinguerle a colpo d'occhio come nel file
# di esempio — non ha altro significato.
_TINTE_IMPRESA = ["EDE7F6", "E3F2FD", "FFF3E0", "E8F5E9"]


def build_confronto_excel(confronto: dict, meta: dict, out_path: str) -> str:
    """confronto: come restituito da confronto_preventivi_engine.costruisci_confronto().
    meta: dict con almeno 'nome_progetto' (facoltativi 'committente'/'ubicazione')."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Confronto preventivi"

    imprese = confronto["imprese_nomi"]
    n_imprese = len(imprese)

    ws["A1"] = "CONFRONTO PREZZI TRA PREVENTIVI"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Progetto: {meta.get('nome_progetto') or 'Progetto senza nome'}"
    if meta.get("committente"):
        ws["A3"] = f"Committente: {meta['committente']}"
    ws["A4"] = f"Imprese confrontate: {', '.join(imprese)}"

    header_row = 6
    colonne_fisse = ["N.", "Codice", "Descrizione", "U.M.", "Quantità"]
    for col_idx, titolo in enumerate(colonne_fisse, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=titolo)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

    col = len(colonne_fisse) + 1
    impresa_col_start: dict[str, int] = {}
    for nome in imprese:
        impresa_col_start[nome] = col
        ws.merge_cells(start_row=header_row - 1, start_column=col, end_row=header_row - 1, end_column=col + 1)
        top = ws.cell(row=header_row - 1, column=col, value=nome)
        top.font = HEADER_FONT
        top.fill = HEADER_FILL
        top.alignment = Alignment(horizontal="center", vertical="center")
        for sub_idx, sub_titolo in enumerate(("Prezzo unitario", "Importo")):
            cell = ws.cell(row=header_row, column=col + sub_idx, value=sub_titolo)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = BORDER
        col += 2

    row = header_row + 1
    totale_row_by_impresa: dict[str, list[int]] = {nome: [] for nome in imprese}
    for categoria in confronto["categorie"]:
        cat_cell = ws.cell(row=row, column=1, value=categoria["nome"])
        cat_cell.font = CATEGORIA_FONT
        cat_cell.fill = CATEGORIA_FILL
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col - 1)
        row += 1
        for voce in categoria["voci"]:
            ws.cell(row=row, column=1, value=voce["numero"]).border = BORDER
            ws.cell(row=row, column=2, value=voce.get("codice", "")).border = BORDER
            desc_cell = ws.cell(row=row, column=3, value=voce["descrizione"])
            desc_cell.border = BORDER
            desc_cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(row=row, column=4, value=voce.get("unita_misura", "")).border = BORDER
            qta_cell = ws.cell(row=row, column=5, value=voce.get("quantita", 0))
            qta_cell.border = BORDER
            qta_cell.number_format = "#,##0.00"

            c = impresa_col_start[imprese[0]] if imprese else 6
            for nome in imprese:
                c = impresa_col_start[nome]
                importo = voce["importi"].get(nome)
                if importo is None:
                    prezzo_cell = ws.cell(row=row, column=c, value="—")
                    importo_cell = ws.cell(row=row, column=c + 1, value="—")
                    prezzo_cell.font = NON_QUOTATA_FONT
                    importo_cell.font = NON_QUOTATA_FONT
                    prezzo_cell.alignment = Alignment(horizontal="center")
                    importo_cell.alignment = Alignment(horizontal="center")
                else:
                    quantita = voce.get("quantita") or 0
                    prezzo_unitario = round(importo / quantita, 2) if quantita else 0
                    prezzo_cell = ws.cell(row=row, column=c, value=prezzo_unitario)
                    importo_cell = ws.cell(row=row, column=c + 1, value=importo)
                    prezzo_cell.number_format = EUR_FMT
                    importo_cell.number_format = EUR_FMT
                    totale_row_by_impresa[nome].append(row)
                prezzo_cell.border = BORDER
                importo_cell.border = BORDER
            row += 1

    totale_label_cell = ws.cell(row=row, column=1, value="TOTALE")
    totale_label_cell.font = TOTALE_FONT
    totale_label_cell.fill = TOTALE_FILL
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    for nome in imprese:
        c = impresa_col_start[nome]
        ws.cell(row=row, column=c).fill = TOTALE_FILL
        importo_cell = ws.cell(row=row, column=c + 1, value=round(confronto["totali"].get(nome, 0.0), 2))
        importo_cell.font = TOTALE_FONT
        importo_cell.fill = TOTALE_FILL
        importo_cell.number_format = EUR_FMT
    row += 2

    non_quotate = confronto.get("non_quotate") or {}
    if any(non_quotate.values()):
        nota_cell = ws.cell(row=row, column=1, value="Voci non quotate da alcune imprese:")
        nota_cell.font = Font(bold=True, italic=True, size=9)
        row += 1
        for nome in imprese:
            numeri = non_quotate.get(nome) or []
            if not numeri:
                continue
            testo = f"• {nome}: voce/i n. " + ", ".join(str(n) for n in numeri)
            ws.cell(row=row, column=1, value=testo).font = Font(italic=True, size=9)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col - 1)
            row += 1

    dichiarati = confronto.get("totali_dichiarati") or {}
    if any(v is not None for v in dichiarati.values()):
        row += 1
        ws.cell(row=row, column=1, value="Totale dichiarato direttamente dall'impresa sul proprio preventivo "
                                          "(a titolo di controllo incrociato col totale ricalcolato sopra):").font = \
            Font(italic=True, size=9)
        row += 1
        for nome, val in dichiarati.items():
            if val is None:
                continue
            ws.cell(row=row, column=1, value=f"• {nome}: € {val:,.2f}").font = Font(italic=True, size=9)
            row += 1

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 55
    ws.column_dimensions["D"].width = 8
    ws.column_dimensions["E"].width = 12
    for nome in imprese:
        c = impresa_col_start[nome]
        ws.column_dimensions[get_column_letter(c)].width = 14
        ws.column_dimensions[get_column_letter(c + 1)].width = 14
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    wb.save(out_path)
    return out_path
