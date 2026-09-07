"""Test end-to-end della pipeline estesa (finiture + strutture + scavi +
copertura + confronto stato di fatto/progetto) sui PDF sintetici di prova."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pdf_validation import validate_pdf
from backend.models import ProjectMeta
from backend.pipeline import run_pipeline

DIR = Path(__file__).parent
DB_PATH = str(DIR / "test_prezzari.db")

BASE_ANSWERS = {
    "pavimenti": "Gres porcellanato standard",
    "pareti_interne": "Intonaco tradizionale + pittura lavabile",
    "serramenti_esterni": "PVC doppio vetro basso emissivo",
    "porte_interne": "Porta tamburata laminata standard",
    "impianto_elettrico": "Standard (normativa base)",
    "impianto_idrico": "Sanitari e rubinetteria standard",
    "tipo_struttura": "Cemento armato (pilastri e travi)",
    "copertura_tipo": "Tetto a falde, manto in laterizio",
}


def approx(a, b, tol=0.05):
    return abs(a - b) <= tol


def test_nuova_costruzione():
    print("\n" + "=" * 60)
    print("TEST 1: nuova costruzione (finiture + strutture + scavi + copertura)")
    print("=" * 60)
    Path(DB_PATH).unlink(missing_ok=True)
    meta = ProjectMeta(nome_progetto="Progetto di prova", committente="Mario Rossi (test)",
                        ubicazione="Via di prova 1, Test (XX)")
    result = run_pipeline(
        tipo_intervento="nuova_costruzione",
        pdf_progetto_path=str(DIR / "sample_plan.pdf"),
        db_path=DB_PATH, meta=meta, answers=BASE_ANSWERS, parametri_overrides={},
        pdf_strutturale_path=str(DIR / "sample_strutturale.pdf"),
        pdf_copertura_path=str(DIR / "sample_copertura.pdf"),
        legend_page=1, structural_legend_page=1,
        excel_out=str(DIR / "out_nc_computo.xlsx"),
        primus_out=str(DIR / "out_nc_primus.xlsx"),
        word_out=str(DIR / "out_nc_computo.docx"),
    )
    assert result.ok, result.errors

    print("-- Vani (senza filtro spessore linea: i muri di prova sono ora sottili, 1.2pt) --")
    for r in result.rooms:
        print(f"  {r.label}: area={r.area_m2} m2  perimetro={r.perimeter_m} m")
    assert len(result.rooms) == 4, f"Attesi 4 vani, trovati {len(result.rooms)}"
    expected = {"SOGGIORNO": (20.0, 18.0), "CUCINA": (12.0, 14.0),
                "CAMERA": (17.5, 17.0), "BAGNO": (10.5, 13.0)}
    found = {r.label.upper(): r for r in result.rooms}
    for label, (area, perim) in expected.items():
        r = found[label]
        assert approx(r.area_m2, area) and approx(r.perimeter_m, perim), (label, r)
    print("OK: il riconoscimento vani funziona anche con muri a spessore linea sottile "
          "(criterio di contenimento, non più spessore penna).")

    print("\n-- Sedime edificio e copertura --")
    print(f"  Sedime (per scavi): {result.footprint_area_m2} m2")
    print(f"  Copertura (pianta, da file dedicato): {result.roof_area_m2} m2")
    assert result.footprint_area_m2 > 40, "Il sedime dovrebbe essere un inviluppo plausibile dei 4 vani"
    assert approx(result.roof_area_m2, 64.0, tol=0.5), f"Copertura attesa ~64 m2, trovata {result.roof_area_m2}"

    print("\n-- Elementi strutturali --")
    for e in result.structural_elements:
        print(f"  {e.code} ({e.kind}) x{e.count}  {e.dim1_cm}x{e.dim2_cm} cm")
    se_by_code = {e.code: e for e in result.structural_elements}
    assert se_by_code["PL1"].count == 4 and se_by_code["PL1"].dim1_cm == 30
    assert se_by_code["TR1"].count == 4 and se_by_code["TR1"].dim1_cm == 30 and se_by_code["TR1"].dim2_cm == 50
    print("OK: pilastri e travi riconosciuti da sigla + abaco sulla pianta strutturale.")

    print("\n-- Voci di computo --")
    categorie_attese = {"Pavimenti", "Pareti interne", "Serramenti esterni", "Porte interne",
                         "Impianti (a corpo)", "Scavi", "Fondazioni", "Solai", "Cappotto termico esterno",
                         "Impermeabilizzazioni",
                         "Strutture in elevazione (calcestruzzo)", "Strutture in elevazione (acciaio)",
                         "Copertura"}
    categorie_trovate = {v.categoria for v in result.voci}
    for v in result.voci:
        print(f"  [{v.codice}] {v.categoria} — {v.quantita} {v.unita_misura} x {v.prezzo_unitario} € = {v.importo} €")
    mancanti = categorie_attese - categorie_trovate
    assert not mancanti, f"Categorie mancanti nel computo: {mancanti}"
    print(f"\nTOTALE: € {result.totale:,.2f}")
    assert result.excel_path and Path(result.excel_path).exists()
    assert result.primus_path and Path(result.primus_path).exists()
    assert result.word_path and Path(result.word_path).exists()
    print("OK: nessuna categoria di lavorazione mancante; export Excel, PriMus e Word generati.")


def test_ristrutturazione():
    print("\n" + "=" * 60)
    print("TEST 2: ristrutturazione (confronto stato di fatto / progetto)")
    print("=" * 60)
    meta = ProjectMeta(nome_progetto="Progetto ristrutturazione test", committente="Anna Bianchi (test)")
    result = run_pipeline(
        tipo_intervento="ristrutturazione",
        pdf_progetto_path=str(DIR / "sample_plan.pdf"),
        pdf_stato_di_fatto_path=str(DIR / "sample_plan_sdf.pdf"),
        db_path=DB_PATH, meta=meta, answers=BASE_ANSWERS, parametri_overrides={},
        legend_page=1,
        excel_out=str(DIR / "out_ristr_computo.xlsx"),
        primus_out=str(DIR / "out_ristr_primus.xlsx"),
        word_out=str(DIR / "out_ristr_computo.docx"),
    )
    assert result.ok, result.errors

    print("-- Confronto stato di fatto / progetto --")
    for c in result.confronto:
        print(f"  {c.label}: {c.stato}  (SDF={c.area_sdf_m2}  SDP={c.area_sdp_m2})")
    ripostiglio = next(c for c in result.confronto if c.label == "RIPOSTIGLIO")
    assert ripostiglio.stato == "demolito", "Il RIPOSTIGLIO presente solo nello stato di fatto deve risultare demolito"
    invariati = [c for c in result.confronto if c.stato == "invariato"]
    assert len(invariati) == 4, "I 4 vani presenti in entrambi gli stati devono risultare invariati"
    print("OK: il vano presente solo nello stato di fatto è correttamente segnalato come demolito.")

    demolizioni = [v for v in result.voci if v.categoria == "Demolizioni"]
    assert demolizioni, "Devono comparire righe di demolizione nel computo"
    for v in demolizioni:
        print(f"  [{v.codice}] {v.categoria} — {v.quantita} {v.unita_misura} — {v.note}")
    print("OK: le voci di demolizione per il vano rimosso sono presenti nel computo.")


def test_pdf_non_conforme_rifiutato():
    print("\n" + "=" * 60)
    print("TEST 3: PDF non conforme viene rifiutato")
    print("=" * 60)
    from reportlab.pdfgen import canvas as rl_canvas
    bad_path = str(DIR / "bad_plan.pdf")
    c = rl_canvas.Canvas(bad_path)
    c.drawString(100, 700, "Pianta senza scala né quote")
    c.rect(100, 400, 200, 150)
    c.save()
    v = validate_pdf(bad_path)
    assert not v.is_valid
    print("Messaggi di rifiuto:", v.messages)
    print("OK: caricamento rifiutato con messaggio esplicito, come richiesto.")
    Path(bad_path).unlink(missing_ok=True)


def test_tavola_con_piu_piani():
    print("\n" + "=" * 60)
    print("TEST 4: tavola con più piani affiancati (piano terra + piano primo)")
    print("=" * 60)
    from backend.pipeline import extract_quantities
    res = extract_quantities(tipo_intervento="nuova_costruzione",
                              pdf_progetto_path=str(DIR / "sample_multi_plan.pdf"))
    assert res.ok, res.errors

    found = {r.label.upper(): r for r in res.rooms}
    assert len(found) == 4, f"Attesi 4 vani (2 per piano), trovati {len(found)}"
    print("-- Piano assegnato a ciascun vano --")
    for r in res.rooms:
        print(f"  {r.label}: area={r.area_m2} m2  piano={r.piano}")
    assert found["SOGGIORNO"].piano == "TERRA"
    assert found["CUCINA"].piano == "TERRA"
    assert found["CAMERA"].piano == "PRIMO"
    assert found["BAGNO"].piano == "PRIMO"
    print("OK: ogni vano è stato assegnato al piano giusto in base al titolo più vicino.")

    # Il sedime/perimetro deve venire SOLO dal piano terra (32 m2 / 24 m, vedi
    # generate_sample_plan.build_multi_plan): sommare anche il piano primo
    # (28 m2 in più) darebbe 60 m2, un sedime quasi doppio di quello reale.
    assert approx(res.footprint_area_m2, 32.0), res.footprint_area_m2
    assert approx(res.perimetro_esterno_m, 24.0), res.perimetro_esterno_m
    print(f"OK: sedime={res.footprint_area_m2} m2 e perimetro={res.perimetro_esterno_m} m calcolati "
          "SOLO dal piano terra, non sommando anche il piano primo.")

    assert any("più piani sullo stesso foglio" in n for n in res.note_metodologiche)
    assert any("SOLO i vani assegnati al piano terra" in n for n in res.note_metodologiche)
    print("OK: le note metodologiche spiegano la separazione automatica per piano.")


if __name__ == "__main__":
    test_nuova_costruzione()
    test_ristrutturazione()
    test_pdf_non_conforme_rifiutato()
    test_tavola_con_piu_piani()
    print("\n=== TUTTI I TEST SUPERATI ===")
