Ferma il backend FastAPI del progetto claim-triage-agent.

1. Trova il PID del processo in ascolto sulla porta 8000 con PowerShell:
   `Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess`

2. Se non ci sono processi, segnala che il backend non è in esecuzione e termina.

3. Se trovato un PID, mostralo all'utente e termina il processo:
   `Stop-Process -Id <PID> -Force`

4. Verifica che la porta 8000 sia ora libera e riporta l'esito.
