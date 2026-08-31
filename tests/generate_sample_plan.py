"""Genera i PDF di prova usati per testare l'intera pipeline (nuova
costruzione e ristrutturazione) senza dover procurarsi elaborati CAD veri:

  sample_plan.pdf         pianta di progetto (4 vani) + abaco serramenti
  sample_plan_sdf.pdf     stato di fatto: gli stessi 4 vani + un RIPOSTIGLIO
                          in più, che nel progetto viene demolito
  sample_strutturale.pdf  pianta strutturale (pilastri/travi taggati) + abaco
  sample_copertura.pdf    sagoma di copertura quotata (un solo vano "COPERTURA")

Quantità reali note (usate dalle asserzioni in test_pipeline.py):
  SOGGIORNO  5.0 x 4.0 m  area 20.0 m2  perimetro 18.0 m
  CUCINA     3.0 x 4.0 m  area 12.0 m2  perimetro 14.0 m
  CAMERA     5.0 x 3.5 m  area 17.5 m2  perimetro 17.0 m
  BAGNO      3.0 x 3.5 m  area 10.5 m2  perimetro 13.0 m
  RIPOSTIGLIO (solo stato di fatto)  2.0 x 2.0 m  area 4.0 m2  perimetro 8.0 m
  COPERTURA  8.0 x 8.0 m  area 64.0 m2
  Pilastri PL1 x4, sezione 30x30 cm | Travi TR1 x4, sezione 30x50 cm
"""
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

SCALE = 100
PT_PER_M = 1000 / ((25.4 / 72) * SCALE)
ORIGIN = (80, 380)


def m2pt(x_m, y_m, origin=ORIGIN):
    ox, oy = origin
    return ox + x_m * PT_PER_M, oy + y_m * PT_PER_M


def draw_room(c, x0, y0, w, h, label, quotes, origin=ORIGIN):
    px0, py0 = m2pt(x0, y0, origin)
    pw, ph = w * PT_PER_M, h * PT_PER_M
    c.setLineWidth(1.2)
    c.rect(px0, py0, pw, ph, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(px0 + pw / 2, py0 + ph / 2, label)
    c.setFont("Helvetica", 7)
    c.drawCentredString(px0 + pw / 2, py0 - 10, quotes[0])
    c.drawString(px0 - 28, py0 + ph / 2, quotes[1])


def build_architectural_plan(path: str, include_ripostiglio: bool):
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 12)
    titolo = "PIANTA PIANO TERRA - STATO DI FATTO" if include_ripostiglio else "PIANTA PIANO TERRA - STATO DI PROGETTO"
    c.drawString(80, 760, titolo)
    c.setFont("Helvetica", 10)
    c.drawString(80, 745, "SCALA 1:100")

    draw_room(c, 0, 4, 5, 4, "SOGGIORNO", ("500", "400"))
    draw_room(c, 5, 4, 3, 4, "CUCINA", ("300", "400"))
    draw_room(c, 0, 0, 5, 3.5, "CAMERA", ("500", "350"))
    draw_room(c, 5, 0, 3, 3.5, "BAGNO", ("300", "350"))
    if include_ripostiglio:
        draw_room(c, 8, 4, 2, 2, "RIPOSTIGLIO", ("200", "200"))

    c.setFont("Helvetica-Bold", 8)
    px, py = m2pt(2.5, 4); c.drawCentredString(px, py + 2, "P1")
    px, py = m2pt(4, 1.75); c.drawCentredString(px, py + 2, "P1")
    px, py = m2pt(0, 6); c.drawCentredString(px + 5, py, "P1")
    px, py = m2pt(2.5, 8); c.drawCentredString(px, py - 10, "F1")
    px, py = m2pt(2.5, 0); c.drawCentredString(px, py + 10, "F1")
    px, py = m2pt(6.5, 8); c.drawCentredString(px, py - 10, "F2")
    px, py = m2pt(6.5, 0); c.drawCentredString(px, py + 10, "F3")

    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(80, 760, "ABACO SERRAMENTI")
    c.setFont("Helvetica", 10)
    lines = [
        "P1 - 90x210 cm - porta interna",
        "F1 - 120x150 cm - finestra",
        "F2 - 100x120 cm - finestra",
        "F3 - dimensioni da rilevare in cantiere",
    ]
    y = 730
    for line in lines:
        c.drawString(80, y, line)
        y -= 18
    c.save()


def build_structural_plan(path: str):
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(80, 760, "PIANTA STRUTTURALE PIANO TERRA")
    c.setFont("Helvetica", 10)
    c.drawString(80, 745, "SCALA 1:100")

    # sagoma edificio 8x8 m
    px0, py0 = m2pt(0, 0)
    pw = ph = 8 * PT_PER_M
    c.setLineWidth(1.2)
    c.rect(px0, py0, pw, ph, stroke=1, fill=0)

    # quote
    c.setFont("Helvetica", 8)
    c.drawCentredString(px0 + pw / 2, py0 - 12, "800")
    c.drawString(px0 - 26, py0 + ph / 2, "800")
    c.drawCentredString(px0 + pw / 2, py0 + ph + 6, "800")
    c.drawString(px0 + pw + 6, py0 + ph / 2, "800")
    c.drawCentredString(px0 + pw / 4, py0 - 12, "400")
    c.drawCentredString(px0 + 3 * pw / 4, py0 - 12, "400")

    # 4 pilastri "PL1" agli angoli (disegnati come piccoli quadrati pieni) e
    # 4 travi "TR1" a metà lato (segmenti), per dare al PDF contenuto
    # vettoriale sufficiente oltre al solo perimetro
    c.setFont("Helvetica-Bold", 7)
    corners = [(0.3, 0.3), (7.7, 0.3), (0.3, 7.7), (7.7, 7.7)]
    pil_side = 0.3 * PT_PER_M
    for x, y in corners:
        px, py = m2pt(x, y)
        c.rect(px - pil_side / 2, py - pil_side / 2, pil_side, pil_side, stroke=1, fill=0)
        c.drawCentredString(px, py + pil_side / 2 + 8, "PL1")
    mids = [(4, 0.3), (4, 7.7), (0.3, 4), (7.7, 4)]
    for x, y in mids:
        px, py = m2pt(x, y)
        c.line(px - 15, py, px + 15, py)
        c.drawCentredString(px, py + 8, "TR1")

    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(80, 760, "ABACO PILASTRI E TRAVI")
    c.setFont("Helvetica", 10)
    c.drawString(80, 730, "PL1 - 30x30 cm - pilastro in c.a.")
    c.drawString(80, 712, "TR1 - 30x50 cm - trave in c.a.")
    c.save()


def build_roof_plan(path: str):
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(80, 760, "PIANTA COPERTURA")
    c.setFont("Helvetica", 10)
    c.drawString(80, 745, "SCALA 1:100")

    px0, py0 = m2pt(0, 0)
    pw = ph = 8 * PT_PER_M
    c.setLineWidth(1.2)
    c.rect(px0, py0, pw, ph, stroke=1, fill=0)
    # linea di colmo e due tratti di falda, solo per dare contenuto vettoriale
    # oltre al perimetro (non usati nel calcolo, che si basa sul poligono)
    c.line(px0, py0 + ph / 2, px0 + pw, py0 + ph / 2)
    c.line(px0 + pw / 2, py0, px0 + pw / 2, py0 + ph / 2)
    c.line(px0 + pw / 2, py0 + ph / 2, px0 + pw / 2, py0 + ph)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(px0 + pw / 2, py0 + ph / 2 + 15, "COPERTURA")
    c.setFont("Helvetica", 8)
    c.drawCentredString(px0 + pw / 2, py0 - 12, "800")
    c.drawString(px0 - 26, py0 + ph / 2, "800")
    c.drawCentredString(px0 + pw / 2, py0 + ph + 6, "800")
    c.drawString(px0 + pw + 6, py0 + ph / 2, "800")
    c.drawCentredString(px0 + pw / 4, py0 - 12, "400")
    c.drawCentredString(px0 + 3 * pw / 4, py0 - 12, "400")
    c.save()


if __name__ == "__main__":
    build_architectural_plan("tests/sample_plan.pdf", include_ripostiglio=False)
    build_architectural_plan("tests/sample_plan_sdf.pdf", include_ripostiglio=True)
    build_structural_plan("tests/sample_strutturale.pdf")
    build_roof_plan("tests/sample_copertura.pdf")
    print("Creati: sample_plan.pdf, sample_plan_sdf.pdf, sample_strutturale.pdf, sample_copertura.pdf")
