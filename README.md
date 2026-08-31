# Computo Metrico Automatico — Sito web (prototipo)

Sito web funzionante (un unico servizio: backend FastAPI + frontend, pronto per la messa online) che copre la pipeline completa: intake (nuova costruzione o ristrutturazione) → caricamento elaborati (pianta quotata, pianta strutturale, copertura, ed eventualmente stato di fatto) → rilievo quantità → domande sulle finiture/struttura mancanti → parametri dimensionali → abbinamento a un prezzario → generazione del computo (Excel completo, elenco prezzi per import manuale in PriMus, relazione Word in prosa).

**Perché sito e non app nativa**: l'obiettivo dichiarato è un prodotto in abbonamento — un sito raggiungibile da browser, senza installazione, è la forma naturale per questo modello (è anche come lavora la maggior parte del software professionale AEC italiano che offre un piano cloud). Un'app nativa (Windows/Mac) richiederebbe firma del codice, distribuzione e aggiornamenti separati per piattaforma: complessità non giustificata prima che il motore di calcolo sia validato su progetti reali. Per questo frontend e backend sono stati uniti in un solo servizio distribuibile (vedi sotto).

## Cosa fa oggi

- **Chiede subito il tipo di intervento** (nuova costruzione o ristrutturazione) e mostra la checklist dei documenti richiesti di conseguenza: pianta quotata, prospetti e sezioni architettoniche, piante e sezioni strutturali sono **obbligatori** per una nuova costruzione; per una ristrutturazione sono obbligatorie sia la pianta dello stato di fatto sia quella di progetto.
- **Valida ogni PDF caricato** (progetto, stato di fatto, strutturale, copertura): deve essere vettoriale, dichiarare una scala metrica ed essere quotato. Se manca un requisito, il caricamento è **rifiutato con un messaggio esplicito**.
- **Rileva vani, sedime dell'edificio e copertura** dalla pianta quotata: superficie e perimetro di ogni vano, poligono di inviluppo dell'edificio (per gli scavi), superficie di copertura (da un file di copertura dedicato, se caricato, altrimenti approssimata dal sedime).
- **Non usa più lo spessore delle linee per riconoscere i muri.** Come giustamente osservato, è un criterio fragile perché il peso penna è una convenzione grafica soggettiva, non semantica, e cambia da studio a studio. Il riconoscimento dei vani ora è topologico: per ogni etichetta di vano si cerca il poligono chiuso più piccolo che la contiene, con una superficie plausibile per un ambiente — un criterio che si generalizza meglio a stili di disegno diversi.
- **Riconosce elementi puntuali taggati con sigla + abaco**: porte/finestre sulla pianta di progetto (es. "P1", "F2") e pilastri/travi sulla pianta strutturale (es. "PL1", "TR1"), con le dimensioni lette da un abaco su pagina dedicata.
- **Calcola anche scavi, strutture in elevazione e copertura**: volume di scavo dal sedime x profondità indicata; calcestruzzo e acciaio (a incidenza parametrica) per pilastri/travi in c.a., oppure volume di muratura portante se la struttura verticale scelta è in muratura; superficie di copertura corretta per l'angolo di falda.
- **Per le ristrutturazioni, confronta stato di fatto e stato di progetto**: i vani presenti solo nello stato di fatto sono trattati come demoliti e generano le relative voci; i vani con superficie cambiata sono segnalati per una verifica puntuale (non generano automaticamente una quantità, per non rischiare una stima arbitraria).
- **Fa domande solo dove serve**: se non alleghi un capitolato, chiede materiali, finiture e tipo di struttura/copertura per categoria; se alleghi un testo di capitolato, salta le categorie già coperte da parole chiave nel testo. I parametri puramente dimensionali (altezza di interpiano, profondità di scavo, incidenza acciaio, ecc.), non deducibili in modo affidabile dai soli elaborati in questa versione, sono proposti con un valore tipico che l'utente conferma o modifica.
- **Usa un prezzario di default se non ne carichi uno** (un prezzario "Lombardia" di esempio/placeholder, con prezzi plausibili ma non ufficiali) e permette di caricarne uno reale via CSV, salvato nel database per i progetti successivi.
- **Genera tre file**: il computo in Excel in stile PriMus, un secondo file Excel pensato per l'importazione manuale sicura in PriMus, e una relazione Word in prosa con le stesse convenzioni del caso Colombo.

## Sul formato "PriMus" (perché non un file nativo)

Ho verificato i formati usati da PriMus prima di costruire l'export, per non promettere una compatibilità che non esiste davvero. I formati di interscambio di PriMus (XPWE, DCF, PWE) sono **formati proprietari ACCA senza schema pubblicato**; inoltre la funzione di importazione Excel di PriMus accetta solo file **prima esportati da PriMus stesso** — non un foglio Excel arbitrario, per quanto ben strutturato (confermato dalla documentazione e dal forum ufficiale ACCA). Generare un finto file "formato PriMus" avrebbe due rischi concreti: che PriMus lo rifiuti, oppure — peggio — che lo importi in modo silenziosamente sbagliato, il che sarebbe inaccettabile per un documento con valore economico.

Ho quindi scelto la strada sicura: un secondo file Excel (`elenco_prezzi_per_primus.xlsx`) strutturato per il flusso manuale documentato da ACCA — un foglio "Elenco Prezzi" da incollare nell'editor Elenco Prezzi di PriMus, un foglio "Misurazioni" con le quantità già calcolate da inserire nelle righe di misura, e un foglio "Istruzioni" col procedimento passo passo. Non è un click unico, ma è affidabile: nessun dato viene silenziosamente alterato. Se in futuro volessi investigare un'integrazione più diretta, servirebbe la documentazione tecnica del formato DCF/XPWE, che ACCA fornisce solo tramite accordi di sviluppo — è un'opzione da valutare più avanti, non necessaria per validare l'approccio.

## Ambito attuale e limiti onesti

Il rilievo geometrico è stato validato sul formato di disegno con cui è stato costruito e testato (poligoni chiusi con etichette di testo per vani/copertura, sigle + abaco per elementi puntuali). Un disegno CAD reale con convenzioni diverse (blocchi complessi, hatch, layer con nomi non standard) richiederà probabilmente una calibrazione — è il motivo per cui il passo successivo più utile resta provarlo su alcuni progetti reali dello studio.

Le strutture in elevazione sono calcolate come **stima parametrica preliminare**: la lunghezza delle travi e l'incidenza dell'acciaio sono valori tipici confermati dall'utente, non misurati da un disegno esecutivo armato; le casserature non sono comprese. Il sedime dell'edificio (usato per gli scavi) è approssimato con l'inviluppo convesso dei vani rilevati, il che sovrastima l'area per edifici con pianta molto articolata. Per le ristrutturazioni, solo i vani interamente demoliti generano automaticamente una riga di demolizione: i vani con superficie variata sono segnalati ma non quantificati, per non introdurre una stima arbitraria. Prospetti e sezioni architettoniche sono richiesti come parte della documentazione obbligatoria e possono essere validati per conformità, ma in questa versione non vengono ancora letti automaticamente: i valori che ne deriverebbero (altezze, profondità di scavo) restano parametri confermati dall'utente — un'estensione naturale per una prossima iterazione. Il prezzario precaricato è inventato a scopo dimostrativo e non ha valore ufficiale.

## Architettura

```
backend/
  intake.py              tipo di intervento + checklist documenti obbligatori
  parametri_engine.py    parametri dimensionali con default (altezze, profondità scavo, ecc.)
  pdf_validation.py      validazione scala/quote/vettorialità
  geometry_engine.py     estrazione vani (per contenimento, non per spessore linea), sedime,
                          elementi taggati con sigla+abaco (porte/finestre, pilastri/travi)
  capitolato_engine.py   domande su materiali/finiture/struttura/copertura mancanti
  confronto_engine.py    confronto stato di fatto / stato di progetto (ristrutturazioni)
  prezzario/
    db.py                 database SQLite dei prezzari (seed + caricati dall'utente)
    seed_data.py           prezzario di esempio placeholder (finiture, scavi, strutture, copertura, demolizioni)
    matching.py             abbina quantità + risposte + parametri alle voci di prezzo
  output/
    excel_generator.py     computo in Excel stile PriMus + export "Elenco Prezzi/Misurazioni" per PriMus
    word_generator.py      relazione in Word (python-docx), incluso il confronto stato di fatto/progetto
  pipeline.py              orchestrazione end-to-end
  main.py                  API FastAPI
frontend/
  index.html               interfaccia minimale (intake, upload multipli, domande, parametri, download)
tests/
  generate_sample_plan.py  genera pianta di progetto, stato di fatto, pianta strutturale, copertura
  test_pipeline.py         verifica quantità, strutture, confronto stati, doppio export, rifiuto PDF non conforme
```

## Avvio in locale (senza Docker)

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Poi apri `http://localhost:8000` nel browser: sito e API sono sullo stesso indirizzo, non serve aprire il file HTML separatamente.

Per rigenerare gli elaborati di prova ed eseguire i test:

```bash
python tests/generate_sample_plan.py
python tests/test_pipeline.py
```

## Come mettere online il sito

Il progetto è pensato per girare come un singolo container Docker, così può essere distribuito su qualunque host senza configurazione aggiuntiva.

**In locale con Docker** (utile anche solo per provarlo esattamente come girerebbe online):

```bash
docker compose up --build
```

Il sito sarà su `http://localhost:8000`. I dati (database dei prezzari, file caricati e generati) sono salvati nel volume Docker `computo-data`, quindi sopravvivono ai riavvii del container — senza questo volume, ogni riavvio azzererebbe i prezzari caricati.

**Per metterlo online davvero**, servono un host che esegua container Docker e un disco persistente collegato alla cartella `/data` (variabile d'ambiente `COMPUTO_DATA_DIR`, già impostata nel Dockerfile). Opzioni concrete, dalla più semplice:

- **Render.com**: collega direttamente un repository GitHub con un Dockerfile e offre un piano gratuito per un primo test, senza richiedere obbligatoriamente una carta di credito per registrarsi. Il limite del piano gratuito: il servizio "si addormenta" dopo 15 minuti senza richieste e impiega circa un minuto a ripartire alla richiesta successiva (irrilevante per un uso occasionale di test, non adatto a un servizio sempre pronto); il supporto ai dischi persistenti sul piano gratuito non è garantito, quindi il database dei prezzari caricati potrebbe azzerarsi ai riavvii finché non si passa a un piano a pagamento.
- **Railway.app**: offre un volume persistente anche nel piano gratuito (0,5 GB, sufficiente per iniziare), ma dal 2026 richiede comunque l'aggiunta di un metodo di pagamento anche per il piano gratuito/trial. È la scelta migliore se per il test vuoi che i prezzari caricati non si perdano tra un riavvio e l'altro.
- **Un VPS** (es. Hetzner, DigitalOcean): più controllo e costo prevedibile, ma richiede occuparsi di aggiornamenti, backup del volume e di un reverse proxy (es. Caddy o Nginx) per HTTPS con un dominio proprio — opzione da valutare solo per un lancio più stabile, non per un primo test.

Nessuna di queste opzioni comprende ancora account utente: oggi il sito è utilizzabile da chiunque abbia l'indirizzo, senza login. Va bene per una fase di test interno o con pochi clienti selezionati (basta non pubblicizzare l'indirizzo), ma prima di vendere abbonamenti pubblicamente serve aggiungere autenticazione e separazione dei dati tra utenti — coerente con quanto già indicato come passo successivo, da fare dopo aver validato il motore di calcolo su progetti reali.

### Guida rapida: pubblicarlo su Render in circa 10 minuti (nessun comando da digitare)

1. Se non hai già un account GitHub, creane uno gratuito su github.com.
2. Su github.com, crea un nuovo repository (pulsante verde "New"), lascialo pubblico o privato indifferentemente, senza aggiungere file di esempio.
3. Estrai lo zip di questo progetto sul tuo computer, poi nella pagina del repository appena creato usa "uploading an existing file" e trascina dentro tutto il contenuto della cartella estratta (file e sottocartelle inclusi) — GitHub li carica senza bisogno di installare git. Conferma il commit.
4. Vai su render.com, registrati (puoi usare l'account GitHub appena creato per accedere in un clic).
5. Nella dashboard di Render scegli "New +" → "Web Service", collega il repository GitHub appena caricato.
6. Render rileva automaticamente il Dockerfile nel repository: lascia le impostazioni proposte, scegli il piano "Free" e conferma.
7. **Prima di confermare**, apri la sezione "Environment" e aggiungi due variabili d'ambiente: `BASIC_AUTH_USER` (es. `francope`) e `BASIC_AUTH_PASS` (una password a tua scelta). Il sito è già predisposto per chiedere queste credenziali a ogni accesso quando sono impostate: senza questo passaggio l'indirizzo resterebbe aperto a chiunque lo trovi, con questo passaggio solo chi conosce utente e password può usarlo, pur restando un indirizzo tecnicamente pubblico.
8. Dopo un paio di minuti di build, Render assegna un indirizzo pubblico del tipo `https://computo-app-xxxx.onrender.com`: aprilo nel browser, inserisci le credenziali quando richieste, ed è il sito.

Se in un secondo momento vuoi aggiungere un disco persistente (perché il prezzario caricato non si azzeri ai riavvii), serve passare a un'istanza a pagamento e collegare un "Persistent Disk" al percorso `/data` dalle impostazioni del servizio.

### Nota sulla riservatezza dell'indirizzo

Con `BASIC_AUTH_USER`/`BASIC_AUTH_PASS` impostate, chiunque apra il link vede una richiesta di nome utente e password prima di poter usare il sito: senza le credenziali, non si può fare nulla. Non è un vero sistema ad account (nessuna distinzione tra utenti, tutti condividono la stessa password), ma è sufficiente per un test riservato a te o a poche persone di fiducia a cui comunichi la password.

## Prossimi passi ragionevoli, in ordine

1. **Provare il prototipo su 2-3 progetti reali dello studio** (piante, piante strutturali e sezioni vere) per calibrare il motore di estrazione sulle vostre convenzioni di disegno, e caricare il prezzario Lombardia reale al posto del placeholder.
2. **Lettura automatica di prospetti e sezioni** per derivare altezze di interpiano, profondità di scavo e angolo di falda invece di chiederli come parametri confermati dall'utente.
3. **Demolizioni parziali** per i vani con superficie variata tra stato di fatto e progetto, oggi solo segnalati.
4. **Aggiungere account utente e persistenza progetti**, così ogni computo generato resta associato a un cliente/incarico invece di essere solo un download.
5. **Interfaccia dedicata e fatturazione abbonamenti**, solo una volta che il motore di calcolo è stato validato su casi reali: prima la qualità del risultato, poi il prodotto attorno.
