"""Prezzario di riferimento usato come default quando l'utente non ne carica uno.

Contiene una selezione curata di voci tratte dal Prezzario Regionale delle Opere
Pubbliche, edizione 2022, di Regione Lombardia (in collaborazione con il Comune di
Milano) — il prezzario ufficiale caricato da Franco il 04/09/2026, tenuto qui come
riferimento permanente da usare ogni volta che l'utente non carica un proprio
prezzario (CSV) e non ne seleziona uno diverso.

Ogni voce riporta nella descrizione il codice e il volume di provenienza. Non tutte
le combinazioni (categoria, sotto_tipo) hanno un corrispondente ufficiale 1:1 nel
prezzario regionale: dove necessario sono stati usati, con trasparenza dichiarata
nella descrizione stessa:
  - somme di due voci ufficiali (es. intonaco + pittura, vasca piscina + rivestimento);
  - la voce ufficiale più simile disponibile, quando manca una voce specifica
    (segnalate con "adattata"/"non essendo censita...");
  - riferimenti generici non ufficiali (prefisso RIF-...-99 o simili) per le opzioni
    "Altro (specificare a parte)" e per alcune voci sempre "da completare a mano"
    (il cui prezzo non incide comunque sul totale calcolato, es. spinottature,
    opere_esterne, acustica, scale).

Il catalogo completo del prezzario (oltre 35.000 articoli ufficiali) è stato
estratto dai PDF caricati ma non importato come prezzario separato consultabile:
resta un possibile sviluppo futuro se sarà utile poter scegliere singoli codici
ufficiali invece di questo set curato.

Un prezzario reale caricato dall'utente (tramite `db.import_prezzario_from_rows`)
ha comunque sempre la precedenza quando selezionato esplicitamente.
"""

PLACEHOLDER_PREZZARIO_META = {
    "regione": "Lombardia",
    "anno": 2022,
    "nome": "Prezzario Regione Lombardia 2022 (selezione di riferimento)",
    "is_placeholder": True,
}

# categoria, sotto_tipo (deve combaciare con le opzioni in capitolato_engine.py),
# codice, descrizione, unita_misura, prezzo (€)
PLACEHOLDER_VOCI = [
    ('pavimenti', 'Gres porcellanato standard', '1C.18.200.0030.g',
     "Pavimento in piastrelle di gres fine porcellanato a superficie liscia, spessore 8-10 mm, posato "
     "con boiacca di cemento su letto di malta o incollato, escluso il sottofondo — piastrelle 30x30 "
     "cm, colori chiari (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.18.200.0030.g)", 'm2', 28.97),
    ('pavimenti', 'Gres porcellanato effetto legno/pietra', '1C.18.200.0040.c',
     "Pavimento in piastrelle di clinker a superficie liscia, formato 30x30 cm, posato con boiacca di "
     "cemento o incollato, escluso il sottofondo — usato come riferimento più simile per gres in "
     "grande formato decorativo, non essendo censita una voce specifica 'effetto legno/pietra' "
     "(fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.18.200.0040.c)", 'm2', 55.84),
    ('pavimenti', 'Parquet prefinito', '1C.18.400.0020.a',
     "Pavimento in tavolette di legno di rovere Europa UNI B, incollate su supporto cementizio, "
     "comprese lamatura, ceratura e assistenze murarie (fonte: Prezzario Regione Lombardia 2022, vol. "
     "1.1, art. 1C.18.400.0020.a)", 'm2', 62.15),
    ('pavimenti', 'Marmo/pietra naturale', '1C.18.250.0010.a',
     "Pavimento in piastrelle di marmo Arabescato Corchia, 1a scelta, lastre calibrate e lucidate, "
     "formato piccolo (0,05-0,12 m², spessore 10 mm) (fonte: Prezzario Regione Lombardia 2022, vol. "
     "1.1, art. 1C.18.250.0010.a)", 'm2', 80.54),
    ('pavimenti', 'Altro (specificare a parte)', 'RIF-PAV-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): il Prezzario "
     "Regione Lombardia 2022 non prevede una voce 'generica' per pavimentazioni non specificate — "
     "sostituire con il materiale e il codice realmente previsti dal capitolato", 'm2', 56.88),
    ('pareti_interne', 'Intonaco tradizionale + pittura lavabile', '1C.07.110.0040 + 1C.24.120.0020.c',
     "Intonaco completo a civile per interni con malte tradizionali (1C.07.110.0040, € 18,88/m²) + "
     "idropittura acrilica traspirante superlavabile a due riprese (1C.24.120.0020.c, € 4,09/m²) — "
     "somma di due voci ufficiali del Prezzario Regione Lombardia 2022, vol. 1.1", 'm2', 22.97),
    ('pareti_interne', 'Rasatura civile + pittura', '1C.07.230.0010 + 1C.24.120.0020.a',
     "Rasatura a civile fine su superfici interne con rasante cementizio (1C.07.230.0010, € 8,50/m²) "
     "+ idropittura a base di copolimeri vinilversatati traspirante (1C.24.120.0020.a, € 3,71/m²) — "
     "somma di due voci ufficiali del Prezzario Regione Lombardia 2022, vol. 1.1", 'm2', 12.21),
    ('pareti_interne', 'Intonaco premiscelato + pittura decorativa', '1C.07.220.0010 + 1C.24.120.0040',
     "Intonaco completo per interni con premiscelato, finitura a civile fine, esecuzione manuale "
     "(1C.07.220.0010, € 22,69/m²) + rivestimento murale policromo a base di resine acriliche e chips "
     "colorati, applicato a spruzzo (1C.24.120.0040, € 14,97/m²) — somma di due voci ufficiali del "
     "Prezzario Regione Lombardia 2022, vol. 1.1", 'm2', 37.66),
    ('pareti_interne', 'Altro (specificare a parte)', 'RIF-PAR-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): sostituire con la "
     "lavorazione realmente prevista dal capitolato", 'm2', 24.28),
    ('serramenti_esterni', 'PVC doppio vetro basso emissivo', '1C.21.100.0010.b',
     "Finestre e porte finestre in PVC antiurto ad alta resistenza, telaio armato con profilati "
     "d'acciaio, antaribalta a due battenti, misurazione esterno telaio. NOTA: per convenzione del "
     "Prezzario regionale i vetri sono sempre esclusi dal prezzo delle lavorazioni (costo del "
     "vetrocamera basso emissivo da computare a parte con le voci del cap. 1C.23 — Opere da vetraio) "
     "(fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.21.100.0010.b)", 'm2', 201.67),
    ('serramenti_esterni', 'Alluminio a taglio termico doppio vetro', '1C.22.250.0010.b',
     "Serramenti in alluminio per finestre/portefinestre a uno o più battenti, profilati estrusi "
     "isolati a taglio termico, anodizzazione e verniciatura. Vetri esclusi per convenzione del "
     "Prezzario regionale (cap. 1C.23) (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.22.250.0010.b)", 'm2', 243.08),
    ('serramenti_esterni', 'Legno doppio vetro', '1C.21.010.0020.a',
     "Finestre e porte finestre in legno lamellare di abete/pino, telaio unico con controtelaio, a "
     "uno o più battenti, verniciatura a tre mani. Vetri esclusi per convenzione del Prezzario "
     "regionale (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.21.010.0020.a)", 'm2', 534.09),
    ('serramenti_esterni', 'Alluminio/PVC triplo vetro', '1C.22.250.0010.b (adattata)',
     "Il Prezzario Regione Lombardia 2022 non prevede una voce distinta per serramenti a triplo "
     "vetro: usato come riferimento il serramento in alluminio a taglio termico (1C.22.250.0010.b, € "
     "243,08/m², vetri esclusi) — il costo reale di una versione a triplo vetro è superiore, verifica "
     "e correggi", 'm2', 243.08),
    ('serramenti_esterni', 'Altro (specificare a parte)', 'RIF-SER-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): sostituire con il "
     "serramento realmente previsto dal capitolato", 'm2', 305.47),
    ('serramenti_esterni', '__FALLBACK_NO_DIM__', '1C.21.100.0010.b (stima a corpo)',
     "Finestra con dimensioni non rilevate: prezzo indicativo a corpo stimato da un serramento medio "
     "di circa 1,4 m² in PVC (1C.21.100.0010.b, € 201,67/m² x 1,4 m²) — da correggere appena "
     "disponibili le misure reali", 'cad', 282.34),
    ('porte_interne', 'Porta tamburata laminata standard', '1C.21.200.0010.a',
     "Porta interna a battente a un'anta, tamburata con struttura a nido d'ape, rivestita in medium "
     "density laccato, dimensioni standard (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.21.200.0010.a)", 'cad', 455.93),
    ('porte_interne', 'Porta tamburata laccata', '1C.21.200.0060.a',
     "Portoncino d'ingresso interno a battente a un'anta, tamburato, rivestito in medium density "
     "laccato, misure standard 90-100x210-220 (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, "
     "art. 1C.21.200.0060.a)", 'cad', 431.16),
    ('porte_interne', 'Porta in legno massello', '1C.21.200.0010.c',
     "Porta interna a battente a un'anta, tamburata con struttura a nido d'ape, rivestita in rovere "
     "lucidato, dimensioni standard (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.21.200.0010.c)", 'cad', 730.07),
    ('porte_interne', 'Porta rasomuro (a filo muro, a scomparsa)', '1C.21.250.0010.a + 1C.21.250.0050.a',
     "Kit porta scorrevole a scomparsa: telaio in lamiera zincata da murare (1C.21.250.0010.a, € "
     "349,17, luce 70x200-210) + anta scorrevole tamburata rifinita (1C.21.250.0050.a, € 523,84) — il "
     "Prezzario regionale non censisce una voce 'rasomuro a filo muro' in senso stretto: usata come "
     "riferimento più vicino la porta scorrevole a scomparsa completa (somma di due voci ufficiali, "
     "vol. 1.1)", 'cad', 873.01),
    ('porte_interne', 'Altro (specificare a parte)', 'RIF-POR-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): sostituire con la "
     "porta realmente prevista dal capitolato", 'cad', 622.54),
    ('impianto_elettrico', 'Standard (normativa base)', 'PLC-ELE-01',
     "Punto impianto elettrico standard per vano (normativa base) — voce non utilizzata nel calcolo "
     "attuale del computo (gli impianti sono computati con un'unica voce a corpo, categoria "
     "'impianti_a_corpo'), mantenuta per compatibilità del capitolato", 'cad', 450.0),
    ('impianto_elettrico', 'Predisposizione domotica', 'PLC-ELE-02',
     "Punto impianto elettrico con predisposizione domotica per vano — voce non utilizzata nel "
     "calcolo attuale del computo, mantenuta per compatibilità del capitolato", 'cad', 650.0),
    ('impianto_elettrico', 'Domotica completa', 'PLC-ELE-03',
     "Punto impianto elettrico con domotica completa per vano — voce non utilizzata nel calcolo "
     "attuale del computo, mantenuta per compatibilità del capitolato", 'cad', 1200.0),
    ('impianto_elettrico', 'Altro (specificare a parte)', 'PLC-ELE-99',
     "Impianto elettrico — tipologia da definire — voce non utilizzata nel calcolo attuale del "
     "computo", 'cad', 500.0),
    ('impianto_idrico', 'Sanitari e rubinetteria standard', 'PLC-IDR-01',
     "Sanitari e rubinetteria standard per vano — voce non utilizzata nel calcolo attuale del "
     "computo, mantenuta per compatibilità del capitolato", 'cad', 600.0),
    ('impianto_idrico', 'Fascia media', 'PLC-IDR-02',
     "Sanitari e rubinetteria fascia media per vano — voce non utilizzata nel calcolo attuale del "
     "computo", 'cad', 900.0),
    ('impianto_idrico', 'Fascia alta', 'PLC-IDR-03',
     "Sanitari e rubinetteria fascia alta per vano — voce non utilizzata nel calcolo attuale del "
     "computo", 'cad', 1500.0),
    ('impianto_idrico', 'Altro (specificare a parte)', 'PLC-IDR-99',
     "Impianto idrico — tipologia da definire — voce non utilizzata nel calcolo attuale del computo", 'cad', 700.0),
    ('scavi', 'standard', '1C.02.100.0040.a',
     "Scavo a sezione obbligata a pareti verticali, eseguito a macchina fino a 3,00 m di profondità, "
     "con carico e deposito delle terre nell'ambito del cantiere (fonte: Prezzario Regione Lombardia "
     "2022, vol. 1.1, art. 1C.02.100.0040.a)", 'm3', 10.51),
    ('scavi', 'piscina', '1C.02.100.0050.a',
     "Scavo a sezione obbligata a pareti verticali, eseguito a macchina per profondità superiore a "
     "3,00 m, con carico e deposito delle terre nell'ambito del cantiere (fonte: Prezzario Regione "
     "Lombardia 2022, vol. 1.1, art. 1C.02.100.0050.a)", 'm3', 12.6),
    ('strutture_cls', 'standard', '1C.04.020.0040.a',
     "Strutture (pilastri, travi, correnti, solette, murature di vani scala/ascensore) realizzate con "
     "getto di calcestruzzo preconfezionato a prestazione garantita, classe C25/30-XC1/XC2, esclusi "
     "ferro e casseri (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.04.020.0040.a)", 'm3', 178.97),
    ('strutture_cls', 'casseforme', '1C.04.400.0020.c',
     "Casseforme per getti in calcestruzzo con tavole di abete, per strutture in c.a., muri scala ed "
     "ascensore di qualsiasi spessore, solette piene (fonte: Prezzario Regione Lombardia 2022, vol. "
     "1.1, art. 1C.04.400.0020.c)", 'm2', 45.88),
    ('strutture_ferro', 'standard', '1C.04.450.0010.a',
     "Acciaio tondo in barre nervate B450C per cemento armato, rispondente ai CAM, in opera compresa "
     "lavorazione, posa, sormonti, sfrido, legature (fonte: Prezzario Regione Lombardia 2022, vol. "
     "1.1, art. 1C.04.450.0010.a)", 'kg', 1.79),
    ('spinottature', 'standard', 'RIF-SPI-01',
     "Ripresa dei getti e spinottature per il collegamento tra elementi strutturali gettati in tempi "
     "diversi — voce non censita puntualmente nel Prezzario 2022 come articolo a sé: quantità e "
     "prezzo dipendono dal progetto strutturale esecutivo, da misurare e valorizzare a mano", 'n.', 0.0),
    ('strutture_muratura', 'standard', '1C.06.050.0010.a',
     "Muratura portante in fondazione o elevazione di mattoni pieni, malta tradizionale "
     "(conducibilità termica 0,55 W/mK), secondo NTC 2018 (fonte: Prezzario Regione Lombardia 2022, "
     "vol. 1.1, art. 1C.06.050.0010.a)", 'm3', 375.54),
    ('copertura', 'Tetto a falde, manto in laterizio', '1C.11.030.0010.b',
     "Copertura completa di orditura in legno (grossa e piccola orditura su capriate) e manto in "
     "tegole a canale (coppi) (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.11.030.0010.b)", 'm2', 108.55),
    ('copertura', 'Tetto a falde, manto in cemento', '1C.11.030.0010.c',
     "Copertura completa di orditura in legno (grossa e piccola orditura su capriate) e manto in "
     "lastre cementizie fibrorinforzate ondulate, spessore 7 mm (fonte: Prezzario Regione Lombardia "
     "2022, vol. 1.1, art. 1C.11.030.0010.c)", 'm2', 81.58),
    ('copertura', 'Copertura piana con guaina bituminosa', '1C.13.160.0020',
     "Manto impermeabile bituminoso per coperture pedonabili, membrana elastoplastomerica 4 mm, "
     "biarmata, resistente ai raggi UV, saldata a fiamma — non include la struttura portante (solaio "
     "piano, già computato separatamente) (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.13.160.0020)", 'm2', 25.64),
    ('copertura', 'Copertura metallica', '1C.11.140.0010.d',
     "Copertura di tetto con lastre in lamiera grecata di acciaio zincato, spessore 6/10 mm, colore "
     "naturale — non include l'orditura portante metallica, da computare separatamente se non già "
     "prevista (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.11.140.0010.d)", 'm2', 23.14),
    ('copertura', 'Altro (specificare a parte)', 'RIF-COP-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): sostituire con la "
     "copertura realmente prevista dal capitolato", 'm2', 59.73),
    ('demolizioni', 'pavimento', '1C.01.100.0010.a',
     "Demolizione di pavimenti interni in piastrelle di cemento, ceramica o cotto con relativa malta "
     "di allettamento, incluso carico e trasporto delle macerie (esclusi oneri di smaltimento) "
     "(fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.01.100.0010.a)", 'm2', 9.79),
    ('demolizioni', 'intonaco', '1C.01.090.0020.a',
     "Scrostamento di intonaco interno o esterno, di qualsiasi tipo, in buono stato di conservazione, "
     "incluso carico e trasporto delle macerie (esclusi oneri di smaltimento) (fonte: Prezzario "
     "Regione Lombardia 2022, vol. 1.1, art. 1C.01.090.0020.a)", 'm2', 12.64),
    ('fondazioni', 'magrone', '1C.04.020.0010.a',
     "Sottofondazioni realizzate con getto di calcestruzzo preconfezionato a prestazione garantita, "
     "classe C16/20 (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.04.020.0010.a)", 'm3', 132.36),
    ('fondazioni', 'standard', '1C.04.020.0020.a',
     "Fondazioni (plinti, travi rovesce, platee) realizzate con getto di calcestruzzo preconfezionato "
     "a prestazione garantita, classe C25/30-XC1/XC2, esclusi ferro e casseri (fonte: Prezzario "
     "Regione Lombardia 2022, vol. 1.1, art. 1C.04.020.0020.a)", 'm3', 154.47),
    ('fondazioni', 'casseforme', '1C.04.400.0010.a',
     "Casseforme per getti in calcestruzzo con pannelli di legno lamellare, per fondazioni, plinti, "
     "travi rovesce, platee (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.04.400.0010.a)", 'm2', 17.58),
    ('fondazioni', 'acciaio', '1C.04.450.0010.a',
     "Acciaio tondo in barre nervate B450C per cemento armato, in opera (fonte: Prezzario Regione "
     "Lombardia 2022, vol. 1.1, art. 1C.04.450.0010.a)", 'kg', 1.79),
    ('cantiere', 'approntamento', 'RIF-CNT-01',
     "Approntamento e allestimento del cantiere edile (recinzione, baraccamenti, impianti provvisori "
     "di cantiere) — il Prezzario Regione Lombardia 2022 tratta i costi di cantierizzazione in modo "
     "analitico nel capitolo 1S (Costi della sicurezza) anziché con una voce unica a corpo: il prezzo "
     "qui riportato viene comunque sempre sostituito dal parametro utente 'Costo di approntamento del "
     "cantiere'", 'corpo', 1.0),
    ('cantiere', 'bagno_chimico', 'RIF-CNT-02',
     "Nolo di bagno chimico da cantiere per l'intera durata dei lavori — non censito come voce unica "
     "a corpo nel Prezzario 2022; il prezzo qui riportato viene comunque sempre sostituito dal "
     "parametro utente 'Costo del nolo bagno chimico'", 'corpo', 1.0),
    ('cantiere', 'gru', 'RIF-CNT-03',
     "Nolo di gru da cantiere per l'intera durata dei lavori — non censito come voce unica a corpo "
     "nel Prezzario 2022; il prezzo qui riportato viene comunque sempre sostituito dal parametro "
     "utente 'Costo del nolo gru'", 'corpo', 1.0),
    ('assistenza_muraria', 'serramenti', 'RIF-ASM-SER-01',
     "Assistenza muraria per la posa dei serramenti esterni — nel Prezzario Regione Lombardia 2022 "
     "questa assistenza è normalmente GIA' INCLUSA nel prezzo di fornitura e posa dei serramenti "
     "stessi (vedi voci della categoria 'serramenti_esterni'): usa questa riga separata solo se nel "
     "tuo capitolato la posa è scorporata dalla fornitura", 'm2', 25.0),
    ('assistenza_muraria', 'porte', 'RIF-ASM-POR-01',
     "Assistenza muraria per la posa delle porte interne — nel Prezzario Regione Lombardia 2022 "
     "questa assistenza è normalmente GIA' INCLUSA nel prezzo di fornitura e posa delle porte stesse "
     "(vedi voci della categoria 'porte_interne'): usa questa riga separata solo se nel tuo "
     "capitolato la posa è scorporata dalla fornitura", 'cad', 45.0),
    ('assistenza_muraria', 'elettrico', '1C.28.200.0010.a',
     "Assistenza muraria per l'esecuzione dell'impianto elettrico (nuove costruzioni), in percentuale "
     "sul costo dell'impianto — il prezzo qui riportato viene comunque sempre sostituito dal "
     "parametro utente 'Incidenza assistenza muraria elettrico' (fonte: Prezzario Regione Lombardia "
     "2022, vol. 1.1, art. 1C.28.200.0010.a)", '%', 15.0),
    ('assistenza_muraria', 'idraulico', '1C.28.100.0010.a',
     "Assistenza muraria per l'esecuzione degli impianti meccanici (nuove costruzioni), in "
     "percentuale sul costo dell'impianto — il prezzo qui riportato viene comunque sempre sostituito "
     "dal parametro utente 'Incidenza assistenza muraria idraulico' (fonte: Prezzario Regione "
     "Lombardia 2022, vol. 1.1, art. 1C.28.100.0010.a)", '%', 15.0),
    ('solai', 'standard', '1C.05.050.0010.d',
     "Solaio piano in cemento armato e blocchi in laterizio a nervature parallele, gettato in opera, "
     "altezza totale 25 cm (20 laterizio + 5 soletta), escluso il ferro tondo di armatura (fonte: "
     "Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.05.050.0010.d)", 'm2', 66.09),
    ('solai', 'casseforme', '1C.04.400.0010.c',
     "Casseforme per getti in calcestruzzo con pannelli di legno lamellare, orizzontali per solette "
     "piene (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.04.400.0010.c)", 'm2', 22.86),
    ('solai', 'calcestruzzo', '1C.04.020.0040.a',
     "Getto di calcestruzzo preconfezionato a prestazione garantita per solette, classe "
     "C25/30-XC1/XC2, esclusi ferro e casseri (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, "
     "art. 1C.04.020.0040.a)", 'm3', 178.97),
    ('solai', 'acciaio', '1C.04.450.0010.a',
     "Acciaio tondo in barre nervate B450C per cemento armato, in opera (fonte: Prezzario Regione "
     "Lombardia 2022, vol. 1.1, art. 1C.04.450.0010.a)", 'kg', 1.79),
    ('vespaio', 'standard', '1C.05.500.0020.b',
     "Vespaio aerato con elementi in plastica a perdere, altezza 25-30 cm, sottofondo in calcestruzzo "
     "C16/20 e soletta superiore C25/30 (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.05.500.0020.b)", 'm2', 37.19),
    ('contropareti', 'standard', '1C.06.550.0050',
     "Controparete in lastre di gesso rivestito a bordi assottigliati, spessore 13 mm, applicata "
     "direttamente alla parete con incollaggio in gesso (fonte: Prezzario Regione Lombardia 2022, "
     "vol. 1.1, art. 1C.06.550.0050)", 'm2', 22.53),
    ('pareti_divisorie', 'Muratura in laterizio forato', '1C.06.070.0100.b',
     "Tavolati in mattoni forati 8x12x24 cm, con malta cementizia o bastarda, spessore 12 cm (fonte: "
     "Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.06.070.0100.b)", 'm2', 30.61),
    ('pareti_divisorie', 'Cartongesso su orditura metallica', '1C.06.560.0050.a',
     "Parete in lastre di gesso rivestito a bordi assottigliati sulle due facce, orditura in "
     "profilati di acciaio zincato, montanti a interasse 60 cm, una lastra da 13 mm per faccia "
     "(fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.06.560.0050.a)", 'm2', 34.11),
    ('pareti_divisorie', 'Altro (specificare a parte)', 'RIF-PDV-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): sostituire con la "
     "parete realmente prevista dal capitolato", 'm2', 32.36),
    ('velette', 'standard', '1C.20.050.0040.a',
     "Velette e incassettature con lastre lisce in gesso rasate, spessore 15 mm — quantità e sviluppo "
     "lineare non desumibili dalla sola pianta: misura e valorizza a mano (fonte: Prezzario Regione "
     "Lombardia 2022, vol. 1.1, art. 1C.20.050.0040.a)", 'm2', 37.18),
    ('controsoffitti', 'standard', '1C.20.050.0010.a',
     "Controsoffitto in pannelli di gesso 600x600x22 mm, orditura a vista, superficie liscia (fonte: "
     "Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.20.050.0010.a)", 'm2', 33.02),
    ('acustica', 'materiale_generico', 'RIF-ACU-01',
     "Materiale/lavorazione per requisiti acustici individuato nella relazione acustica caricata — "
     "voce generica non censita puntualmente nel Prezzario 2022 (il materiale specifico varia caso "
     "per caso): misura e valorizza a mano in base al prodotto indicato nella relazione", 'corpo', 0.0),
    ('cappotto_termico', 'EPS/polistirene', '1C.10.300.0020 (80mm+4x10mm)',
     "Sistema per isolamento termico a cappotto in polistirene espanso sinterizzato, spessore 120 mm "
     "(80 mm base € 65,09/m² + 4x10mm extra a € 1,21/m²), rasatura armata in fibra di vetro, finitura "
     "esclusa (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.10.300.0020)", 'm2', 69.93),
    ('cappotto_termico', 'Lana di roccia', '1C.10.300.0030 (60mm+6x10mm)',
     "Sistema per isolamento termico a cappotto in pannelli rigidi di lana di roccia, spessore 120 mm "
     "(60 mm base € 54,36/m² + 6x10mm extra a € 1,66/m²), rasatura armata in fibra di vetro, finitura "
     "esclusa (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.10.300.0030)", 'm2', 64.32),
    ('cappotto_termico', 'Fibra di legno', '1C.10.300.0040 (60mm+6x10mm, adattata)',
     "Il Prezzario Regione Lombardia 2022 non censisce una voce a cappotto in fibra di legno: usato "
     "come riferimento più simile il sistema a cappotto in pannelli di lana di vetro ad alta densità, "
     "spessore 120 mm (60 mm base € 55,21/m² + 6x10mm extra a € 1,86/m²) — il costo reale della fibra "
     "di legno è tipicamente superiore, verifica e correggi (fonte: Prezzario Regione Lombardia 2022, "
     "vol. 1.1, art. 1C.10.300.0040)", 'm2', 66.37),
    ('cappotto_termico', 'Altro (specificare a parte)', 'RIF-CAP-99',
     "Riferimento generico (media indicativa delle voci ufficiali sopra elencate): sostituire con il "
     "materiale realmente previsto dal capitolato", 'm2', 66.87),
    ('impermeabilizzazioni', 'standard', '1C.13.160.0010',
     "Barriera al vapore per sistemi impermeabili posati a freddo con adesivo bituminoso, membrana "
     "2,5 mm, applicata a fiamma (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. "
     "1C.13.160.0010)", 'm2', 11.78),
    ('impermeabilizzazioni', 'piscina', '1C.13.160.0020',
     "Manto impermeabile bituminoso per coperture/vasche pedonabili, membrana elastoplastomerica 4 "
     "mm, biarmata, resistente ai raggi UV, saldata a fiamma (fonte: Prezzario Regione Lombardia "
     "2022, vol. 1.1, art. 1C.13.160.0020)", 'm2', 25.64),
    ('piscina_vasca', 'standard', '1C.04.030.0020.a (sp. 20cm) + 1U.07.150.0010.a',
     "Vasca strutturale: calcestruzzo armato autocompattante SCC C25/30 per murature armate "
     "entro/fuori terra (1C.04.030.0020.a, € 182,28/m³, ipotesi spessore parete/fondo 20 cm = € "
     "36,46/m²) + rivestimento interno vasca (fondo e pareti) in piastrelle di gres ceramico "
     "(1U.07.150.0010.a, € 43,37/m²) — somma di due voci ufficiali del Prezzario Regione Lombardia "
     "2022; lo spessore di 20 cm è un'ipotesi corrente per vasche residenziali, da verificare col "
     "progetto strutturale", 'm2', 79.83),
    ('piscina_bordo', 'standard', '1C.18.300.0010.a',
     "Bordo perimetrale piscina in pavimento di piastrelle di granito Bianco Sardo, lastre calibrate "
     "e lucidate, formato piccolo (0,05-0,12 m², spessore 10 mm) (fonte: Prezzario Regione Lombardia "
     "2022, vol. 1.1, art. 1C.18.300.0010.a)", 'm2', 64.38),
    ('scala_esterna', 'standard', 'RIF-SCE-01',
     "Scala esterna — individuata come possibile presenza in pianta ma non quotata in modo misurabile "
     "automaticamente: non censita come voce unica nel Prezzario 2022 (dipende da materiale, numero "
     "gradini, rivestimento); misura e valorizza a mano", 'corpo', 0.0),
    ('scale_interne', 'standard', 'RIF_SCI-01',
     "Scale interne — collegano i piani dell'edificio, non quotate in modo misurabile automaticamente "
     "dalla sola pianta caricata; non censite come voce unica nel Prezzario 2022 (dipende da "
     "materiale, numero gradini, rivestimento); misura e valorizza a mano", 'corpo', 0.0),
    ('opere_esterne', 'recinzione', '1C.22.450.0010.a',
     "Recinzione in rete elettrosaldata zincata e plasticata, pali e saette in profilati a T 30x30x4 "
     "mm — non rappresentata nella pianta di progetto: misura lo sviluppo reale dalla planimetria "
     "generale (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.22.450.0010.a)", 'm2', 17.36),
    ('opere_esterne', 'smaltimento_acque', 'RIF-OES-SMA-01',
     "Reti di smaltimento acque bianche/nere e cavidotti elettrici esterni — non rappresentate nella "
     "pianta di progetto: dipendono dalla planimetria generale e dalla rete sottoservizi, valorizza a "
     "mano", 'corpo', 0.0),
    ('opere_esterne', 'pavimentazioni_esterne', 'RIF-OES-PAV-01',
     "Pavimentazioni esterne (vialetti, terrazze a terra) — non quantificabili in modo affidabile "
     "dalla sola pianta architettonica: misura e valorizza a mano", 'm2', 0.0),
    ('opere_esterne', 'camerette_ispezione', 'RIF-OES-CAM-01',
     "Camerette di ispezione per reti sottoservizi — non rappresentate nella pianta di progetto: "
     "conta e valorizza a mano dalla planimetria generale/rete sottoservizi", 'n.', 0.0),
    ('opere_esterne', 'pozzo_perdente', 'RIF-OES-POZ-01',
     "Pozzo perdente per smaltimento acque meteoriche/reflue nel sottosuolo — presenza e numero "
     "dipendono dalla rete sottoservizi e dalla planimetria generale: verifica e valorizza a mano", 'n.', 0.0),
    ('lattonerie', 'standard', '1C.14.050.0010.a',
     "Canali di gronda, pluviali, converse e scossaline in lamiera zincata spessore 0,6 mm, lavorati "
     "con sagome e sviluppi normali — lo sviluppo lineare reale non è desumibile dalla sola "
     "superficie di copertura: misura e valorizza a mano da prospetti/sezioni quotate (fonte: "
     "Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.14.050.0010.a)", 'kg', 9.28),
    ('soglie_davanzali', 'standard', '1C.15.310.0020.a',
     "Davanzali e soglie in cemento decorativo gettato fuori opera, superficie a vista raschiata, "
     "sezione fino a 100 cm² — quali aperture li richiedono non è deducibile in automatico: verifica "
     "e valorizza a mano (fonte: Prezzario Regione Lombardia 2022, vol. 1.1, art. 1C.15.310.0020.a)", 'ml', 49.81),
    ('rivestimento_facciata', 'standard', '1C.06.100.0050.a (adattata)',
     "Rivestimento/muratura faccia a vista con mattoni pieni tipo 'a mano', spessore 12 cm — usato "
     "come riferimento più vicino per un rivestimento di facciata in laterizio/klinker a vista; il "
     "materiale specifico (pietra naturale o ricostruita, klinker, doghe) individuato nel render va "
     "sempre confermato e il prezzo corretto di conseguenza (fonte: Prezzario Regione Lombardia 2022, "
     "vol. 1.1, art. 1C.06.100.0050.a)", 'm²', 68.42),
    ('impianti_a_corpo', 'standard', 'RIF-IMP-CORPO-01',
     "Impianti (elettrico, idrico-sanitario, termico/climatizzazione), stima a corpo come percentuale "
     "indicativa del resto del computo — il Prezzario Regione Lombardia 2022 non prevede un'unica "
     "voce a corpo per 'tutti gli impianti' (li tratta analiticamente nei capitoli 1E e 1M): il "
     "prezzo qui riportato viene comunque sempre sostituito dal calcolo percentuale sul subtotale "
     "delle altre lavorazioni", 'a corpo', 0.0),
]

# Impronta del contenuto di PLACEHOLDER_VOCI: il database dei prezzari vive su un
# volume persistente (non viene ricreato ad ogni deploy), quindi senza questo
# controllo una modifica a questa lista non raggiungerebbe mai un'istanza già
# avviata in precedenza (vedi db.ensure_placeholder_seed). Cambia automaticamente
# ad ogni modifica della lista qui sopra: non va aggiornata a mano.
import hashlib as _hashlib
PLACEHOLDER_SEED_VERSION = _hashlib.sha256(repr(PLACEHOLDER_VOCI).encode("utf-8")).hexdigest()[:16]

# Vocabolario di riferimento delle coppie (categoria, sotto_tipo) che il motore di
# calcolo (prezzario/matching.py) sa effettivamente cercare: usato per avvisare
# l'utente al momento del caricamento di un prezzario reale (CSV) se le sue righe
# non useranno MAI nessuna voce (perché categoria/sotto_tipo sono valori interni
# fissi, non nomi liberi — non basta che le colonne del CSV si chiamino giusto,
# devono combaciare anche i VALORI). Non è un elenco esaustivo assoluto (alcuni
# sotto_tipo derivano dalle risposte al capitolato e in teoria potrebbero essere
# personalizzati), ma copre tutte le combinazioni realmente previste da questa
# versione del sistema, quindi un CSV reale dovrebbe avvicinarsi a questo insieme.
REFERENCE_CATEGORIA_SOTTOTIPO = {(cat, sotto) for cat, sotto, *_ in PLACEHOLDER_VOCI}

# Le due uniche voci che il sistema tenta di aggiungere SEMPRE, indipendentemente
# da qualunque dato geometrico (vedi il commento in matching.py/build_computo):
# se un prezzario non le contiene ED è anche privo di corrispondenze per tutto il
# resto, il computo risulta interamente vuoto.
VOCI_SEMPRE_TENTATE = {("cantiere", "approntamento"), ("cantiere", "bagno_chimico")}
