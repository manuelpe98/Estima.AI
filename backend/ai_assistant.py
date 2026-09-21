"""Due funzioni AI, entrambe facoltative e attivate solo su azione esplicita
dell'utente (mai in automatico durante la generazione del computo):

1. interpreta_istruzione — collegata alla colonna "Commento" di UNA riga:
   l'utente scrive un'osservazione o una richiesta di modifica (es. "raddoppia
   la quantità", "il prezzo reale è 65 €/m²", "questa voce non serve,
   eliminala") e, alla conferma, il sistema la interpreta e applica la
   modifica alla riga stessa — o la elimina — invece di limitarsi a salvare
   il commento come nota statica. Usa il modello ECONOMICO (Haiku): è una
   modifica strutturata su una riga sola, compito semplice e frequente.

2. revisiona_computo — un secondo passaggio, sull'INTERO computo già
   generato: lo fa rileggere a un modello più capace (Sonnet) come farebbe
   un computista esperto che cerca errori — prezzi o quantità fuori scala,
   incongruenze tra voci, categorie mancanti — e restituisce un elenco di
   osservazioni, SENZA mai modificare nulla da solo. Compito più complesso
   ma occasionale (una volta per computo, non per riga): qui la qualità del
   modello conta più del costo per singola chiamata.

3. analizza_render — analisi visiva (Sonnet, con visione) dei render/foto
   fotorealistiche eventualmente caricati come riferimento: guarda le
   immagini e descrive materiali ed elementi visibili con impatto
   economico (rivestimenti di facciata, parapetti, infissi, pavimentazioni
   esterne, elementi particolari) che il solo questionario testuale
   potrebbe non cogliere. Come revisiona_computo, SOLO osservazione: non
   calcola quantità né prezzi, e non modifica mai il computo da sola —
   le osservazioni finiscono nelle note metodologiche come riferimento per
   l'utente. Compito occasionale (una volta per progetto): stesso modello
   capace usato per la revisione.

4. interpreta_preventivo_impresa — collegata alla funzione "Confronto
   preventivi imprese" (vedi backend/confronto_preventivi_engine.py): il
   cliente carica il preventivo ricevuto da un'impresa così com'è (PDF,
   Excel o foto/scansione, in QUALSIASI formato/struttura l'impresa lo
   abbia scritto — non un modulo predefinito), e questa funzione abbina ogni
   prezzo trovato alla voce di computo corrispondente, restituendo un
   elenco che l'utente rivede e corregge a mano PRIMA che venga generato il
   file di confronto finale (quel passaggio successivo, invece, è puro
   calcolo — zero chiamate AI). Usa il modello capace (Sonnet): abbinare un
   documento a struttura libera a decine/centinaia di voci di computo è un
   compito di comprensione, non una modifica strutturata su un dato solo.

Ottimizzazione dei costi (richiesta esplicita dell'utente, qualità sempre al
massimo per il compito):
- modello economico per il compito frequente e semplice, modello più capace
  solo per quello occasionale e complesso — non lo stesso modello ovunque;
- prompt caching sul system prompt (fisso, non cambia tra una chiamata e
  l'altra): le chiamate ravvicinate nel tempo pagano il system prompt una
  sola volta invece che ad ogni chiamata;
- input compattato all'essenziale (solo i campi che servono davvero al
  giudizio, descrizioni troncate) per ridurre i token in ingresso.

Per motivi di sicurezza e di costo, entrambe le funzioni:
- richiedono una chiave API Anthropic valida nella variabile d'ambiente
  ANTHROPIC_API_KEY sul server (Render): senza, l'endpoint risponde con un
  errore chiaro invece di fallire in modo silenzioso o inventare un risultato;
- hanno un contratto di risposta JSON rigido: il modello non può eseguire
  codice né toccare file o righe che non gli sono state passate esplicitamente,
  e revisiona_computo non può MAI modificare direttamente il computo — solo
  segnalare, mai agire.
"""
from __future__ import annotations
import base64
import io
import json
import os

# Modello per le modifiche riga-per-riga (frequente, compito semplice e
# strutturato): il più economico disponibile.
MODEL = os.environ.get("ESTIMA_AI_MODEL", "claude-haiku-4-5-20251001")
# Modello per la revisione dell'intero computo (occasionale, compito che
# richiede più ragionamento): qualità prima del costo per singola chiamata,
# ma resta comunque un'unica chiamata per computo, non per riga.
MODEL_REVISIONE = os.environ.get("ESTIMA_AI_MODEL_REVISIONE", "claude-sonnet-5")

SYSTEM_PROMPT = """Sei l'assistente di Estima.AI, un programma italiano di computo metrico \
estimativo per l'edilizia. Il tuo unico compito è applicare UNA istruzione dell'utente a UNA \
riga di computo che ti viene fornita, e restituire il risultato.

Rispondi SEMPRE E SOLO con un oggetto JSON valido, senza testo prima o dopo, con questa struttura \
esatta:
{
  "azione": "modifica" | "elimina" | "nessuna",
  "descrizione": "<descrizione della voce, nuova o invariata>",
  "unita_misura": "<unità di misura, nuova o invariata>",
  "quantita": <numero>,
  "prezzo_unitario": <numero, prezzo unitario in euro>,
  "categoria": "<categoria della voce, nuova o invariata>",
  "risposta": "<una frase breve in italiano che spiega cosa hai fatto o perché no>"
}

Regole:
- "azione":"elimina" se l'utente chiede esplicitamente di togliere/eliminare/rimuovere la riga.
- "azione":"modifica" se applichi un cambiamento a quantità, prezzo, descrizione, unità di misura \
o categoria. Calcola tu eventuali percentuali o operazioni ("raddoppia", "aumenta del 15%", \
"dimezza il prezzo", ecc.) e riporta il valore numerico finale, non la formula.
- "azione":"nessuna" se l'istruzione è solo un'osservazione/promemoria che non richiede modifiche \
ai valori, oppure se non hai abbastanza informazioni per applicarla con certezza (es. l'utente \
chiede "metti il prezzo di mercato" senza indicare un numero: non puoi inventarlo). In questo caso \
lascia quantità, prezzo, descrizione, unità di misura e categoria INVARIATI rispetto alla riga \
originale, e spiega brevemente nella risposta cosa manca o cosa hai capito.
- Non inventare mai un prezzo o una quantità che l'utente non ha fornito né che non deriva da un \
calcolo esplicito sull'istruzione data.
- Quantità e prezzo unitario non possono mai essere negativi.
- Non aggiungere MAI testo, markdown o commenti fuori dal JSON: solo l'oggetto JSON."""

SYSTEM_PROMPT_REVISIONE = """Sei un computista esperto che rilegge un computo metrico \
estimativo GIÀ GENERATO da Estima.AI (un software che lo produce automaticamente da piante \
quotate e da parametri tecnici) per un secondo controllo, come faresti rileggendo il lavoro di \
un collaboratore prima di consegnarlo. Ricevi l'elenco delle voci (categoria, descrizione, unità \
di misura, quantità, prezzo unitario, importo, provenienza del dato) e alcuni dati di base del \
progetto (tipo di intervento, superficie, numero di vani).

Il tuo compito è SEGNALARE possibili problemi, MAI correggerli tu: chi rivede il computo decide \
se e come intervenire. Cerca in particolare:
- prezzi unitari palesemente fuori scala per quel tipo di lavorazione (troppo alti o troppo bassi \
rispetto a valori di mercato plausibili in edilizia italiana);
- quantità implausibili rispetto alle dimensioni del progetto (es. una quantità enormemente più \
grande o più piccola di quanto ci si aspetterebbe dalla superficie/vani indicati);
- incongruenze tra voci che dovrebbero essere coerenti tra loro (es. superfici che non tornano tra \
voci collegate, un'unità di misura sbagliata per quel tipo di lavorazione);
- voci con importo zero che non sono segnalate come segnaposto, o viceversa;
- qualunque altra cosa che un computista esperto noterebbe leggendo l'elenco con occhio critico.

Rispondi SEMPRE E SOLO con un oggetto JSON valido, senza testo prima o dopo, con questa struttura \
esatta:
{
  "osservazioni": [
    {
      "voce_numero": <numero della voce a cui si riferisce, o null se riguarda il computo nel suo insieme>,
      "gravita": "alta" | "media" | "bassa",
      "descrizione": "<cosa hai notato, in italiano, una o due frasi>"
    }
  ],
  "sintesi": "<una frase breve di sintesi complessiva, in italiano>"
}

Regole:
- Se non trovi nulla di sospetto, restituisci "osservazioni": [] e una sintesi che lo dice \
chiaramente — non inventare problemi per riempire la lista.
- Non calcolare né proporre tu un nuovo prezzo o una nuova quantità: descrivi solo il problema.
- Non aggiungere MAI testo, markdown o commenti fuori dal JSON: solo l'oggetto JSON."""


SYSTEM_PROMPT_RENDER = """Sei un architetto che osserva render fotorealistici o foto di un \
progetto edilizio, per aiutare a verificare che il computo metrico rispecchi effettivamente \
quanto rappresentato visivamente. Guarda con la massima attenzione ai dettagli (dedica tutto il \
tempo necessario a un'osservazione accurata, non una descrizione sommaria).

Ricevi due tipi di immagine, sempre chiaramente etichettati nel messaggio: (1) render/foto \
fotorealistiche del progetto; (2) se presenti, una o più immagini di prospetti quotati (disegni \
tecnici con quote altimetriche, es. "±0,00", "+3,00" — l'altezza di riferimento rispetto al piano \
di progetto). Se ricevi anche i prospetti, ricevi INSIEME una lista di "bande" candidate già \
estratte meccanicamente da quelle quote (coppie di valori consecutivi con l'altezza esatta tra i \
due, es. {"da_m": 0.0, "a_m": 3.0, "altezza_m": 3.0}): sono le UNICHE altezze che puoi citare come \
misurate, MAI valori diversi o intermedi.

Descrivi in modo strutturato ciò che vedi nei render/foto, concentrandoti su elementi che hanno un \
impatto economico e che potrebbero non essere ovvi da un semplice questionario testuale:
- materiali di rivestimento delle facciate esterne (intonaco/rasatura liscia, pietra naturale o \
ricostruita, doghe in legno o materiale ligneo, mattone/klinker a vista, altro);
- parapetti e ringhiere: materiale (vetro/cristallo, ferro, muratura piena, legno) e dove si \
trovano (balconi, terrazzi, scale, bordo piscina);
- infissi: materiale e colore apparente (alluminio, PVC, legno), tipologia se riconoscibile \
(scorrevoli, ad anta, porte-finestre a tutta altezza);
- pavimentazioni esterne visibili: materiale (legno/decking, pietra, ghiaia, prato, cemento);
- altri elementi architettonici che potrebbero richiedere una voce di computo dedicata non \
generabile dalla sola pianta (pergole, frangisole, tende da sole fisse, camini, pannelli \
fotovoltaici, piscine e relativi bordi, elementi di arredo esterno fisso).

Per OGNI elemento di categoria "facciata" (rivestimenti che coprono una fascia riconoscibile della \
facciata, es. uno zoccolo in pietra al piano terra), se ti sono state fornite anche le immagini dei \
prospetti quotati E la lista di bande candidate, prova ad abbinarlo a UNA banda: guarda il \
prospetto per capire visivamente tra quali due quote passa la linea di transizione del materiale \
(es. dove finisce la pietra e inizia l'intonaco), poi verifica che quell'intervallo corrisponda \
ESATTAMENTE (stessi da_m/a_m) a una delle bande candidate fornite. Se corrisponde con ragionevole \
sicurezza, riporta quella banda in "banda_abbinata" copiando i valori da_m/a_m ESATTAMENTE come \
ricevuti (mai un valore arrotondato, interpolato o inventato) e "certezza":"alta". Se il prospetto \
non è leggibile a sufficienza, se nessuna banda corrisponde con sicurezza, o se non ti sono stati \
forniti prospetti/bande, lascia "banda_abbinata" a null — è la scelta corretta ogni volta che non \
sei sicuro, molto meglio di un abbinamento sbagliato.

Rispondi SEMPRE E SOLO con un oggetto JSON valido, senza testo prima o dopo, con questa struttura \
esatta:
{
  "elementi": [
    {"categoria": "facciata" | "parapetti" | "infissi" | "pavimentazione_esterna" | "altro",
     "descrizione": "<cosa hai visto, in italiano, una frase>",
     "banda_abbinata": {"da_m": <numero>, "a_m": <numero>} | null,
     "certezza": "alta" | "bassa" | null}
  ],
  "sintesi": "<una o due frasi di sintesi complessiva, in italiano>"
}

Regole:
- Descrivi SOLO ciò che è visivamente riconoscibile con ragionevole certezza: se un materiale non \
è chiaramente distinguibile, dillo esplicitamente nella descrizione invece di indovinare (es. \
"rivestimento chiaro non meglio identificabile: verificare da capitolato") invece di ometterlo.
- Non stimare MAI un'altezza o un'area con un numero che non sia ESATTAMENTE una delle bande \
candidate fornite: se l'intervallo giusto non è tra quelli forniti, "banda_abbinata" resta null, \
anche se a occhio sembra di poter stimare una proporzione — quella stima non è più affidabile di \
un'ipotesi, e qui deve restare un dato misurato o niente.
- "banda_abbinata" e "certezza" si applicano SOLO alla categoria "facciata": per le altre categorie \
lasciali sempre null.
- Non calcolare MAI tu stesso un'area (altezza x perimetro): riporta solo la banda, il calcolo \
dell'area è un passaggio successivo automatico.
- Se le immagini non mostrano elementi esterni rilevanti (es. solo interni), restituisci comunque \
"elementi" con quello che vedi di pertinente (es. materiali di pavimentazione/rivestimento \
interni) e la "sintesi" lo dice chiaramente.
- Non aggiungere MAI testo, markdown o commenti fuori dal JSON: solo l'oggetto JSON."""


SYSTEM_PROMPT_CONFRONTO_PREVENTIVO = """Sei un computista esperto che aiuta un cliente a confrontare i \
preventivi ricevuti da più imprese edili per lo stesso computo metrico. Ricevi (1) l'elenco delle voci del \
computo di riferimento (numero, codice, descrizione, unità di misura, quantità) e (2) il testo o le \
immagini del preventivo che UNA impresa ha inviato — in un formato completamente libero: può essere una \
tabella con codici uguali o diversi da quelli del computo, un elenco a voce singola, un'offerta a corpo per \
macrocategorie, un testo scorrevole, una scansione o foto scritta a mano.

Il tuo compito è ABBINARE ogni prezzo che trovi nel preventivo alla voce di computo corrispondente, \
scrivendo il prezzo UNITARIO (non l'importo totale di riga, che si ricava moltiplicando per la quantità già \
nota) per ciascuna voce abbinata con ragionevole sicurezza.

Rispondi SEMPRE E SOLO con un oggetto JSON valido, senza testo prima o dopo, con questa struttura esatta:
{
  "righe": [
    {"numero": <numero della voce di computo>, "prezzo_unitario": <numero>|null, "nota": "<breve nota, o stringa vuota>"}
  ],
  "totale_dichiarato": <numero>|null,
  "sintesi": "<una o due frasi di sintesi in italiano su come si è svolto l'abbinamento>"
}

Regole, IMPORTANTI:
- Includi una riga in "righe" per OGNI voce del computo ricevuto, anche quelle che il preventivo non tocca \
affatto (in quel caso "prezzo_unitario": null e "nota": "voce non presente in questo preventivo").
- Non inventare MAI un prezzo unitario che non sia calcolabile con certezza dal testo/immagine ricevuto: se \
il preventivo esprime un prezzo "a corpo" per un gruppo di voci senza scomporlo per singola voce, lascia \
"prezzo_unitario": null per quelle voci e scrivi nella "nota" l'importo a corpo dichiarato e a quali voci si \
riferisce (es. "incluso nel prezzo a corpo di 12.000 € per l'intero capitolo scavi, non scomponibile per \
singola voce") — MAI ripartire tu stesso l'importo tra le voci in proporzione, anche se sembra un calcolo \
semplice: è una stima che spetta all'utente decidere se fare, non un dato dichiarato dall'impresa.
- Se il documento usa codici diversi da quelli del computo, abbina comunque per CONTENUTO (descrizione della \
lavorazione), non per codice: due codici diversi possono descrivere la stessa lavorazione.
- Se un prezzo nel preventivo non corrisponde con ragionevole sicurezza a nessuna voce del computo, non \
forzare un abbinamento: ometti quel prezzo (non esiste un posto dove metterlo) e segnalalo nella "sintesi" \
generale, non in una "nota" di riga inventata.
- "totale_dichiarato": il totale complessivo del preventivo, SOLO se l'impresa lo scrive esplicitamente da \
qualche parte nel documento (es. "Totale offerta: 45.000 €"); altrimenti null — non calcolarlo tu sommando \
le righe abbinate, verrà ricalcolato automaticamente e serve solo da controllo incrociato.
- Quantità e prezzi sono sempre in euro. Un prezzo non può mai essere negativo.
- Non aggiungere MAI testo, markdown o commenti fuori dal JSON: solo l'oggetto JSON."""


class AiAssistantError(RuntimeError):
    """Errore di configurazione o di interpretazione: mai propagato come
    modifica applicata, sempre mostrato all'utente com'è."""


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AiAssistantError(
            "La funzione AI non è configurata su questo server: manca la variabile d'ambiente "
            "ANTHROPIC_API_KEY. Impostala nelle variabili d'ambiente del servizio Render con una "
            "chiave valida di console.anthropic.com, poi riprova."
        )
    try:
        import anthropic
    except ImportError as exc:
        raise AiAssistantError(
            "La libreria 'anthropic' non è installata sul server (verifica requirements.txt)."
        ) from exc
    return anthropic.Anthropic(api_key=api_key)


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        # tolleranza minima nel caso il modello racchiuda comunque il JSON in un blocco di codice
        raw = raw.strip("`")
        if "\n" in raw:
            first_line, rest = raw.split("\n", 1)
            raw = rest if first_line.strip().lower() in ("json", "") else raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AiAssistantError(f"Risposta dell'AI non interpretabile come JSON: {exc}") from exc


def _safe_float(value, fallback: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    return v if v >= 0 else fallback


def _system_block(text: str) -> list[dict]:
    # Il system prompt è FISSO (non cambia mai tra una chiamata e l'altra):
    # marcandolo cache_control, le chiamate ravvicinate nel tempo pagano il
    # system prompt una sola volta invece che ad ogni chiamata (il prezzo di
    # lettura dalla cache è una frazione di quello pieno). Non riduce il
    # costo della PRIMA chiamata, solo di quelle successive entro la finestra
    # di cache di Anthropic.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def interpreta_istruzione(voce: dict, istruzione: str) -> dict:
    """voce: dict con almeno codice/categoria/descrizione/unita_misura/quantita/
    prezzo_unitario/note (i campi extra vengono ignorati). istruzione: testo
    libero scritto dall'utente nella colonna Commento. Ritorna sempre un dict
    con le chiavi azione/descrizione/unita_misura/quantita/prezzo_unitario/
    categoria/risposta — mai un'eccezione silenziosa: in caso di problemi
    solleva AiAssistantError con un messaggio da mostrare all'utente."""
    istruzione = (istruzione or "").strip()
    if not istruzione:
        raise AiAssistantError("Scrivi un'osservazione o una richiesta prima di premere invio.")

    client = _client()
    voce_snapshot = {
        "codice": voce.get("codice", ""),
        "categoria": voce.get("categoria", ""),
        "descrizione": voce.get("descrizione", ""),
        "unita_misura": voce.get("unita_misura", ""),
        "quantita": voce.get("quantita", 0),
        "prezzo_unitario": voce.get("prezzo_unitario", 0),
        "note": voce.get("note", ""),
    }
    user_content = (
        "Riga attuale del computo:\n"
        f"{json.dumps(voce_snapshot, ensure_ascii=False, indent=2)}\n\n"
        f"Istruzione dell'utente:\n{istruzione}"
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=_system_block(SYSTEM_PROMPT),
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:  # errori di rete/quota/autenticazione verso Anthropic
        raise AiAssistantError(f"Errore nel contattare il servizio AI: {exc}") from exc

    raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)

    azione = data.get("azione")
    if azione not in ("modifica", "elimina", "nessuna"):
        azione = "nessuna"

    return {
        "azione": azione,
        "descrizione": data.get("descrizione") or voce_snapshot["descrizione"],
        "unita_misura": data.get("unita_misura") or voce_snapshot["unita_misura"],
        "quantita": _safe_float(data.get("quantita"), voce_snapshot["quantita"]),
        "prezzo_unitario": _safe_float(data.get("prezzo_unitario"), voce_snapshot["prezzo_unitario"]),
        "categoria": data.get("categoria") or voce_snapshot["categoria"],
        "risposta": (data.get("risposta") or "Fatto.").strip(),
    }


# Numero massimo di caratteri della descrizione inviati per voce nella
# revisione: riduce i token in ingresso (richiesta esplicita di ottimizzare i
# costi) senza perdere l'informazione che serve al giudizio del modello — la
# descrizione completa non aggiunge nulla al tipo di controllo che deve fare
# (prezzo fuori scala, quantità implausibile, incongruenza), che si basa su
# categoria/quantità/prezzo/unità più i primi termini della descrizione.
_MAX_DESCRIZIONE_REVISIONE = 90


def revisiona_computo(voci: list[dict], meta: dict, tipo_intervento: str) -> dict:
    """voci: lista di dict (righe del computo, come restituite da /api/calcola-voci
    o corrette dall'utente). meta: dict con almeno nome_progetto/committente/
    ubicazione. tipo_intervento: 'nuova_costruzione' o 'ristrutturazione'.
    Ritorna sempre un dict con le chiavi osservazioni/sintesi — mai
    un'eccezione silenziosa: in caso di problemi solleva AiAssistantError."""
    if not voci:
        raise AiAssistantError("Nessuna voce da revisionare.")

    client = _client()
    voci_compatte = []
    for v in voci:
        descrizione = (v.get("descrizione") or "")[:_MAX_DESCRIZIONE_REVISIONE]
        voci_compatte.append({
            "numero": v.get("numero"),
            "categoria": v.get("categoria", ""),
            "descrizione": descrizione,
            "unita_misura": v.get("unita_misura", ""),
            "quantita": v.get("quantita", 0),
            "prezzo_unitario": v.get("prezzo_unitario", 0),
            "origine": v.get("origine", ""),
            "da_completare": bool(v.get("da_completare", False)),
        })
    contesto = {
        "tipo_intervento": tipo_intervento,
        "nome_progetto": meta.get("nome_progetto", ""),
        "numero_voci": len(voci_compatte),
        "totale_computo_eur": round(sum(v["quantita"] * v["prezzo_unitario"] for v in voci_compatte), 2),
    }
    user_content = (
        "Dati di base del progetto:\n"
        f"{json.dumps(contesto, ensure_ascii=False, indent=2)}\n\n"
        "Voci del computo (una riga per voce, campi essenziali):\n"
        f"{json.dumps(voci_compatte, ensure_ascii=False)}"
    )

    try:
        resp = client.messages.create(
            model=MODEL_REVISIONE,
            max_tokens=2000,
            system=_system_block(SYSTEM_PROMPT_REVISIONE),
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:
        raise AiAssistantError(f"Errore nel contattare il servizio AI: {exc}") from exc

    raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)

    osservazioni_raw = data.get("osservazioni")
    osservazioni = []
    if isinstance(osservazioni_raw, list):
        for o in osservazioni_raw:
            if not isinstance(o, dict):
                continue
            gravita = o.get("gravita")
            if gravita not in ("alta", "media", "bassa"):
                gravita = "media"
            osservazioni.append({
                "voce_numero": o.get("voce_numero"),
                "gravita": gravita,
                "descrizione": (o.get("descrizione") or "").strip(),
            })

    return {
        "osservazioni": osservazioni,
        "sintesi": (data.get("sintesi") or "").strip(),
    }


# --- Analisi visiva dei render ---------------------------------------------

# Lato massimo (px) a cui vengono ridimensionate le immagini prima dell'invio:
# oltre questa dimensione Anthropic le ridimensiona comunque internamente per
# la visione, quindi farlo qui non perde dettaglio utile al modello, ma
# riduce il peso del payload (upload più veloce, meno probabilità di superare
# il limite di dimensione per immagine) e il numero di token fatturati.
_RENDER_MAX_SIDE_PX = 1568
_RENDER_JPEG_QUALITY = 85
# Limite pratico di immagini per singola chiamata: oltre non aggiunge
# affidabilità al giudizio ma allunga tempo e costo in modo sproporzionato.
_MAX_RENDER_IMAGES = 6


def _encode_image_for_vision(path: str, page_index: int = 0) -> tuple[str, str] | None:
    """Ritorna (media_type, dati_base64) per un file immagine, ridimensionato
    se necessario. Ritorna None se il file non è un'immagine leggibile (es.
    un file di modello 3D proprietario caricato per errore in questo campo,
    o un file corrotto/vuoto) — in quel caso il chiamante lo segnala come
    scartato invece di far fallire l'intera analisi.

    Il campo "render" del form accetta anche PDF (un render esportato come
    PDF invece che come JPEG/PNG è comune, ed è anche così che vengono
    passati i prospetti quotati): se il file non si apre come immagine
    raster, si tenta di renderizzare la pagina `page_index` con PyMuPDF
    (già una dipendenza del progetto) prima di considerarlo illeggibile."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        img = None
    if img is None:
        try:
            import fitz
            doc = fitz.open(path)
            if page_index >= doc.page_count:
                return None
            page = doc[page_index]
            zoom = min(3.0, _RENDER_MAX_SIDE_PX / max(page.rect.width, page.rect.height, 1))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()
        except Exception:
            return None
    try:
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > _RENDER_MAX_SIDE_PX:
            scale = _RENDER_MAX_SIDE_PX / max(w, h)
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_RENDER_JPEG_QUALITY)
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


# Tolleranza sul confronto tra la banda restituita dal modello e le bande
# candidate realmente estratte da elevation_engine.py: deve corrispondere
# quasi esattamente (il modello copia i numeri, non li ricalcola) — questa
# tolleranza serve solo per eventuali arrotondamenti di virgola mobile nel
# giro JSON, non per "avvicinarsi" a un valore diverso.
_TOLLERANZA_BANDA_M = 0.02


def _banda_valida(banda: dict, bande_candidate: list[dict]) -> dict | None:
    """Verifica che la banda restituita dal modello corrisponda DAVVERO (a
    meno di arrotondamento) a una delle bande candidate fornite — non ci si
    fida MAI di un valore dichiarato dal modello che non sia riconducibile a
    un dato osservato: se non trova corrispondenza, ritorna None (equivale a
    nessun abbinamento, anche se il modello ha dichiarato certezza alta)."""
    try:
        da_m = float(banda.get("da_m"))
        a_m = float(banda.get("a_m"))
    except (TypeError, ValueError):
        return None
    for cand in bande_candidate:
        if (abs(cand["da_m"] - da_m) <= _TOLLERANZA_BANDA_M
                and abs(cand["a_m"] - a_m) <= _TOLLERANZA_BANDA_M):
            return cand
    return None


def analizza_render(image_paths: list[str], prospetti_pdf_path: str | None = None,
                     bande_prospetti: list[dict] | None = None) -> dict:
    """image_paths: percorsi dei render/foto caricati come riferimento
    visivo. prospetti_pdf_path: percorso del PDF (unito) dei prospetti
    quotati, se caricati — se presente, la sua prima pagina viene inclusa
    come immagine aggiuntiva per il confronto visivo. bande_prospetti: le
    bande di altezza già estratte meccanicamente da elevation_engine.py
    (SEMPRE l'unica fonte di numeri: il modello può solo scegliere quale
    banda, tra queste, corrisponde a un rivestimento visto nel render — mai
    inventarne una nuova, verificato server-side in _banda_valida).

    Non usa MAI un'immagine per calcolare quantità o prezzi direttamente:
    l'unica quantificazione possibile è un'altezza copiata verbatim da una
    banda candidata reale. Ritorna sempre un dict con le chiavi elementi/
    sintesi/immagini_analizzate/immagini_scartate — mai un'eccezione
    silenziosa: in caso di problemi solleva AiAssistantError (il chiamante
    lo tratta come non bloccante: i render restano comunque allegati come
    riferimento anche se l'analisi non è disponibile)."""
    if not image_paths:
        raise AiAssistantError("Nessun render da analizzare.")

    encoded: list[tuple[str, str, str]] = []  # (media_type, data, etichetta)
    scartate: list[str] = []
    for p in image_paths[:_MAX_RENDER_IMAGES]:
        enc = _encode_image_for_vision(p)
        if enc:
            encoded.append((enc[0], enc[1], "render/foto del progetto"))
        else:
            scartate.append(os.path.basename(p).split("_", 1)[-1])
    if not encoded:
        raise AiAssistantError(
            "Nessuno dei file caricati come render è un'immagine leggibile (formati supportati: "
            "JPEG, PNG, WEBP, GIF non animata): verifica il formato dei file caricati."
        )

    bande_candidate: list[dict] = list(bande_prospetti or [])
    prospetto_incluso = False
    if prospetti_pdf_path and bande_candidate:
        enc = _encode_image_for_vision(prospetti_pdf_path, page_index=0)
        if enc:
            encoded.append((enc[0], enc[1], "prospetto quotato (disegno tecnico), pagina 1"))
            prospetto_incluso = True

    client = _client()
    content: list[dict] = []
    for media_type, data, etichetta in encoded:
        content.append({"type": "text", "text": f"[Immagine seguente: {etichetta}]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    istruzioni = "Analizza queste immagini del progetto secondo le istruzioni del system prompt."
    if prospetto_incluso:
        istruzioni += (
            "\n\nBande di altezza candidate estratte meccanicamente dal prospetto (le UNICHE che puoi "
            f"citare in \"banda_abbinata\"):\n{json.dumps(bande_candidate, ensure_ascii=False)}"
        )
    content.append({"type": "text", "text": istruzioni})

    try:
        resp = client.messages.create(
            model=MODEL_REVISIONE,
            max_tokens=1500,
            system=_system_block(SYSTEM_PROMPT_RENDER),
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        raise AiAssistantError(f"Errore nel contattare il servizio AI: {exc}") from exc

    raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)

    elementi_raw = data.get("elementi")
    elementi = []
    categorie_valide = {"facciata", "parapetti", "infissi", "pavimentazione_esterna", "altro"}
    for e in (elementi_raw if isinstance(elementi_raw, list) else []):
        if not isinstance(e, dict):
            continue
        categoria = e.get("categoria") if e.get("categoria") in categorie_valide else "altro"
        descrizione = (e.get("descrizione") or "").strip()
        if not descrizione:
            continue
        voce = {"categoria": categoria, "descrizione": descrizione, "banda_abbinata": None}
        banda_dichiarata = e.get("banda_abbinata")
        if categoria == "facciata" and isinstance(banda_dichiarata, dict) and prospetto_incluso:
            banda_reale = _banda_valida(banda_dichiarata, bande_candidate)
            if banda_reale and e.get("certezza") == "alta":
                voce["banda_abbinata"] = {
                    "da_m": banda_reale["da_m"],
                    "a_m": banda_reale["a_m"],
                    "altezza_m": banda_reale["altezza_m"],
                }
        elementi.append(voce)

    return {
        "elementi": elementi,
        "sintesi": (data.get("sintesi") or "").strip(),
        "immagini_analizzate": len(image_paths[:_MAX_RENDER_IMAGES]) - len(scartate),
        "immagini_scartate": scartate,
        "prospetto_incluso": prospetto_incluso,
    }


# --- Interpretazione preventivi imprese (confronto prezzi) ------------------

# Numero massimo di pagine PDF rasterizzate per la visione, se il testo non è
# estraibile (scansione/foto): stesso ordine di grandezza di _MAX_RENDER_IMAGES,
# oltre non aggiunge affidabilità ma allunga costo e tempo.
_MAX_PAGINE_PREVENTIVO = 6
# Sotto questa soglia di caratteri, il testo estratto da un PDF è considerato
# "non significativo" (probabile scansione/immagine senza livello di testo):
# si passa alla visione invece di mandare pochi caratteri di rumore all'AI.
_MIN_CARATTERI_TESTO_PDF = 120
# Numero massimo di righe/celle lette da un preventivo in Excel, per tenere
# sotto controllo i token in ingresso anche per fogli molto grandi.
_MAX_RIGHE_EXCEL_PREVENTIVO = 400
_ESTENSIONI_IMMAGINE = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")


def _estrai_testo_excel(path: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    righe_testo = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=_MAX_RIGHE_EXCEL_PREVENTIVO):
            valori = [str(c.value).strip() for c in row if c.value not in (None, "")]
            if valori:
                righe_testo.append(" | ".join(valori))
        if len(righe_testo) >= _MAX_RIGHE_EXCEL_PREVENTIVO:
            righe_testo.append("[…troncato: foglio più lungo del limite letto…]")
            break
    return "\n".join(righe_testo)


def _prepara_contenuto_preventivo(file_path: str) -> tuple[str | None, list[tuple[str, str]]]:
    """Ritorna (testo, immagini) a partire dal file di preventivo caricato,
    scegliendo automaticamente l'estrazione più adatta: testo per Excel/PDF
    con livello di testo selezionabile, visione (immagini) per PDF scansionati
    o foto dirette. Ritorna sempre almeno uno dei due non vuoto, altrimenti
    solleva AiAssistantError (formato non gestito o file illeggibile)."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    immagini: list[tuple[str, str]] = []

    if ext in ("xlsx", "xlsm", "xls"):
        try:
            testo = _estrai_testo_excel(file_path)
        except Exception as exc:
            raise AiAssistantError(f"Impossibile leggere il file Excel del preventivo: {exc}") from exc
        if not testo.strip():
            raise AiAssistantError("Il file Excel caricato risulta vuoto.")
        return testo, immagini

    if f".{ext}" in _ESTENSIONI_IMMAGINE:
        enc = _encode_image_for_vision(file_path)
        if not enc:
            raise AiAssistantError("L'immagine caricata non è leggibile (formati supportati: JPEG, PNG, WEBP).")
        immagini.append(enc)
        return None, immagini

    if ext == "pdf":
        testo = ""
        try:
            import fitz
            with fitz.open(file_path) as doc:
                testo = "\n".join(p.get_text() for p in doc)
        except Exception:
            testo = ""
        if len(testo.strip()) >= _MIN_CARATTERI_TESTO_PDF:
            return testo, immagini
        # Testo insufficiente: probabile scansione/foto — rasterizza le prime pagine per la visione.
        try:
            import fitz
            with fitz.open(file_path) as doc:
                n_pagine = min(doc.page_count, _MAX_PAGINE_PREVENTIVO)
        except Exception as exc:
            raise AiAssistantError(f"Impossibile aprire il PDF del preventivo: {exc}") from exc
        for i in range(n_pagine):
            enc = _encode_image_for_vision(file_path, page_index=i)
            if enc:
                immagini.append(enc)
        if not immagini:
            raise AiAssistantError(
                "Il PDF caricato non contiene testo selezionabile né pagine leggibili come immagine: "
                "verifica che il file non sia corrotto."
            )
        return None, immagini

    raise AiAssistantError(
        f"Formato file non supportato per il preventivo ('.{ext}'): carica un PDF, un file Excel "
        "(.xlsx) o una foto/scansione (JPEG, PNG)."
    )


def interpreta_preventivo_impresa(voci_riferimento: list[dict], nome_impresa: str, file_path: str) -> dict:
    """voci_riferimento: lista di dict con almeno numero/codice/descrizione/unita_misura/quantita
    (le voci del computo di riferimento — vedi confronto_preventivi_engine.leggi_computo_base).
    nome_impresa: nome dell'impresa che ha inviato il preventivo, solo per il contesto del prompt.
    file_path: percorso del file di preventivo caricato così com'è (PDF, Excel o immagine).

    Ritorna sempre un dict con le chiavi righe/totale_dichiarato/sintesi — mai un'eccezione
    silenziosa: in caso di problemi solleva AiAssistantError. Il risultato è SEMPRE da rivedere e
    correggere dall'utente prima di essere usato per generare il file di confronto finale (vedi
    l'endpoint /api/confronto/interpreta-preventivo e il commento in cima a questo file)."""
    if not voci_riferimento:
        raise AiAssistantError("Nessuna voce di computo di riferimento: carica prima il computo base.")

    testo, immagini = _prepara_contenuto_preventivo(file_path)

    client = _client()
    voci_compatte = [{
        "numero": v.get("numero"),
        "codice": v.get("codice", ""),
        "descrizione": v.get("descrizione", ""),
        "unita_misura": v.get("unita_misura", ""),
        "quantita": v.get("quantita", 0),
    } for v in voci_riferimento]

    content: list[dict] = [{
        "type": "text",
        "text": (
            f"Voci del computo di riferimento ({len(voci_compatte)} righe):\n"
            f"{json.dumps(voci_compatte, ensure_ascii=False)}\n\n"
            f"Preventivo ricevuto dall'impresa \"{nome_impresa}\":"
        ),
    }]
    if testo:
        # Limite di sicurezza sui caratteri di testo inviati: un preventivo non dovrebbe mai
        # avvicinarsi a questa soglia, è solo una protezione contro un file anomalo.
        content.append({"type": "text", "text": testo[:60000]})
    for media_type, data_b64 in immagini:
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data_b64}})
    if immagini:
        content.append({"type": "text", "text": "[le immagini sopra sono le pagine del preventivo ricevuto]"})

    try:
        resp = client.messages.create(
            model=MODEL_REVISIONE,
            max_tokens=4000,
            system=_system_block(SYSTEM_PROMPT_CONFRONTO_PREVENTIVO),
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        raise AiAssistantError(f"Errore nel contattare il servizio AI: {exc}") from exc

    raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)

    numeri_validi = {v["numero"] for v in voci_compatte}
    righe_raw = data.get("righe")
    per_numero: dict[int, dict] = {}
    if isinstance(righe_raw, list):
        for r in righe_raw:
            if not isinstance(r, dict):
                continue
            try:
                numero = int(r.get("numero"))
            except (TypeError, ValueError):
                continue
            if numero not in numeri_validi:
                continue
            prezzo = r.get("prezzo_unitario")
            try:
                prezzo = float(prezzo) if prezzo is not None else None
            except (TypeError, ValueError):
                prezzo = None
            if prezzo is not None and prezzo < 0:
                prezzo = None
            per_numero[numero] = {
                "numero": numero,
                "prezzo_unitario": prezzo,
                "nota": (r.get("nota") or "").strip(),
            }
    # Garantisce una riga per OGNI voce del computo, anche se il modello ne ha
    # omessa qualcuna: meglio "non quotata" esplicito che una voce mancante in
    # tabella senza spiegazione.
    righe = [per_numero.get(v["numero"]) or {"numero": v["numero"], "prezzo_unitario": None, "nota": ""}
             for v in voci_compatte]

    totale_dichiarato = data.get("totale_dichiarato")
    try:
        totale_dichiarato = float(totale_dichiarato) if totale_dichiarato is not None else None
    except (TypeError, ValueError):
        totale_dichiarato = None

    return {
        "righe": righe,
        "totale_dichiarato": totale_dichiarato,
        "sintesi": (data.get("sintesi") or "").strip(),
    }
