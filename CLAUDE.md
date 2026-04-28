# Claim Triage Agent — CLAUDE.md

## Progetto
Sistema di triage reclami per utility elettrica con self-improving agent (Scenario 5 — Agentic Solution).
L'agente classifica email in arrivo e migliora nel tempo grazie alle correzioni degli operatori umani.

## Stack
- Python 3.13, FastAPI, uvicorn (no Docker)
- SQLite + SQLModel come ORM
- AWS Bedrock (profile: bootcamp, region: us-west-2) via `anthropic.AnthropicBedrock`
- Modelli: `us.anthropic.claude-sonnet-4-6` (coordinator), `us.anthropic.claude-3-5-haiku-20241022-v1:0` (classificatore + data gen)
- Frontend: HTML + Tailwind CDN + vanilla JS, servito su `/app` via StaticFiles

## Struttura
```
claim-triage-agent/
├── data/               # email sintetiche, categorie, golden set, adversarial set
├── agent/              # coordinator + tools + feedback store
├── backend/            # FastAPI app, modelli DB, routes
├── frontend/           # index.html (include JS inline)
├── eval/               # harness + metriche
├── decisions/          # ADR
└── .claude/
    ├── hooks/          # PreToolUse hook per route_ticket
    └── commands/       # /start e /stop slash commands
```

## Convenzioni Codice
- Tutto in Python, snake_case
- Niente secret hardcoded — usare .env (AWS_PROFILE=bootcamp)
- Ogni tool agent ritorna structured error: `{"isError": true, "code": "...", "guidance": "..."}`
- 5 tool per agente (4 azione + 1 result tool)
- Output strutturato via result tool `submit_triage_result` con JSON Schema — niente parsing manuale

## Architettura Agent
Il CoordinatorAgent (Sonnet) orchestra in sequenza:
1. `classify_complaint` → chiama Haiku via `_classify_with_llm()`, ritorna categoria + priorità + confidence + entità estratte come tool result strutturato
2. `get_customer_history` → storico cliente (mock CRM, ritorna sempre 0 ticket)
3. `get_similar_cases` → casi simili già corretti da umani (dal feedback store)
4. `route_ticket` → assegna ufficio destinatario (bloccato da hook se confidence < 0.5 o emergenza)
5. `submit_triage_result` → result tool con JSON Schema completo; l'output è estratto dal `tool_input`, niente parsing testuale

Se confidence < 0.5 o categoria = emergenza_pericolo: `route_ticket` non viene chiamato, il ticket va in `human_review`.
Se `classify_complaint` ritorna confidence < 0.4 e la categoria è chiaramente sbagliata, Sonnet può correggere.

## Self-Improving Loop
- Override umano → `feedback_store.save_override(...)` persiste in `FeedbackEntry`
- Ad ogni override (`REFRESH_THRESHOLD = 1`) → `_refresh_few_shots()` rigenera i `FewShotExample` dagli ultimi 20 feedback con categoria cambiata
- I few-shot vengono iniettati nel system prompt del coordinator alla prossima chiamata
- `AccuracySnapshot` scattato dopo ogni override — visibile nel tab Analytics

## Guardrails
- `PreToolUse` hook (`.claude/hooks/check_route_ticket.py`) blocca `route_ticket` se `confidence < 0.5`
- Emergenza/Pericolo → sempre P1, sempre human review obbligatoria, `route_ticket` mai chiamato
- Mai loggare PII (nome, indirizzo, dati bancari) in chiaro nei log

## Categorie Reclami
| Categoria | Ufficio | Priorità Default |
|---|---|---|
| emergenza_pericolo | Pronto Intervento Urgente | P1 |
| guasto_interruzione | Pronto Intervento | P2 |
| qualita_fornitura | Tecnico Qualità | P3 |
| reclamo_fattura | Amministrazione | P4 |
| contatore | Tecnico Contatori | P4 |
| cambio_contratto | Commerciale | P4 |
| nuovo_allaccio | Nuovi Allacci | P4 |
| info_generale | Customer Service | P5 |

## Endpoint principali
| Method | Path | Descrizione |
|---|---|---|
| POST | `/emails/process` | Triage singola email |
| POST | `/dataset/load` | Carica golden set nel DB |
| POST | `/dataset/process?limit=N` | Triage batch in background |
| GET | `/dataset/process/status` | Polling progresso batch |
| POST | `/tickets/{id}/override` | Correzione operatore → self-improving loop |
| POST | `/tickets/{id}/confirm` | Conferma decisione agente |
| GET | `/metrics/summary` | KPI generali |
| GET | `/metrics/accuracy` | Storia accuracy per grafici |
| GET | `/metrics/categories` | Accuracy per categoria |

## Come Avviare
```bash
pip install -r requirements.txt
cp .env.example .env        # AWS_PROFILE=bootcamp già impostato

# Avvia backend
python -m uvicorn backend.main:app --host localhost --port 8000

# Frontend su http://localhost:8000/app
# API docs su http://localhost:8000/docs
```

Oppure usa i comandi slash da Claude Code:
- `/start` — avvia il backend e verifica health
- `/stop` — ferma il processo sulla porta 8000

## Eval
```bash
python eval/run_eval.py --limit 20              # 20 email golden
python eval/run_eval.py --adversarial           # solo adversarial set
python eval/run_eval.py --output results.json   # salva risultati
```

## Decisioni Architetturali
- ADR-001: Coordinator + specialist tools vs agente monolitico
- ADR-002: Few-shot injection per il self-improving loop vs fine-tuning
