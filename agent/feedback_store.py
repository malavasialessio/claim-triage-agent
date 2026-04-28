"""
Feedback store: persiste gli override degli operatori e aggiorna i few-shot examples.
Questo è il cuore del self-improving loop.
"""

import json
from datetime import datetime
from sqlmodel import Session, select, func
from backend.models import FeedbackEntry, FewShotExample, Ticket, AccuracySnapshot
from backend.database import engine

REFRESH_THRESHOLD = 1  # ogni override aggiorna subito i few-shot


def save_override(
    ticket_id: int,
    email_id: str,
    email_body: str,
    agent_category: str,
    agent_priority: str,
    human_category: str,
    human_priority: str,
    operator_note: str = "",
) -> FeedbackEntry:
    """Salva un override umano e triggera il refresh dei few-shot se necessario."""
    with Session(engine) as session:
        entry = FeedbackEntry(
            ticket_id=ticket_id,
            email_id=email_id,
            agent_category=agent_category,
            agent_priority=agent_priority,
            human_category=human_category,
            human_priority=human_priority,
            operator_note=operator_note,
            category_changed=(agent_category != human_category),
            priority_changed=(agent_priority != human_priority),
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        total_feedback = session.exec(select(func.count(FeedbackEntry.id))).one()
        if total_feedback % REFRESH_THRESHOLD == 0:
            _refresh_few_shots(session, email_body, entry)

        _take_accuracy_snapshot(session)
        session.refresh(entry)  # ri-carica dopo i commit annidati di _refresh_few_shots
        return entry


def _refresh_few_shots(session: Session, latest_body: str, latest_entry: FeedbackEntry):
    """
    Rigenera i FewShotExample dagli ultimi 20 feedback più significativi
    (dove categoria o priorità sono cambiate).
    """
    meaningful = session.exec(
        select(FeedbackEntry)
        .where(FeedbackEntry.category_changed == True)
        .order_by(FeedbackEntry.created_at.desc())
        .limit(20)
    ).all()

    # Cancella i vecchi few-shot
    old = session.exec(select(FewShotExample)).all()
    for o in old:
        session.delete(o)

    # Ricrea dai feedback più recenti
    for fb in meaningful:
        ticket = session.exec(
            select(Ticket).where(Ticket.id == fb.ticket_id)
        ).first()
        if not ticket:
            continue

        snippet = ticket.body[:300] if hasattr(ticket, "body") else ""
        example = FewShotExample(
            email_snippet=snippet,
            correct_category=fb.human_category,
            correct_priority=fb.human_priority,
            explanation=fb.operator_note or "Correzione operatore",
            source_feedback_id=fb.id,
        )
        session.add(example)

    session.commit()


def get_few_shot_prompt(limit: int = 5) -> str:
    """
    Ritorna un blocco di testo con gli ultimi few-shot examples
    da iniettare nel system prompt del coordinator.
    """
    with Session(engine) as session:
        examples = session.exec(
            select(FewShotExample)
            .order_by(FewShotExample.created_at.desc())
            .limit(limit)
        ).all()

    if not examples:
        return ""

    lines = ["Esempi recenti corretti da operatori umani (impara da questi pattern):"]
    for i, ex in enumerate(examples, 1):
        lines.append(
            f"\n[Esempio {i}]\n"
            f"Testo: \"{ex.email_snippet[:200]}...\"\n"
            f"Categoria corretta: {ex.correct_category}\n"
            f"Priorità corretta: {ex.correct_priority}\n"
            f"Nota operatore: {ex.explanation}"
        )
    return "\n".join(lines)


def get_similar_cases(category: str, email_snippet: str, limit: int = 3) -> list[dict]:
    """
    Recupera i casi simili dal feedback store per una data categoria.
    Ritorna solo esempi con categoria cambiata (più informativi).
    """
    with Session(engine) as session:
        entries = session.exec(
            select(FeedbackEntry)
            .where(FeedbackEntry.human_category == category)
            .order_by(FeedbackEntry.created_at.desc())
            .limit(limit * 3)
        ).all()

    results = []
    for e in entries[:limit]:
        results.append({
            "human_category": e.human_category,
            "human_priority": e.human_priority,
            "operator_note": e.operator_note,
            "category_changed": e.category_changed,
            "priority_changed": e.priority_changed,
        })
    return results


def _take_accuracy_snapshot(session: Session):
    """Scatta uno snapshot dell'accuratezza corrente."""
    total = session.exec(
        select(func.count(Ticket.id)).where(Ticket.status.in_(["confirmed", "overridden"]))
    ).one() or 0

    overridden = session.exec(
        select(func.count(Ticket.id)).where(Ticket.status == "overridden")
    ).one() or 0

    if total == 0:
        return

    accuracy = (total - overridden) / total

    # Per categoria
    from backend.models import Ticket as T
    category_stats = {}
    from agent.tools import CATEGORY_TO_OFFICE
    for cat in CATEGORY_TO_OFFICE.keys():
        cat_total = session.exec(
            select(func.count(T.id))
            .where(T.agent_category == cat)
            .where(T.status.in_(["confirmed", "overridden"]))
        ).one() or 0
        cat_wrong = session.exec(
            select(func.count(T.id))
            .where(T.agent_category == cat)
            .where(T.status == "overridden")
            .where(T.human_category != cat)
        ).one() or 0
        if cat_total > 0:
            category_stats[cat] = round((cat_total - cat_wrong) / cat_total, 3)

    few_shot_count = session.exec(select(func.count(FewShotExample.id))).one() or 0

    snapshot = AccuracySnapshot(
        total_reviewed=total,
        total_overridden=overridden,
        accuracy_rate=round(accuracy, 4),
        category_accuracy=json.dumps(category_stats),
        few_shot_count=few_shot_count,
    )
    session.add(snapshot)
    session.commit()


def get_accuracy_history() -> list[dict]:
    """Ritorna la storia degli snapshot di accuratezza per il grafico nel frontend."""
    with Session(engine) as session:
        snapshots = session.exec(
            select(AccuracySnapshot).order_by(AccuracySnapshot.snapshot_at)
        ).all()
    return [
        {
            "snapshot_at": s.snapshot_at.isoformat(),
            "accuracy_rate": s.accuracy_rate,
            "total_reviewed": s.total_reviewed,
            "total_overridden": s.total_overridden,
            "few_shot_count": s.few_shot_count,
            "category_accuracy": json.loads(s.category_accuracy),
        }
        for s in snapshots
    ]
