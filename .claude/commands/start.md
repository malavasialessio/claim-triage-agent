Avvia il backend FastAPI del progetto claim-triage-agent.

1. Controlla se la porta 8000 è già occupata con PowerShell:
   `Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue`
   Se un processo è già in ascolto, segnalalo e non avviarne un altro.

2. Se la porta è libera, avvia il backend in background:
   `python backend/main.py`

3. Attendi che il processo sia pronto (circa 2 secondi), poi verifica con:
   `curl -s http://localhost:8000/health`

4. Riporta l'esito: conferma che il backend è up e comunica gli URL:
   - Frontend: http://localhost:8000/app
   - API docs: http://localhost:8000/docs
   - Health: http://localhost:8000/health
