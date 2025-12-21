# 🕊️ Memento Legacy

Memento Legacy è una web application "Dead Man's Switch" che invia messaggi postumi se non accedi al sistema per un periodo predefinito.

## 🚀 Requisiti Rapidi

1. **Python 3.8+** installato.
2. Un account email per l'invio (consigliato **Gmail** con App Password o **Brevo**).

## 🛠️ Configurazione Iniziale

1. **Installa le dipendenze:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Crea il file `.env`:**
   Copia il contenuto di `.env.example` in un nuovo file chiamato `.env` e inserisci le tue credenziali.

### Configurazione Gmail (Semplice)
- Attiva la **Verifica in 2 passaggi** sul tuo account Google.
- Vai su [Account Google > Sicurezza > Password per le app](https://myaccount.google.com/apppasswords).
- Genera una password per "Altra (nome personalizzato)" chiamandola `Memento`.
- Copia il codice di 16 lettere nel campo `MEMENTO_EMAIL_PASS` del file `.env`.

### Configurazione Alternativa (Brevo)
Se non vuoi usare Gmail:
- Registrati su [Brevo.com](https://www.brevo.com/).
- Vai in **SMTP & API**.
- Usa `smtp-relay.brevo.com` (Porta 587) e la chiave API come password.

## 🏃 Esecuzione

1. **Esegui il Backend:**
   ```bash
   python app.py
   ```
2. **Apri il Frontend:**
   Apri `index.html` nel tuo browser.

## 🧩 Test Rapido
- Crea un account nell'app.
- Aggiungi un messaggio rivolto a te stesso (usa la tua email).
- Attiva la **Modalità Simulazione** nel pannello di controllo.
- Attendi 60 secondi senza premere "I'm Alive": riceverai l'email di test!
