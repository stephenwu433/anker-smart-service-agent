from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConversationState(str, Enum):
    GUIDE = "GUIDE"
    RESOLVE = "RESOLVE"
    ASK = "ASK"
    HANDOFF = "HANDOFF"
    BLOCK = "BLOCK"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Intent(str, Enum):
    CONSULT = "consult"
    PURCHASE = "purchase"
    USAGE = "usage"
    AFTER_SALES = "after_sales"
    COMPLAINT = "complaint"
    OTHER = "other"


class IntentResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    source: str = Field(min_length=1, max_length=100)


class KnowledgeReference(BaseModel):
    knowledge_id: str
    version: str
    excerpt: str
    source: str


class Inference(BaseModel):
    value: str
    confidence: float = Field(ge=0, le=1)


class SafetyHold(BaseModel):
    active: bool = False
    reasons: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    terms: list[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = None


class JudgmentRecord(BaseModel):
    judgment_id: str
    kind: Literal["safety", "missing_information", "answerability"]
    status: Literal["active", "withdrawn"] = "active"
    depends_on_facts: list[str] = Field(default_factory=list)
    summary: str
    created_at: datetime
    withdrawn_at: Optional[datetime] = None
    withdrawn_reason: Optional[str] = None


class EmpathyCard(BaseModel):
    conversation_id: str
    surface_issue: str
    intent: Intent
    intent_confidence: float = Field(default=0.0, ge=0, le=1)
    intent_source: str = "legacy"
    emotion: Optional[str] = None
    scenario: str
    entities: dict[str, Any] = Field(default_factory=dict)
    confirmed_facts: list[str] = Field(default_factory=list)
    inferences: list[Inference] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    risk_reasons: list[str] = Field(default_factory=list)
    knowledge_refs: list[KnowledgeReference] = Field(default_factory=list)
    next_state: ConversationState
    schema_version: str


class Attachment(BaseModel):
    kind: Literal["product_image", "order_screenshot"]
    filename: str


class ConversationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    product: Optional[str] = Field(default=None, max_length=200)
    order_reference: Optional[str] = Field(default=None, max_length=100)
    attachments: list[Attachment] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def reject_blank_message(self) -> ConversationRequest:
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("message must not be blank")
        return self


class AttemptRecord(BaseModel):
    attempt_id: str
    conversation_id: str
    recommendation: str
    purpose: str
    instructions: str
    observation_target: str
    exit_condition: str
    action_id: Optional[str] = None
    knowledge_id: Optional[str] = None
    depends_on_judgments: list[str] = Field(default_factory=list)
    depends_on_facts: list[str] = Field(default_factory=list)
    execution_status: Literal["proposed", "executed", "skipped", "withdrawn"] = "proposed"
    observation: Optional[str] = None
    outcome: Optional[Literal["improved", "unchanged", "worse", "unknown"]] = None
    based_on_revision: int = 1
    superseded_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ConsumerResponse(BaseModel):
    conversation_id: str
    result_id: str
    state: ConversationState
    message: str
    evidence: list[KnowledgeReference] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    event_id: Optional[str] = None
    event_status: Optional[str] = None
    estimated_response_at: Optional[datetime] = None
    current_attempt: Optional[AttemptRecord] = None


class HandoffDecision(BaseModel):
    accepted: bool
    idempotency_key: str = Field(min_length=1, max_length=200)


class FeedbackRequest(BaseModel):
    result_id: str
    resolved: bool
    comment: Optional[str] = Field(default=None, max_length=1000)


class ResolutionRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class ServiceActionRequest(BaseModel):
    action: Literal["reply", "request_material", "create_after_sales", "escalate_expert", "close"]
    parameters: dict[str, Any] = Field(default_factory=dict)


class CaseRevisionRequest(BaseModel):
    facts: dict[str, str] = Field(default_factory=dict)
    unknown_fields: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=300)


class CaseRevision(BaseModel):
    revision: int
    facts: dict[str, str] = Field(default_factory=dict)
    unknown_fields: list[str] = Field(default_factory=list)
    reason: str
    created_at: datetime


class CaseRecord(BaseModel):
    case_id: str
    conversation_id: str
    original_statement: str
    current_revision: int = 1
    revisions: list[CaseRevision] = Field(default_factory=list)


class AttemptCreateRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=100)


class AttemptUpdateRequest(BaseModel):
    execution_status: Literal["executed", "skipped"]
    observation: Optional[str] = Field(default=None, max_length=1000)
    outcome: Optional[Literal["improved", "unchanged", "worse", "unknown"]] = None
    based_on_revision: Optional[int] = None


class AttemptFeedbackResponse(BaseModel):
    attempt: AttemptRecord
    response: ConsumerResponse


class TicketResultRequest(BaseModel):
    event: Literal["agent_replied", "action_completed", "user_confirmed_resolved", "reopened"]
    note: Optional[str] = Field(default=None, max_length=1000)


class TicketRecord(BaseModel):
    ticket_id: str
    conversation_id: str
    status: Literal[
        "waiting_for_agent", "agent_replied", "action_completed", "resolved", "reopened"
    ]
    version: int = 1
    result_events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EventSummary(BaseModel):
    event_id: str
    conversation_id: str
    status: str
    priority: int
    reason: str
    created_at: datetime
    estimated_response_at: datetime


class HandoffPackage(BaseModel):
    conversation_id: str
    original_messages: list[str]
    summary: str
    confirmed_facts: list[str]
    inferences: list[Inference]
    missing_information: list[str]
    risk_level: RiskLevel
    risk_reasons: list[str]
    knowledge_refs: list[KnowledgeReference]
    executed_actions: list[dict[str, Any]]
    suggested_next_step: str
    event: Optional[EventSummary] = None
    current_state: ConversationState
    schema_version: str
    rule_version: str
    knowledge_version: str
    ticket: Optional[TicketRecord] = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    case: Optional[CaseRecord] = None


class AgentConversationView(BaseModel):
    handoff_package: HandoffPackage
    empathy_card: EmpathyCard
    audit_trail: list[dict[str, Any]]


class InsightMetric(BaseModel):
    value: float
    sample_size: int
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    data_classification: Literal["demo", "real"] = "demo"


class InsightsResponse(BaseModel):
    consultation_count: InsightMetric
    resolution_rate: InsightMetric
    handoff_rate: InsightMetric
    repeat_question_rate: InsightMetric
    top_unresolved_issues: list[dict[str, Union[int, str]]]


class StoredConversation(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    conversation_id: str
    state: ConversationState
    messages: list[str]
    empathy_card: EmpathyCard
    last_result_id: str
    unresolved_attempts: int = 0
    case: Optional[CaseRecord] = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    judgments: list[JudgmentRecord] = Field(default_factory=list)
    safety_hold: SafetyHold = Field(default_factory=SafetyHold)
    ticket: Optional[TicketRecord] = None
    created_at: datetime
    updated_at: datetime
