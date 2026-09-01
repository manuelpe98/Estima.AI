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
    ("scavi", "piscina", "PLC-SCA-PISC-01",
     "Scavo a sezione obbligata per la formazione della vasca piscina, con carico e trasporto a discarica "
     "del materiale eccedente", "m3", 22.00),

    # Strutture in elevazione — cemento armato (pilastri e travi): calcestruzzo,
    # casseforme e acciaio come voci distinte.
    ("strutture_cls", "standard", "PLC-CLS-01",
     "Fornitura e posa in opera di calcestruzzo a prestazione garantita per la realizzazione di pilastri e "
     "travi in elevazione, gettato in opera con pompa o altro mezzo di movimentazione, diametro massimo "
     "aggregati 32 mm, consistenza S4/S5, compresa la vibratura; esclusi ferro e casseforme (computati a "
     "parte). Classe di resistenza: C28/35 – XC1. Compreso ogni onere necessario per dare la lavorazione "
     "eseguita a regola d'arte.", "m3", 220.00),
    ("strutture_cls", "casseforme", "PLC-CLS-CAS-01",
     "Casseforme per getti di calcestruzzo in elevazione (pilastri e travi), eseguite con pannelli metallici "
     "modulari e pedane in legno, eseguite fino a 4,50 m dal piano d'appoggio, comprese le armature di "
     "sostegno e di controvento, il disarmante, la manutenzione ed il disarmo, in modo da ottenere superfici "
     "regolari e planari. Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.",
     "m2", 60.00),
    ("strutture_ferro", "standard", "PLC-FER-01",
     "Fornitura e posa in opera di acciaio in barre ad aderenza migliorata per cemento armato, qualità B450C, "
     "conforme alla norma UNI EN 10080 ed ai Criteri Ambientali Minimi (D.M. 23/06/2022), per l'armatura di "
     "pilastri e travi in elevazione; compresa la lavorazione, la sagomatura, la posa, i sormonti, lo sfrido "
     "e le legature. Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.",
     "kg", 2.20),

    # Spinottature di ripresa getto — non quantificabili in modo affidabile dalla sola
    # pianta architettonica (dipendono dal progetto strutturale esecutivo): voce
    # sempre presente quando c'è struttura in c.a., ma segnaposto da completare a mano.
    ("spinottature", "standard", "PLC-SPI-01",
     "Esecuzione di spinottature di collegamento su strutture in calcestruzzo armato, mediante perforazione "
     "del calcestruzzo, pulizia del foro ed inghisaggio di barre/spinotti con resina epossidica o malta "
     "colabile ad alte prestazioni, per la ripresa di getto e la solidarizzazione delle nuove strutture — "
     "quantità dipendente dal progetto strutturale esecutivo, non desumibile dalla sola pianta architettonica: "
     "quantità e prezzo da completare manualmente. Compreso ogni onere necessario per dare la lavorazione "
     "eseguita a regola d'arte.", "n.", 0.00),

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

    # Fondazioni — scomposte come nel computo tradizionale: magrone, calcestruzzo,
    # casseforme e acciaio come voci distinte (non più un'unica voce "a corpo forfettario").
    ("fondazioni", "magrone", "PLC-FND-MAGR-01",
     "Fornitura e posa in opera di calcestruzzo magro di pulizia e livellamento (magrone) per la formazione "
     "del piano di posa delle fondazioni, classe di resistenza C12/15, gettato in opera dello spessore medio "
     "indicato, compresa la livellatura della superficie superiore; escluse armature e casseforme. Compreso "
     "ogni onere necessario per dare la lavorazione eseguita a regola d'arte.", "m3", 110.00),
    ("fondazioni", "standard", "PLC-FND-CLS-01",
     "Fornitura e posa in opera di calcestruzzo a prestazione garantita per la realizzazione delle fondazioni "
     "(platea o travi rovesce e cordoli), gettato in opera con pompa o altro mezzo di movimentazione, diametro "
     "massimo aggregati 32 mm, consistenza S4/S5, compresa la vibratura; esclusi ferro, casseforme e magrone "
     "di sottofondazione (computati a parte). Classe di resistenza e di esposizione: C28/35 – XC2. Compreso "
     "ogni onere necessario per dare la lavorazione eseguita a regola d'arte.", "m3", 230.00),
    ("fondazioni", "casseforme", "PLC-FND-CAS-01",
     "Casseforme per getti di calcestruzzo in fondazione (platea, travi rovesce, cordoli e muri controterra "
     "di fondazione), eseguite con pannelli in legno o metallici fino a 4,50 m dal piano d'appoggio, comprese "
     "le armature di sostegno, il disarmante, la manutenzione ed il disarmo. Compreso ogni onere necessario "
     "per dare la lavorazione eseguita a regola d'arte.", "m2", 45.00),
    ("fondazioni", "acciaio", "PLC-FND-FER-01",
     "Fornitura e posa in opera di acciaio in barre ad aderenza migliorata per cemento armato, qualità B450C, "
     "conforme alla norma UNI EN 10080 ed ai Criteri Ambientali Minimi (D.M. 23/06/2022), per l'armatura delle "
     "fondazioni; compresa la lavorazione, la sagomatura, la posa, i sormonti, lo sfrido e le legature. "
     "Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.", "kg", 2.10),

    # Approntamento di cantiere (a corpo — il prezzo unitario è sovrascritto a runtime
    # dal parametro "costo_approntamento_cantiere_eur", perché il costo reale dipende
    # molto dalla dimensione/durata del cantiere e non è deducibile dalla sola pianta)
    ("cantiere", "approntamento", "PLC-CNT-01",
     "Approntamento e installazione del cantiere edile, comprensivo di ogni opera e apprestamento necessario "
     "alla messa in sicurezza dell'area di lavoro per l'intera durata dei lavori: baracche prefabbricate ad "
     "uso spogliatoio/ufficio di cantiere e ricovero attrezzi, servizio igienico chimico, dispositivi di "
     "protezione collettiva e cartellonistica di sicurezza, impianto elettrico e idrico di cantiere, "
     "recinzione perimetrale dell'area con accessi carrai e pedonali, aree di stoccaggio dei materiali, "
     "mantenimento in efficienza per l'intera durata dei lavori e sgombero/pulizia finale a opere ultimate. "
     "Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.", "corpo", 1.00),

    # Solai — pacchetto completo "a corpo" (laterocemento/predalles: usato di default,
    # struttura+soletta in un'unica voce) oppure scomposto in casseforme/calcestruzzo/
    # acciaio se il capitolato indica un solaio gettato in opera (soletta piena).
    ("solai", "standard", "PLC-SOL-01",
     "Solaio in laterocemento (o predalles) completo di soletta collaborante, esclusa la finitura di pavimento "
     "(computata a parte)", "m2", 90.00),
    ("solai", "casseforme", "PLC-SOL-CAS-01",
     "Casseforme per il getto del solaio in soletta piena, comprensive di pannellatura, orditura di sostegno "
     "e puntellazione, eseguite fino a 4,50 m dal piano d'appoggio, compreso il disarmante, la manutenzione "
     "ed il disarmo. Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.",
     "m2", 38.00),
    ("solai", "calcestruzzo", "PLC-SOL-CLS-01",
     "Fornitura e posa in opera di calcestruzzo a prestazione garantita per la realizzazione del solaio in "
     "soletta piena, gettato in opera con pompa, diametro massimo aggregati 32 mm, consistenza S4/S5, "
     "compresa la vibratura; esclusi ferro e casseforme. Classe di resistenza e di esposizione: C28/35 – "
     "XC1/XC2. Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.",
     "m3", 230.00),
    ("solai", "acciaio", "PLC-SOL-FER-01",
     "Fornitura e posa in opera di acciaio in barre ad aderenza migliorata per cemento armato, qualità B450C, "
     "conforme alla norma UNI EN 10080 ed ai Criteri Ambientali Minimi (D.M. 23/06/2022), per l'armatura del "
     "solaio in soletta piena; compresa la lavorazione, la sagomatura, la posa, i sormonti, lo sfrido e le "
     "legature. Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.",
     "kg", 2.20),

    # Vespaio aerato sotto la pavimentazione del piano terra/interrato (solo se
    # richiesto dal capitolato: "vespaio_aerato")
    ("vespaio", "standard", "PLC-VES-01",
     "Formazione di vespaio aerato sotto la pavimentazione, realizzato mediante casseri modulari a perdere in "
     "polipropilene riciclato tipo igloo, posati su piano predisposto, compresa la formazione delle aperture/"
     "condotti di aerazione, il getto di calcestruzzo di completamento delle cupole e della soletta superiore "
     "armata con rete elettrosaldata. Compreso ogni onere necessario per dare la lavorazione eseguita a "
     "regola d'arte.", "m2", 45.00),

    # Cartongesso — contropareti, pareti divisorie interne e velette (solo se
    # richiesti dal capitolato).
    ("contropareti", "standard", "PLC-CTP-01",
     "Formazione di contropareti interne in lastre di cartongesso, realizzate su orditura metallica zincata, "
     "comprese le lastre, l'eventuale interposizione di materassino isolante, la stuccatura e rasatura dei "
     "giunti previa posa di rete, la movimentazione del materiale e le assistenze. Compreso ogni onere "
     "necessario per dare la lavorazione eseguita a regola d'arte.", "m2", 65.00),
    ("pareti_divisorie", "Muratura in laterizio forato", "PLC-PDI-01",
     "Formazione di pareti divisorie interne in blocchi di laterizio forato, eseguita con malta di allettamento, "
     "compresa la formazione dei piani di lavoro e l'ammorsamento alle strutture adiacenti. Compreso ogni "
     "onere necessario per dare la lavorazione eseguita a regola d'arte.", "m2", 42.00),
    ("pareti_divisorie", "Cartongesso su orditura metallica", "PLC-PDI-02",
     "Formazione di pareti divisorie interne in cartongesso, costituite da orditura metallica zincata e doppia "
     "lastra su entrambi i lati, compresa l'interposizione di materassino fonoisolante in lana minerale, la "
     "stuccatura e rasatura dei giunti previa posa di rete, la movimentazione del materiale e le assistenze. "
     "Compreso ogni onere necessario per dare la lavorazione eseguita a regola d'arte.", "m2", 70.00),
    ("pareti_divisorie", "Altro (specificare a parte)", "PLC-PDI-99",
     "Formazione di pareti divisorie interne — tipologia da definire, voce generica", "m2", 55.00),
    ("velette", "standard", "PLC-VEL-01",
     "Formazione di velette e/o gole luminose in cartongesso su orditura metallica (per la chiusura di soglie "
     "finestre e/o l'alloggiamento di illuminazione a led indiretta), comprese le lastre, la stuccatura e "
     "rasatura dei giunti e le assistenze — posizioni e sviluppo lineare da definire in base al progetto: "
     "quantità e prezzo da completare manualmente. Compreso ogni onere necessario per dare la lavorazione "
     "eseguita a regola d'arte.", "ml", 0.00),

    # Cappotto termico esterno (prezzo al m2 di parete, a spessore standard: correggere se lo spessore reale "
    # differisce sensibilmente da quello indicato nei parametri)
    ("cappotto_termico", "EPS/polistirene", "PLC-CAP-01",
     "Cappotto termico esterno in EPS, fornito e posto in opera, incluso rasatura e rete portaintonaco", "m2", 75.00),
    ("cappotto_termico", "Lana di roccia", "PLC-CAP-02",
     "Cappotto termico esterno in lana di roccia, fornito e posto in opera, incluso rasatura e rete portaintonaco",
     "m2", 85.00),
    ("cappotto_termico", "Fibra di legno", "PLC-CAP-03",
     "Cappotto termico esterno in fibra di legno, fornito e posto in opera, incluso rasatura e rete portaintonaco",
     "m2", 95.00),
    ("cappotto_termico", "Altro (specificare a parte)", "PLC-CAP-99",
     "Cappotto termico esterno — materiale da definire, voce generica", "m2", 80.00),

    # Impermeabilizzazioni (vespaio/fondazioni contro terra, prezzo al m2 di sedime)
    ("impermeabilizzazioni", "standard", "PLC-IMP-01",
     "Impermeabilizzazione e vespaio areato (o magrone + guaina) contro terra alla base dell'edificio",
     "m2", 35.00),
    ("impermeabilizzazioni", "piscina", "PLC-IMP-PISC-01",
     "Impermeabilizzazione della vasca piscina (pareti e fondo), guaina o rivestimento specifico per vasche",
     "m2", 55.00),

    # Piscina (scavo dedicato in "scavi"/piscina; qui vasca strutturale e bordo)
    ("piscina_vasca", "standard", "PLC-PSC-01",
     "Vasca piscina in calcestruzzo armato (pareti e fondo), gettata in opera, esclusi impermeabilizzazione, "
     "rivestimento e impianto di filtrazione (computati a parte)", "m2", 320.00),
    ("piscina_bordo", "standard", "PLC-PSC-02",
     "Pavimentazione del bordo perimetrale della piscina, antiscivolo, incluso sottofondo", "m2", 70.00),

    # Opere accessorie individuate ma NON quantificabili in modo affidabile dai soli elaborati
    # architettonici caricati in questa versione (richiedono la planimetria generale/rete
    # sottoservizi, le sezioni quotate o un rilievo dedicato): vengono comunque elencate come
    # voce, con quantità e prezzo a 0, da completare manualmente — invece di essere omesse.
    ("scala_esterna", "standard", "PLC-SCE-01",
     "Scala esterna (struttura, gradini e rivestimento) — individuata in pianta ma non quotata in modo "
     "misurabile automaticamente: quantità e prezzo da completare manualmente", "corpo", 0.00),
    ("opere_esterne", "recinzione", "PLC-OPE-01",
     "Recinzione esterna del lotto — non rappresentata nella pianta di progetto caricata: quantità e prezzo "
     "da completare manualmente in base alla planimetria generale", "ml", 0.00),
    ("opere_esterne", "smaltimento_acque", "PLC-OPE-02",
     "Rete di smaltimento acque bianche/nere esterne (tubazioni, pozzetti, pozzi perdenti) — non rappresentata "
     "nella pianta di progetto caricata: quantità e prezzo da completare manualmente in base alla planimetria "
     "generale/rete sottoservizi", "corpo", 0.00),
    ("opere_esterne", "pavimentazioni_esterne", "PLC-OPE-03",
     "Pavimentazioni esterne, marciapiedi e sistemazioni del sedime (solarium, vialetti, scivoli) — non "
     "quantificate in modo affidabile dalla sola pianta architettonica: quantità e prezzo da completare "
     "manualmente", "m2", 0.00),

    # Impianti (elettrico + idrico-sanitario + termico/climatizzazione insieme, a corpo, come percentuale
    # indicativa del resto del computo — l'importo è calcolato dalla pipeline, non da quantità x prezzo unitario)
    ("impianti_a_corpo", "standard", "PLC-IMP-CORPO-01",
     "Impianti (elettrico, idrico-sanitario, termico/climatizzazione) — stima a corpo, esclusa dal rilievo "
     "dettagliato in questa versione: valorizzata come percentuale indicativa del resto del computo, da "
     "sostituire con un computo impiantistico dedicato appena disponibile", "a corpo", 0.00),
]

# Impronta del contenuto di PLACEHOLDER_VOCI: il database dei prezzari vive su un
# volume persistente (non viene ricreato ad ogni deploy), quindi senza questo
# controllo una modifica a questa lista non raggiungerebbe mai un'istanza già
# avviata in precedenza (vedi db.ensure_placeholder_seed). Cambia automaticamente
# ad ogni modifica della lista qui sopra: non va aggiornata a mano.
import hashlib as _hashlib
PLACEHOLDER_SEED_VERSION = _hashlib.sha256(repr(PLACEHOLDER_VOCI).encode("utf-8")).hexdigest()[:16]
