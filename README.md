# Team Hackathon — Claim Triage Agent

## Participants
- Alessio Malavasi (Architect / Dev / PM)
- [Teammate] (Architect / Dev / Quality)

## Scenario
Scenario 5: Agentic Solution — "The Intake"

## What We Built
An AI-powered complaint triage system for an electric utility company. Inbound customer emails
are automatically classified by category and priority, enriched with customer history and similar
past cases, and routed to the correct internal team.

The system features a **self-improving loop**: every time a human operator overrides the agent's
decision (correcting category, priority, or routing), that override is stored as a labeled example.
After every 10 overrides, the agent's few-shot prompt is automatically updated, so the agent
progressively adapts to the operator's implicit preferences and domain knowledge that no formal
rulebook captures.

What runs: FastAPI backend, SQLite persistence, multi-tool coordinator agent on AWS Bedrock,
interactive review dashboard.
What's scaffolded: eval harness, adversarial test set.

## Challenges Attempted
| # | Challenge | Status | Notes |
|---|---|---|---|
| 1 | The Mandate | done | One-page agent mandate with explicit non-automation scope |
| 2 | The Bones | done | ADR with coordinator + specialist tools, stop_reason handling |
| 3 | The Tools | done | 4 tools with structured errors and boundary descriptions |
| 4 | The Triage | done | Coordinator with validation-retry loop, reasoning logged |
| 5 | The Brake | done | PreToolUse hook blocks route_ticket if confidence < 0.5 |
| 6 | The Attack | partial | Adversarial eval set with prompt injection cases |
| 7 | The Scorecard | partial | Eval harness with accuracy + false-confidence rate |
| 8 | The Loop | done | Override → labeled example → few-shot refresh |

## Key Decisions
- **AWS Bedrock over direct Anthropic API**: corporate constraint, no additional cost approval needed
- **Few-shot injection over fine-tuning**: faster iteration, no retraining cycle, fully transparent
- **SQLite over Postgres**: zero-infrastructure for hackathon, trivial to swap for production
- **confidence < 0.5 → hard block via hook**: deterministic guardrail, not a prompt preference

See `/decisions/` for full ADRs.

## How to Run It
```bash
# Prerequisites: Python 3.11+, AWS CLI with bootcamp profile configured
git clone https://github.com/malavasialessio/claim-triage-agent
cd claim-triage-agent
pip install -r requirements.txt
cp .env.example .env
# edit .env: set AWS_PROFILE=bootcamp

# (Optional) regenerate synthetic email dataset
python data/generate_emails.py

# Start backend
python backend/main.py
# → API running at http://localhost:8000
# → Open frontend/index.html in browser
```

## If We Had More Time
1. Full adversarial eval with automated CI scoring
2. Multi-operator support (each operator has their own preference model)
3. Streaming agent responses in the UI
4. Feedback loop that writes to a vector store for semantic similarity search

## How We Used Claude Code
- Generated all synthetic email data (50 realistic + 10 adversarial)
- Scaffolded the entire FastAPI + SQLModel backend
- Wrote and iterated on the agent tool descriptions
- Built the self-improving loop logic
- Drafted all ADRs and this README
