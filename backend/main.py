"""
FastAPI backend for the Claim Triage Agent.
Run with: python backend/main.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select, func
from dotenv import load_dotenv

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from backend.database import init_db, get_session, engine
from backend.models import Email, Ticket, FeedbackEntry, AccuracySnapshot
from agent.coordinator import triage_email
from agent.feedback_store import save_override, get_accuracy_history, REFRESH_THRESHOLD
from agent.tools import CATEGORY_TO_OFFICE

app = FastAPI(title="Claim Triage Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


# ── Schemas ──────────────────────────────────────────────────────────────────

class ProcessEmailRequest(BaseModel):
    email_id: str
    subject: str
    body: str


class ReviewRequest(BaseModel):
    human_category: Optional[str] = None
    human_priority: Optional[str] = None
    operator_note: Optional[str] = None
    reviewed_by: Optional[str] = "operator"


class LoadDatasetRequest(BaseModel):
    limit: Optional[int] = 50


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()


# ── Email endpoints ───────────────────────────────────────────────────────────

@app.post("/emails/process")
def process_email(req: ProcessEmailRequest, session: Session = Depends(get_session)):
    """Invia un'email all'agente e salva il risultato."""
    existing = session.exec(select(Email).where(Email.email_id == req.email_id)).first()
    if not existing:
        email_row = Email(email_id=req.email_id, subject=req.subject, body=req.body, status="processing")
        session.add(email_row)
        session.commit()

    result = triage_email(req.email_id, req.subject, req.body, db_session=session)

    ticket = Ticket(
        email_id=req.email_id,
        agent_category=result["final_category"],
        agent_priority=result["final_priority"],
        agent_office=result["final_office"],
        agent_confidence=result["confidence"],
        agent_reasoning=result.get("reasoning", ""),
        agent_extracted_customer_id=result.get("extracted_customer_id"),
        agent_has_vulnerable_customer=result.get("has_vulnerable_customer", False),
        retry_count=result.get("retry_count", 0),
        retry_errors=result.get("retry_errors", ""),
        status="human_review" if result.get("needs_human_review") else "pending_review",
    )
    session.add(ticket)

    email_row = session.exec(select(Email).where(Email.email_id == req.email_id)).first()
    if email_row:
        email_row.status = "processed"
        session.add(email_row)

    session.commit()
    session.refresh(ticket)

    return {
        "ticket_id": ticket.id,
        "email_id": req.email_id,
        "agent_decision": {
            "category": result["final_category"],
            "priority": result["final_priority"],
            "office": result["final_office"],
            "confidence": result["confidence"],
        },
        "needs_human_review": result.get("needs_human_review", False),
        "human_review_reason": result.get("human_review_reason"),
        "retry_count": result.get("retry_count", 0),
    }


@app.get("/emails/pending")
def get_pending(session: Session = Depends(get_session)):
    """Lista ticket in attesa di review umana."""
    tickets = session.exec(
        select(Ticket)
        .where(Ticket.status.in_(["pending_review", "human_review"]))
        .order_by(Ticket.created_at.desc())
    ).all()

    result = []
    for t in tickets:
        email = session.exec(select(Email).where(Email.email_id == t.email_id)).first()
        result.append(_ticket_with_email(t, email))
    return result


@app.get("/tickets")
def get_all_tickets(session: Session = Depends(get_session)):
    """Lista tutti i ticket con email associata."""
    tickets = session.exec(select(Ticket).order_by(Ticket.created_at.desc())).all()
    result = []
    for t in tickets:
        email = session.exec(select(Email).where(Email.email_id == t.email_id)).first()
        result.append(_ticket_with_email(t, email))
    return result


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket non trovato")
    email = session.exec(select(Email).where(Email.email_id == ticket.email_id)).first()
    return _ticket_with_email(ticket, email)


@app.post("/tickets/{ticket_id}/confirm")
def confirm_ticket(ticket_id: int, reviewed_by: str = "operator", session: Session = Depends(get_session)):
    """Operatore conferma la classificazione dell'agente."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket non trovato")

    ticket.status = "confirmed"
    ticket.reviewed_by = reviewed_by
    ticket.reviewed_at = datetime.utcnow()
    session.add(ticket)
    session.commit()

    from agent.feedback_store import _take_accuracy_snapshot
    with Session(engine) as s:
        _take_accuracy_snapshot(s)

    return {"status": "confirmed", "ticket_id": ticket_id}


@app.post("/tickets/{ticket_id}/override")
def override_ticket(ticket_id: int, req: ReviewRequest, session: Session = Depends(get_session)):
    """Operatore corregge la classificazione — alimenta il self-improving loop."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket non trovato")

    email = session.exec(select(Email).where(Email.email_id == ticket.email_id)).first()

    human_category = req.human_category or ticket.agent_category
    human_priority = req.human_priority or ticket.agent_priority

    ticket.status = "overridden"
    ticket.human_category = human_category
    ticket.human_priority = human_priority
    ticket.human_office = CATEGORY_TO_OFFICE.get(human_category, "Customer Service")
    ticket.operator_note = req.operator_note or ""
    ticket.reviewed_by = req.reviewed_by or "operator"
    ticket.reviewed_at = datetime.utcnow()
    session.add(ticket)
    session.commit()

    # Self-improving loop: salva il feedback
    feedback = save_override(
        ticket_id=ticket_id,
        email_id=ticket.email_id,
        email_body=email.body if email else "",
        agent_category=ticket.agent_category,
        agent_priority=ticket.agent_priority,
        human_category=human_category,
        human_priority=human_priority,
        operator_note=req.operator_note or "",
    )

    return {
        "status": "overridden",
        "ticket_id": ticket_id,
        "feedback_id": feedback.id,
        "few_shots_refreshed": (feedback.id % REFRESH_THRESHOLD == 0),
    }


# ── Dataset loader + batch processor ─────────────────────────────────────────

_process_state: dict = {"running": False, "processed": 0, "total": 0, "errors": 0}


def _process_emails_batch(email_ids: list[str]) -> None:
    global _process_state
    with Session(engine) as session:
        for email_id in email_ids:
            try:
                email = session.exec(select(Email).where(Email.email_id == email_id)).first()
                if not email:
                    _process_state["processed"] += 1
                    continue

                result = triage_email(email.email_id, email.subject, email.body, db_session=session)

                ticket = Ticket(
                    email_id=email.email_id,
                    agent_category=result["final_category"],
                    agent_priority=result["final_priority"],
                    agent_office=result["final_office"],
                    agent_confidence=result["confidence"],
                    agent_reasoning=result.get("reasoning", ""),
                    agent_extracted_customer_id=result.get("extracted_customer_id"),
                    agent_has_vulnerable_customer=result.get("has_vulnerable_customer", False),
                    retry_count=result.get("retry_count", 0),
                    retry_errors=result.get("retry_errors", ""),
                    status="human_review" if result.get("needs_human_review") else "pending_review",
                )
                session.add(ticket)
                email.status = "processed"
                session.commit()
                _process_state["processed"] += 1
            except Exception as e:
                _process_state["errors"] += 1
                _process_state["processed"] += 1

    _process_state["running"] = False


@app.post("/dataset/process")
async def process_dataset(background_tasks: BackgroundTasks, session: Session = Depends(get_session), limit: int = 10):
    """Lancia il triage in background su tutte le email pending."""
    global _process_state
    if _process_state["running"]:
        raise HTTPException(status_code=409, detail="Processing già in corso")

    pending = session.exec(select(Email).where(Email.status == "pending").limit(limit)).all()
    if not pending:
        return {"message": "Nessuna email pending da processare", "total": 0}

    _process_state = {"running": True, "processed": 0, "total": len(pending), "errors": 0}
    background_tasks.add_task(_process_emails_batch, [e.email_id for e in pending])
    return {"message": f"Avviato triage di {len(pending)} email", "total": len(pending)}


@app.get("/dataset/process/status")
def process_status():
    """Stato del batch processing in corso."""
    return _process_state


@app.post("/dataset/load")
def load_dataset(req: LoadDatasetRequest, session: Session = Depends(get_session)):
    """Carica email dal golden set nel DB per demo/test."""
    data_path = Path(__file__).parent.parent / "data" / "emails_golden.json"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail="Dataset non trovato. Eseguire data/generate_emails.py")

    emails = json.loads(data_path.read_text(encoding="utf-8"))
    if req.limit:
        emails = emails[: req.limit]

    loaded = 0
    for e in emails:
        existing = session.exec(select(Email).where(Email.email_id == e["id"])).first()
        if not existing:
            row = Email(
                email_id=e["id"],
                subject=e.get("subject", ""),
                body=e.get("body", ""),
                status="pending",
            )
            session.add(row)
            loaded += 1

    session.commit()
    return {"loaded": loaded, "total_in_db": session.exec(select(func.count(Email.id))).one()}


# ── Metrics ───────────────────────────────────────────────────────────────────

@app.get("/metrics/accuracy")
def get_accuracy():
    """Storia dell'accuratezza nel tempo (per il grafico)."""
    return get_accuracy_history()


@app.get("/metrics/summary")
def get_summary(session: Session = Depends(get_session)):
    """Riepilogo statistico corrente."""
    total_emails = session.exec(select(func.count(Email.id))).one() or 0
    total_tickets = session.exec(select(func.count(Ticket.id))).one() or 0
    pending = session.exec(
        select(func.count(Ticket.id)).where(Ticket.status.in_(["pending_review", "human_review"]))
    ).one() or 0
    confirmed = session.exec(select(func.count(Ticket.id)).where(Ticket.status == "confirmed")).one() or 0
    overridden = session.exec(select(func.count(Ticket.id)).where(Ticket.status == "overridden")).one() or 0
    total_feedback = session.exec(select(func.count(FeedbackEntry.id))).one() or 0

    reviewed = confirmed + overridden
    accuracy = round((confirmed / reviewed) if reviewed > 0 else 0, 4)

    return {
        "total_emails": total_emails,
        "total_tickets": total_tickets,
        "pending_review": pending,
        "confirmed": confirmed,
        "overridden": overridden,
        "accuracy_rate": accuracy,
        "total_feedback_entries": total_feedback,
        "few_shots_until_refresh": REFRESH_THRESHOLD - (total_feedback % REFRESH_THRESHOLD) if total_feedback > 0 else REFRESH_THRESHOLD,
    }


@app.get("/metrics/categories")
def get_category_stats(session: Session = Depends(get_session)):
    """Distribuzione ticket per categoria con accuracy."""
    stats = {}
    for cat in CATEGORY_TO_OFFICE.keys():
        total = session.exec(
            select(func.count(Ticket.id)).where(Ticket.agent_category == cat)
        ).one() or 0
        wrong = session.exec(
            select(func.count(Ticket.id))
            .where(Ticket.agent_category == cat)
            .where(Ticket.status == "overridden")
            .where(Ticket.human_category != cat)
        ).one() or 0
        stats[cat] = {"total": total, "wrong": wrong, "accuracy": round((total - wrong) / total, 3) if total > 0 else None}
    return stats


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ticket_with_email(ticket: Ticket, email: Optional[Email]) -> dict:
    return {
        "ticket_id": ticket.id,
        "email_id": ticket.email_id,
        "subject": email.subject if email else "",
        "body": email.body if email else "",
        "received_at": email.received_at.isoformat() if email else None,
        "agent": {
            "category": ticket.agent_category,
            "priority": ticket.agent_priority,
            "office": ticket.agent_office,
            "confidence": ticket.agent_confidence,
            "reasoning": ticket.agent_reasoning,
            "has_vulnerable_customer": ticket.agent_has_vulnerable_customer,
            "retry_count": ticket.retry_count,
        },
        "human": {
            "category": ticket.human_category,
            "priority": ticket.human_priority,
            "office": ticket.human_office,
            "note": ticket.operator_note,
            "reviewed_by": ticket.reviewed_by,
            "reviewed_at": ticket.reviewed_at.isoformat() if ticket.reviewed_at else None,
        },
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
    }


if __name__ == "__main__":
    host = os.getenv("BACKEND_HOST", "localhost")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
