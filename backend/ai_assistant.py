"""Assistente AI collegato alla colonna "Commento" del computo: l'utente
scrive un'osservazione o una richiesta di modifica su una riga (es. "raddoppia
la quantità", "il prezzo reale è 65 €/m²", "questa voce non serve, eliminala")
e, alla conferma (invio), il sistema interpreta il testo con un modello
linguistico e applica la modifica alla riga stessa — o la elimina — invece di
limitarsi a salvare il commento come nota statica.

Per motivi di sicurezza e di costo, questa funzione:
- richiede una chiave API Anthropic valida nella variabile d'ambiente
  ANTHROPIC_API_KEY sul server (Render): senza, l'endpoint risponde con un
  errore chiaro invece di fallire in modo silenzioso o inventare un risultato;
- lavora SEMPRE su una riga alla volta, con un contratto di risposta JSON
  rigido: il modello non può eseguire codice né toccare altre righe o file.
"""
from __future__ import annotations
import json
import os

MODEL = os.environ.get("ESTIMA_AI_MODEL", "claude-3-5-haiku-20241022")

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
            system=SYSTEM_PROMPT,
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
