from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Email(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email_id: str = Field(unique=True, index=True)
    subject: str
    body: str
    received_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="pending")  # pending | processed | human_review | done


class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email_id: str = Field(index=True)

    # Agent decision
    agent_category: str
    agent_priority: str
    agent_office: str
    agent_confidence: float
    agent_reasoning: str = Field(default="")
    agent_extracted_customer_id: Optional[str] = None
    agent_has_vulnerable_customer: bool = Field(default=False)
    retry_count: int = Field(default=0)
    retry_errors: str = Field(default="")

    # Human review
    status: str = Field(default="pending_review")  # pending_review | confirmed | overridden
    human_category: Optional[str] = None
    human_priority: Optional[str] = None
    human_office: Optional[str] = None
    operator_note: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def final_category(self) -> str:
        return self.human_category or self.agent_category

    @property
    def final_priority(self) -> str:
        return self.human_priority or self.agent_priority

    @property
    def was_overridden(self) -> bool:
        return self.status == "overridden"


class FeedbackEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(index=True)
    email_id: str

    agent_category: str
    agent_priority: str
    human_category: str
    human_priority: str
    operator_note: str = Field(default="")

    category_changed: bool
    priority_changed: bool

    created_at: datetime = Field(default_factory=datetime.utcnow)


class FewShotExample(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email_snippet: str        # first 300 chars of body
    correct_category: str
    correct_priority: str
    explanation: str          # from operator_note
    source_feedback_id: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AccuracySnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)
    total_reviewed: int
    total_overridden: int
    accuracy_rate: float
    category_accuracy: str    # JSON string: {category: rate}
    few_shot_count: int
