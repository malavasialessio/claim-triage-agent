# Claim Triage Agent — CLAUDE.md

## Progetto
Sistema di triage reclami per utility elettrica con self-improving agent (Scenario 5 — Agentic Solution).
L'agente classifica email in arrivo e migliora nel tempo grazie alle correzioni degli operatori umani.

## Stack
- Python 3.13, FastAPI, uvicorn (no Docker)
- SQLite + SQLModel come ORM
- AWS Bedrock (profile: bootcamp, region: us-west-2) via `anthropic.AnthropicBedrock`
- Modelli: `anthropic.claude-sonnet-4-6` (agent), `anthropic.claude-3-5-haiku-20241022-v1:0` (data gen / operazioni veloci)
- Frontend: HTML + Tailwind CDN + vanilla JS

## Struttura
```
claim-triage-agent/
├── data/               # email sintetiche, categorie, golden set, adversarial set
├── agent/              # coordinator + tools + feedback store
├── backend/            # FastAPI app, modelli DB, routes
├── frontend/           # index.html, style.css, app.js
├── eval/               # harness + metriche
└── decisions/          # ADR
```

## Convenzioni Codice
- Tutto in Python, snake_case
- Niente secret hardcoded — usare .env (AWS_PROFILE=bootcamp)
- Ogni tool agent ritorna structured error: `{"isError": true, "code": "...", "guidance": "..."}`
- Max 4 tool per agente
- Validation-retry loop: max 3 tentativi su output malformato, loggare retry_count e error_type

## Architettura Agent
Il CoordinatorAgent orchestra in sequenza:
1. `classify_complaint` → categoria + priorità + entità estratte (NO routing)
2. `get_similar_cases` → casi simili già corretti da umani (dal feedback store)
3. `route_ticket` → assegna ufficio destinatario (bloccato da hook se confidence < 0.5)

Se confidence < 0.5 il ticket va in coda `human_review`, `route_ticket` non viene chiamato.

## Self-Improving Loop
- Override umano → `feedback_store.save_override(email_id, agent_decision, human_decision, reason)`
- Ogni 10 override → `feedback_store.refresh_few_shots()` rigenera gli esempi per il classifier
- Accuracy tracciata nel tempo e visibile nel dashboard

## Guardrails
- `PreToolUse` hook blocca `route_ticket` se `confidence < 0.5`
- Mai loggare PII (nome, indirizzo, dati bancari) in chiaro nei log
- Emergenza/Pericolo → sempre P1, sempre human review obbligatoria prima del routing

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

## Come Avviare
```bash
cd claim-triage-agent
pip install -r requirements.txt
cp .env.example .env        # impostare AWS_PROFILE=bootcamp
python backend/main.py      # FastAPI su http://localhost:8000
# aprire frontend/index.html nel browser
```

## Decisioni Architetturali
- ADR-001: Coordinator + specialist tools vs agente monolitico
- ADR-002: Few-shot injection per il self-improving loop vs fine-tuning
