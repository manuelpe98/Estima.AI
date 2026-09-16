"""Invio di email transazionali (per ora solo il recupero password) tramite
l'API HTTP di Resend (resend.com): scelto perché basta una singola richiesta
POST — nessun server SMTP da configurare — e il piano gratuito copre ampiamente
il volume atteso in questa fase.

Per attivarlo davvero servono, su https://resend.com:
1. Un account Resend.
2. Un dominio verificato (aggiungendo alcuni record DNS al dominio da cui si
   vuole inviare, es. studiope.it o un sottodominio come mail.estima.ai) —
   senza dominio verificato Resend permette di inviare solo a indirizzi email
   di test, non utile per un pubblico reale.
3. La chiave API, da impostare come variabile d'ambiente RESEND_API_KEY su
   Render (stesso schema di ANTHROPIC_API_KEY/STRIPE_SECRET_KEY).
4. Facoltativo: RESEND_FROM_EMAIL con l'indirizzo mittente verificato (es.
   "Estima.AI <notifiche@estima.ai>"); se assente si usa un mittente di test
   di Resend, che funziona SOLO per inviare alla propria casella collegata
   all'account Resend, non a utenti reali.

Finché RESEND_API_KEY non è configurata, invia_email() non genera errori: si
limita a scrivere nei log del server il contenuto che avrebbe inviato (utile
per testare tutto il flusso di recupero password anche prima di aver attivato
Resend, leggendo il link di reset direttamente dai log)."""
from __future__ import annotations
import logging
import os

import requests

logger = logging.getLogger("computo.email")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Estima.AI <onboarding@resend.dev>")


def invia_email(destinatario: str, oggetto: str, corpo_html: str, corpo_testo: str) -> bool:
    """Ritorna True se l'email risulta accettata da Resend per l'invio, False
    altrimenti. Non solleva mai eccezioni: un problema con l'invio email (rete,
    chiave mancante, Resend momentaneamente giù) non deve mai far fallire con
    un errore 500 l'endpoint che lo ha richiesto — nel caso del recupero
    password, l'endpoint chiamante risponde comunque con lo stesso messaggio
    generico indipendentemente dall'esito, per non rivelare se un indirizzo
    email è registrato o meno (vedi /api/auth/richiedi-reset)."""
    if not RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY non configurata: email a %s NON inviata (oggetto: %r). "
            "Contenuto per debug/test locale:\n%s",
            destinatario, oggetto, corpo_testo,
        )
        return False
    try:
        risposta = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [destinatario],
                "subject": oggetto,
                "html": corpo_html,
                "text": corpo_testo,
            },
            timeout=10,
        )
        if risposta.status_code >= 300:
            logger.error(
                "Invio email a %s fallito (HTTP %s): %s", destinatario, risposta.status_code, risposta.text[:500],
            )
            return False
        return True
    except requests.RequestException as exc:
        logger.error("Invio email a %s fallito (errore di rete): %s", destinatario, exc)
        return False
