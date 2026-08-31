"""Prezzario di ESEMPIO usato come default quando l'utente non ne carica uno.

ATTENZIONE: questi NON sono i prezzi ufficiali del Prezzario Regione Lombardia.
Sono valori segnaposto plausibili, usati solo per dimostrare la pipeline.
Il prezzario reale (regione/anno) va caricato dall'utente e salvato nel
database tramite `db.import_prezzario_from_rows`.
"""

PLACEHOLDER_PREZZARIO_META = {
    "regione": "Lombardia",
    "anno": 2026,
    "nome": "ESEMPIO PLACEHOLDER — non ufficiale, sostituire con il prezzario reale",
    "is_placeholder": True,
}

# categoria, sotto_tipo (deve combaciare con le opzioni in capitolato_engine.py),
# codice, descrizione, unita_misura, prezzo (€)
PLACEHOLDER_VOCI = [
    # Pavimenti (prezzo al m2, fornito e posto in opera)
    ("pavimenti", "Gres porcellanato standard", "PLC-PAV-01",
     "Fornitura e posa di pavimento in gres porcellanato standard, formato corrente, "
     "incluso sottofondo e materiali di allettamento", "m2", 38.00),
    ("pavimenti", "Gres porcellanato effetto legno/pietra", "PLC-PAV-02",
     "Fornitura e posa di pavimento in gres porcellanato effetto legno/pietra, "
     "formato grande, incluso sottofondo e materiali di allettamento", "m2", 48.00),
    ("pavimenti", "Parquet prefinito", "PLC-PAV-03",
     "Fornitura e posa di parquet prefinito multistrato, incluso sottofondo e finitura", "m2", 65.00),
    ("pavimenti", "Marmo/pietra naturale", "PLC-PAV-04",
     "Fornitura e posa di pavimento in marmo/pietra naturale, incluso sottofondo", "m2", 110.00),
    ("pavimenti", "Altro (specificare a parte)", "PLC-PAV-99",
     "Fornitura e posa di pavimentazione — tipologia da definire, voce generica", "m2", 50.00),

    # Pareti interne: intonaco + tinteggiatura (prezzo al m2 di parete)
    ("pareti_interne", "Intonaco tradizionale + pittura lavabile", "PLC-INT-01",
     "Intonaco civile tradizionale a due strati e tinteggiatura con pittura lavabile", "m2", 22.00),
    ("pareti_interne", "Rasatura civile + pittura", "PLC-INT-02",
     "Rasatura civile su supporto esistente e tinteggiatura con pittura", "m2", 18.00),
    ("pareti_interne", "Intonaco premiscelato + pittura decorativa", "PLC-INT-03",
     "Intonaco premiscelato a macchina e tinteggiatura con pittura decorativa", "m2", 30.00),
    ("pareti_interne", "Altro (specificare a parte)", "PLC-INT-99",
     "Trattamento pareti interne — tipologia da definire, voce generica", "m2", 20.00),

    # Serramenti esterni (prezzo al m2 di serramento)
    ("serramenti_esterni", "PVC doppio vetro basso emissivo", "PLC-SER-01",
     "Fornitura e posa serramento esterno in PVC con vetrocamera doppio basso emissivo", "m2", 380.00),
    ("serramenti_esterni", "Alluminio a taglio termico doppio vetro", "PLC-SER-02",
     "Fornitura e posa serramento esterno in alluminio a taglio termico con vetrocamera doppia", "m2", 480.00),
    ("serramenti_esterni", "Legno doppio vetro", "PLC-SER-03",
     "Fornitura e posa serramento esterno in legno con vetrocamera doppia", "m2", 520.00),
    ("serramenti_esterni", "Alluminio/PVC triplo vetro", "PLC-SER-04",
     "Fornitura e posa serramento esterno alluminio/PVC con vetrocamera tripla", "m2", 560.00),
    ("serramenti_esterni", "Altro (specificare a parte)", "PLC-SER-99",
     "Fornitura e posa serramento esterno — tipologia da definire, voce generica", "m2", 450.00),
    ("serramenti_esterni", "__FALLBACK_NO_DIM__", "PLC-SER-98",
     "Fornitura e posa serramento esterno — dimensioni non disponibili da abaco, "
     "prezzo indicativo a corpo per unità", "cad", 450.00),

    # Porte interne (prezzo a corpo per pezzo, completo di telaio)
    ("porte_interne", "Porta tamburata laminata standard", "PLC-POR-01",
     "Fornitura e posa porta interna tamburata laminata, completa di telaio e ferramenta", "cad", 280.00),
    ("porte_interne", "Porta tamburata laccata", "PLC-POR-02",
     "Fornitura e posa porta interna tamburata laccata, completa di telaio e ferramenta", "cad", 380.00),
    ("porte_interne", "Porta in legno massello", "PLC-POR-03",
     "Fornitura e posa porta interna in legno massello, completa di telaio e ferramenta", "cad", 650.00),
    ("porte_interne", "Porta rasomuro (a filo muro, a scomparsa)", "PLC-POR-04",
     "Fornitura e posa porta interna rasomuro a filo muro, completa di controtelaio a scomparsa e ferramenta dedicata",
     "cad", 780.00),
    ("porte_interne", "Altro (specificare a parte)", "PLC-POR-99",
     "Fornitura e posa porta interna — tipologia da definire, voce generica", "cad", 320.00),

    # Impianto elettrico (a corpo per locale)
    ("impianto_elettrico", "Standard (normativa base)", "PLC-ELE-01",
     "Impianto elettrico a norma per locale tipo, in tracce su muratura", "cad", 450.00),
    ("impianto_elettrico", "Predisposizione domotica", "PLC-ELE-02",
     "Impianto elettrico con predisposizione domotica per locale tipo", "cad", 650.00),
    ("impianto_elettrico", "Domotica completa", "PLC-ELE-03",
     "Impianto elettrico domotico completo per locale tipo", "cad", 1200.00),
    ("impianto_elettrico", "Altro (specificare a parte)", "PLC-ELE-99",
     "Impianto elettrico per locale tipo — livello da definire, voce generica", "cad", 500.00),

    # Impianto idrico-sanitario (a corpo per locale bagno/cucina)
    ("impianto_idrico", "Sanitari e rubinetteria standard", "PLC-IDR-01",
     "Impianto idrico-sanitario con sanitari e rubinetteria standard per locale bagno/cucina", "cad", 600.00),
    ("impianto_idrico", "Fascia media", "PLC-IDR-02",
     "Impianto idrico-sanitario con sanitari e rubinetteria di fascia media", "cad", 900.00),
    ("impianto_idrico", "Fascia alta", "PLC-IDR-03",
     "Impianto idrico-sanitario con sanitari e rubinetteria di fascia alta", "cad", 1500.00),
    ("impianto_idrico", "Altro (specificare a parte)", "PLC-IDR-99",
     "Impianto idrico-sanitario per locale bagno/cucina — fascia da definire, voce generica", "cad", 700.00),

    # Scavi
    ("scavi", "standard", "PLC-SCA-01",
     "Scavo di sbancamento a sezione ampia per la formazione del sedime di fondazione, "
     "con carico e trasporto a discarica del materiale eccedente", "m3", 18.00),

    # Strutture in elevazione — cemento armato (pilastri e travi)
    ("strutture_cls", "standard", "PLC-CLS-01",
     "Calcestruzzo per strutture in elevazione (pilastri e travi) C25/30, gettato in opera", "m3", 220.00),
    ("strutture_ferro", "standard", "PLC-FER-01",
     "Acciaio in barre sagomate B450C per strutture in c.a.", "kg", 2.20),

    # Strutture in elevazione — muratura portante
    ("strutture_muratura", "standard", "PLC-MUR-01",
     "Muratura portante in blocchi di laterizio, per strutture in elevazione", "m3", 180.00),

    # Coperture (prezzo al m2 di falda/superficie reale, fornitura e posa completa)
    ("copertura", "Tetto a falde, manto in laterizio", "PLC-COP-01",
     "Copertura a falde con manto in tegole di laterizio, incluso pacchetto isolante e sottostruttura", "m2", 95.00),
    ("copertura", "Tetto a falde, manto in cemento", "PLC-COP-02",
     "Copertura a falde con manto in tegole di cemento, incluso pacchetto isolante e sottostruttura", "m2", 85.00),
    ("copertura", "Copertura piana con guaina bituminosa", "PLC-COP-03",
     "Copertura piana impermeabilizzata con guaina bituminosa, incluso pacchetto isolante", "m2", 60.00),
    ("copertura", "Copertura metallica", "PLC-COP-04",
     "Copertura con lastre metalliche grecate, incluso pacchetto isolante e sottostruttura", "m2", 110.00),
    ("copertura", "Altro (specificare a parte)", "PLC-COP-99",
     "Copertura — tipologia da definire, voce generica", "m2", 80.00),

    # Demolizioni (solo per ristrutturazione, confronto stato di fatto / progetto)
    ("demolizioni", "pavimento", "PLC-DEM-PAV",
     "Demolizione di pavimentazione esistente, incluso trasporto a discarica delle macerie", "m2", 15.00),
    ("demolizioni", "intonaco", "PLC-DEM-INT",
     "Demolizione di intonaco esistente su pareti, incluso trasporto a discarica delle macerie", "m2", 12.00),
]
