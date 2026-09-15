from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from smart_service_agent.actions import AllowedAction, get_action, next_unused_action
from smart_service_agent.config import Settings
from smart_service_agent.errors import ConflictError, InvalidRequestError
from smart_service_agent.intent import (
    FallbackIntentProvider,
    IntentProvider,
    RuleBasedIntentProvider,
)
from smart_service_agent.knowledge import InMemoryKnowledgeBase, KnowledgeProvider
from smart_service_agent.models import (
    AgentConversationView,
    AttemptCreateRequest,
    AttemptFeedbackResponse,
    AttemptRecord,
    AttemptUpdateRequest,
    CaseRecord,
    CaseRevision,
    CaseRevisionRequest,
    ConsumerResponse,
    ConversationRequest,
    ConversationState,
    EmpathyCard,
    EventSummary,
    HandoffPackage,
    Intent,
    JudgmentRecord,
    KnowledgeReference,
    ResolutionRequest,
    RiskLevel,
    SafetyHold,
    StoredConversation,
    TicketRecord,
    TicketResultRequest,
)
from smart_service_agent.repository import StorageRepository, utc_now
from smart_service_agent.safety import evaluate_safety, is_explicit_resolution

CHARGING_TERMS = ("无法充电", "充不上电", "没反应", "充电中断", "充电不稳定")
OPEN_TICKET_STATUSES = {
    "waiting_for_agent",
    "agent_replied",
    "action_completed",
    "reopened",
}
CHARGING_DETAIL_TERMS = (
    "接入电源后",
    "更换线材后",
    "连接设备后",
    "试过",
    "指示灯",
    "型号",
    "发生在",
)


class ConversationOrchestrator:
    def __init__(
        self,
        repository: StorageRepository,
        settings: Settings,
        intent_provider: IntentProvider | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.knowledge = knowledge_provider or InMemoryKnowledgeBase(settings.knowledge_version)
        self.intent_provider = FallbackIntentProvider(
            intent_provider,
            RuleBasedIntentProvider(),
            settings.intent_minimum_confidence,
        )

    def start(self, request: ConversationRequest) -> ConsumerResponse:
        conversation_id = f"conv_{uuid4().hex}"
        return self._process(conversation_id, request, None)

    def continue_conversation(
        self, conversation_id: str, request: ConversationRequest
    ) -> ConsumerResponse | None:
        existing = self.repository.get_conversation(conversation_id)
        if existing is None:
            return None
        return self._process(conversation_id, request, existing)

    def _process(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> ConsumerResponse:
        now = utc_now()
        messages = [*existing.messages, request.message] if existing else [request.message]
        card = self._build_card(conversation_id, request, existing)
        result_id = f"result_{uuid4().hex}"
        stored = StoredConversation(
            conversation_id=conversation_id,
            state=card.next_state,
            messages=messages,
            empathy_card=card,
            last_result_id=result_id,
            unresolved_attempts=(existing.unresolved_attempts if existing else 0)
            + int(card.next_state not in {ConversationState.RESOLVE, ConversationState.GUIDE}),
            case=existing.case if existing else self._initial_case(conversation_id, request, card),
            attempts=list(existing.attempts) if existing else [],
            judgments=list(existing.judgments) if existing else [],
            safety_hold=self._hold_from_card(card, existing, request),
            ticket=existing.ticket if existing else None,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._sync_case_facts(stored, request, card)
        if card.next_state == ConversationState.BLOCK:
            self._withdraw_proposed_attempts(stored, "safety_hold")
            self._upsert_judgment(
                stored,
                kind="safety",
                depends_on_facts=["safety_symptoms"],
                summary="; ".join(card.risk_reasons) or "device safety hold",
            )
        current_attempt = None
        if card.next_state == ConversationState.GUIDE:
            current_attempt = self._ensure_guide_attempt(stored, card)
            if current_attempt is None:
                card.next_state = ConversationState.HANDOFF
                stored.state = ConversationState.HANDOFF
                stored.empathy_card = card
        response_text, actions = self._consumer_copy(
            card,
            attempt=current_attempt,
            unread_attachment=bool(request.attachments),
            sticky_block=bool(
                existing is not None
                and existing.safety_hold.active
                and card.next_state == ConversationState.BLOCK
            ),
        )
        stored.empathy_card = card
        stored.state = card.next_state
        self.repository.save_conversation(stored)
        self.repository.add_audit(
            conversation_id,
            "state_transition",
            {
                "from_state": existing.state.value if existing else None,
                "to_state": card.next_state.value,
                "trigger": card.risk_reasons or card.missing_information or ["knowledge_available"],
                "rule_version": self.settings.rule_version,
                "knowledge_version": self.settings.knowledge_version,
                "result_id": result_id,
            },
        )
        return self._consumer_response(
            stored, card, result_id, response_text, actions, current_attempt
        )

    def _hold_from_card(
        self,
        card: EmpathyCard,
        existing: StoredConversation | None,
        request: ConversationRequest,
    ) -> SafetyHold:
        previous = existing.safety_hold if existing else SafetyHold()
        decision = evaluate_safety(
            request.message,
            hold=previous,
            source="message",
            mode="message",
        )
        if card.next_state == ConversationState.BLOCK:
            return (
                decision.hold
                if decision.hold.active
                else SafetyHold(
                    active=True,
                    reasons=card.risk_reasons,
                    source="message",
                    terms=[reason.split("：")[-1] for reason in card.risk_reasons],
                    updated_at=utc_now(),
                )
            )
        return decision.hold

    def _build_card(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> EmpathyCard:
        text = request.message
        previous_hold = existing.safety_hold if existing else SafetyHold()
        safety = evaluate_safety(text, hold=previous_hold, source="message", mode="message")
        confirmed = list(
            dict.fromkeys(
                [*(existing.empathy_card.confirmed_facts if existing else []), request.message]
            )
        )
        entities = dict(existing.empathy_card.entities) if existing else {}
        if request.product:
            entities["product"] = request.product
        if request.order_reference:
            entities["order_reference"] = request.order_reference

        unread_attachment = bool(request.attachments)
        if safety.blocked:
            state = ConversationState.BLOCK
            risk = RiskLevel.HIGH
            missing = ["可读取的附件内容"] if unread_attachment else []
            refs: list[KnowledgeReference] = []
            intent = Intent.COMPLAINT
            intent_confidence = 1.0
            intent_source = "safety_rules"
            risk_reasons = list(safety.hold.reasons)
        elif unread_attachment:
            state = ConversationState.HANDOFF
            risk = RiskLevel.LOW
            missing = ["可读取的附件内容"]
            refs = []
            intent_result = self.intent_provider.classify(text)
            intent = intent_result.intent
            intent_confidence = intent_result.confidence
            intent_source = intent_result.source
            risk_reasons = []
        elif self._needs_charging_details(text, existing):
            state = ConversationState.ASK
            risk = RiskLevel.LOW
            missing = ["设备型号、供电指示状态或已经尝试过的方法"]
            refs = []
            intent = Intent.USAGE
            intent_confidence = 1.0
            intent_source = "charging_clarification_rules"
            risk_reasons = []
        elif self._needs_model_details(text, existing):
            state = ConversationState.ASK
            risk = RiskLevel.LOW
            missing = ["设备型号或期望的充电功率"]
            refs = []
            intent = Intent.PURCHASE
            intent_confidence = 1.0
            intent_source = "clarification_rules"
            risk_reasons = []
        else:
            intent_result = self.intent_provider.classify(text)
            if (
                existing
                and intent_result.intent == Intent.CONSULT
                and intent_result.confidence < self.settings.intent_minimum_confidence
            ):
                intent = existing.empathy_card.intent
                intent_confidence = existing.empathy_card.intent_confidence
                intent_source = f"context:{existing.empathy_card.intent_source}"
            else:
                intent = intent_result.intent
                intent_confidence = intent_result.confidence
                intent_source = intent_result.source
            if self._is_charging_issue_context(text, existing) and existing:
                refs = self.knowledge.search(
                    f"{existing.case.original_statement} {text}", Intent.USAGE
                )
            else:
                refs = self.knowledge.search(text, intent)
            if not refs and existing and existing.empathy_card.intent == Intent.PURCHASE:
                context_query = f"{existing.empathy_card.surface_issue} {text}"
                refs = self.knowledge.search(context_query, Intent.PURCHASE)
            missing = []
            risk = RiskLevel.LOW
            risk_reasons = []
            state = (
                ConversationState.GUIDE
                if refs and self._is_charging_issue_context(text, existing)
                else (ConversationState.RESOLVE if refs else ConversationState.HANDOFF)
            )

        return EmpathyCard(
            conversation_id=conversation_id,
            surface_issue=request.message,
            intent=intent,
            intent_confidence=intent_confidence,
            intent_source=intent_source,
            emotion="concerned" if safety.blocked else None,
            scenario=self._scenario(intent),
            entities=entities,
            confirmed_facts=confirmed,
            inferences=[],
            missing_information=missing,
            risk_level=risk,
            risk_reasons=risk_reasons,
            knowledge_refs=refs,
            next_state=state,
            schema_version=self.settings.schema_version,
        )

    def _consumer_copy(
        self,
        card: EmpathyCard,
        *,
        attempt: AttemptRecord | None = None,
        unread_attachment: bool = False,
        sticky_block: bool = False,
    ) -> tuple[str, list[str]]:
        if card.next_state == ConversationState.BLOCK:
            message = (
                "设备安全风险尚未解除，不能继续排查或恢复使用。"
                if sticky_block
                else "你描述的情况可能涉及设备安全风险。"
            )
            message += (
                "请立即停止使用并断开电源，不要拆机、再次通电或继续充电；"
                "将设备移离可燃物，并在确保人身安全的前提下等待处理。"
                "是否同意我将设备信息和当前风险提交给人工客服跟进？"
            )
            if unread_attachment:
                message += "我目前无法读取你上传的附件内容，因此不会根据文件名猜测。"
            return message, ["confirm_handoff", "decline_handoff"]
        if card.next_state == ConversationState.ASK:
            if "设备型号、供电指示状态或已经尝试过的方法" in card.missing_information:
                return (
                    "为了只调整一个条件，请告诉我设备型号、接通电源后的指示状态，以及已经试过的方法；不确定也可以跳过。",
                    ["reply", "skip", "confirm_handoff"],
                )
            return "为了更准确地给出建议，请告诉我设备型号、接口类型或期望的充电功率。", ["reply"]
        if card.next_state == ConversationState.HANDOFF:
            if "可读取的附件内容" in card.missing_information:
                return (
                    "我目前无法读取你上传的附件内容，因此不会根据文件名猜测。"
                    "是否同意转人工客服查看并跟进？",
                    ["confirm_handoff", "decline_handoff"],
                )
            return "当前没有足够的已审核依据来安全回答。是否同意我将现有信息提交给人工客服跟进？", [
                "confirm_handoff",
                "decline_handoff",
            ]
        if card.next_state == ConversationState.GUIDE and attempt is not None:
            return (
                f"请只执行这一个步骤：{attempt.instructions}完成后告诉我观察结果。",
                ["report_attempt", "skip_attempt", "confirm_handoff"],
            )
        labels = {
            Intent.USAGE: "使用指引",
            Intent.PURCHASE: "选购指引",
            Intent.CONSULT: "产品指引",
        }
        label = labels.get(card.intent, "服务指引")
        evidence_text = " ".join(ref.excerpt for ref in card.knowledge_refs)
        if card.next_state == ConversationState.RESOLVE and attempt is not None:
            return (
                "根据你的观察，该步骤已改善。请继续按说明书使用；"
                "如再次出现发热、异味、冒烟或鼓包，立即停止使用并转人工。",
                ["feedback", "new_question"],
            )
        return f"根据已审核的{label}：{evidence_text}", ["feedback", "new_question"]

    def _consumer_response(
        self,
        conversation: StoredConversation,
        card: EmpathyCard,
        result_id: str,
        message: str,
        actions: list[str],
        attempt: AttemptRecord | None,
    ) -> ConsumerResponse:
        return ConsumerResponse(
            conversation_id=conversation.conversation_id,
            result_id=result_id,
            state=card.next_state,
            message=message,
            evidence=(
                card.knowledge_refs
                if card.next_state in {ConversationState.RESOLVE, ConversationState.GUIDE}
                else []
            ),
            available_actions=actions,
            current_attempt=attempt,
        )

    def _initial_case(
        self, conversation_id: str, request: ConversationRequest, card: EmpathyCard
    ) -> CaseRecord:
        now = utc_now()
        facts = self._extract_turn_facts(request, None, card)
        revision = CaseRevision(
            revision=1,
            facts=facts,
            unknown_fields=["product"] if "product" not in facts else [],
            reason="initial_statement",
            created_at=now,
        )
        return CaseRecord(
            case_id=f"case_{uuid4().hex}",
            conversation_id=conversation_id,
            original_statement=request.message,
            revisions=[revision],
        )

    def _extract_turn_facts(
        self,
        request: ConversationRequest,
        existing: StoredConversation | None,
        card: EmpathyCard,
    ) -> dict[str, str]:
        facts = dict(self._current_facts(existing)) if existing else {}
        if request.product:
            facts["product"] = request.product
        text = request.message
        if any(term in text for term in CHARGING_TERMS):
            facts["symptom"] = next(term for term in CHARGING_TERMS if term in text)
        if "指示灯" in text:
            facts["power_indicator"] = (
                "指示灯不亮"
                if any(marker in text for marker in ("不亮", "没有指示", "无指示"))
                else "已说明指示状态"
            )
        if any(term in text for term in ("试过", "更换", "换线", "换过")):
            facts["tried_methods"] = "已尝试更换或调整"
        if card.risk_reasons:
            facts["safety_symptoms"] = "、".join(card.risk_reasons)
        elif is_explicit_resolution(text):
            facts.pop("safety_symptoms", None)
        return facts

    def _sync_case_facts(
        self,
        conversation: StoredConversation,
        request: ConversationRequest,
        card: EmpathyCard,
    ) -> None:
        if conversation.case is None:
            return
        facts = self._extract_turn_facts(request, conversation, card)
        current = self._current_facts(conversation)
        if facts == current:
            return
        if len(conversation.messages) == 1 and conversation.case.revisions:
            conversation.case.revisions[0].facts = facts
            conversation.case.revisions[0].unknown_fields = (
                ["product"] if "product" not in facts else []
            )
            return
        self._append_revision(conversation.case, facts, [], "conversation_turn", utc_now())

    @staticmethod
    def _current_facts(conversation: StoredConversation | None) -> dict[str, str]:
        if conversation is None or conversation.case is None or not conversation.case.revisions:
            return {}
        return dict(conversation.case.revisions[-1].facts)

    @staticmethod
    def _append_revision(
        case: CaseRecord,
        facts: dict[str, str],
        unknown_fields: list[str],
        reason: str,
        now,
    ) -> CaseRevision:
        revision = CaseRevision(
            revision=case.current_revision + 1,
            facts=facts,
            unknown_fields=unknown_fields,
            reason=reason,
            created_at=now,
        )
        case.revisions.append(revision)
        case.current_revision = revision.revision
        return revision

    @staticmethod
    def _is_charging_issue_context(text: str, existing: StoredConversation | None) -> bool:
        return any(term in text for term in CHARGING_TERMS) or bool(
            existing
            and existing.case is not None
            and any(term in existing.case.original_statement for term in CHARGING_TERMS)
        )

    def _needs_charging_details(self, text: str, existing: StoredConversation | None) -> bool:
        if not self._is_charging_issue_context(text, existing) or existing is not None:
            return False
        return not any(term in text for term in CHARGING_DETAIL_TERMS)

    def revise_case(self, conversation_id: str, request: CaseRevisionRequest) -> CaseRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None or conversation.case is None:
            return None
        previous = conversation.case.revisions[-1]
        merged = {**previous.facts, **request.facts}
        for key in request.unknown_fields:
            merged.pop(key, None)
        changed = {
            key
            for key in set(previous.facts) | set(merged)
            if previous.facts.get(key) != merged.get(key)
        }
        changed.update(request.unknown_fields)
        now = utc_now()
        self._append_revision(
            conversation.case, merged, request.unknown_fields, request.reason, now
        )
        snapshot = " ".join(merged.values()) + " " + request.reason
        safety = evaluate_safety(
            snapshot, hold=conversation.safety_hold, source="case_revision", mode="revision"
        )
        conversation.safety_hold = safety.hold
        withdrawn = self._withdraw_impacted_attempts(conversation, changed, "case_revised")
        self._withdraw_impacted_judgments(conversation, changed, "case_revised")
        if safety.blocked:
            conversation.state = ConversationState.BLOCK
            conversation.empathy_card.next_state = ConversationState.BLOCK
            conversation.empathy_card.risk_level = RiskLevel.HIGH
            conversation.empathy_card.risk_reasons = list(safety.hold.reasons)
            conversation.empathy_card.intent = Intent.COMPLAINT
            conversation.empathy_card.intent_source = "safety_rules"
            self._withdraw_proposed_attempts(conversation, "safety_hold")
            self._upsert_judgment(
                conversation,
                kind="safety",
                depends_on_facts=["safety_symptoms"],
                summary="; ".join(safety.hold.reasons) or "device safety hold",
            )
        else:
            conversation.empathy_card.risk_level = RiskLevel.LOW
            conversation.empathy_card.risk_reasons = []
            self._recheck_after_revision(conversation, merged)
        conversation.updated_at = now
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "case_revised",
            {
                "revision": conversation.case.current_revision,
                "reason": request.reason,
                "changed_facts": sorted(changed),
                "withdrawn_attempts": withdrawn,
            },
        )
        return conversation.case

    def _recheck_after_revision(
        self, conversation: StoredConversation, facts: dict[str, str]
    ) -> None:
        if conversation.safety_hold.active:
            return
        charging = "symptom" in facts or (
            conversation.case is not None
            and any(term in conversation.case.original_statement for term in CHARGING_TERMS)
        )
        if not charging:
            return
        has_details = any(key in facts for key in ("power_indicator", "tried_methods", "product"))
        if not has_details:
            conversation.state = ConversationState.ASK
            conversation.empathy_card.next_state = ConversationState.ASK
            conversation.empathy_card.missing_information = [
                "设备型号、供电指示状态或已经尝试过的方法"
            ]
            return
        refs = self.knowledge.search(
            " ".join(facts.values()) or "无法充电",
            Intent.USAGE,
        )
        conversation.empathy_card.knowledge_refs = refs
        if refs:
            conversation.state = ConversationState.GUIDE
            conversation.empathy_card.next_state = ConversationState.GUIDE
            self._ensure_guide_attempt(conversation, conversation.empathy_card)
        else:
            conversation.state = ConversationState.HANDOFF
            conversation.empathy_card.next_state = ConversationState.HANDOFF

    def create_attempt(
        self, conversation_id: str, request: AttemptCreateRequest
    ) -> AttemptRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.safety_hold.active or conversation.state == ConversationState.BLOCK:
            raise ConflictError("safety hold prevents new troubleshooting attempts")
        if conversation.state != ConversationState.GUIDE:
            raise InvalidRequestError("attempts can only be created during GUIDE")
        action = get_action(request.action_id)
        if action is None:
            raise InvalidRequestError("action_id is not in the allowed catalog")
        if any(
            item.action_id == action.action_id and item.execution_status == "proposed"
            for item in conversation.attempts
        ):
            raise ConflictError("duplicate attempt")
        if any(item.execution_status == "proposed" for item in conversation.attempts):
            raise ConflictError("an active proposed attempt already exists")
        attempt = self._propose_action(conversation, action)
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id, "attempt_proposed", {"attempt_id": attempt.attempt_id}
        )
        return attempt

    def update_attempt(
        self, conversation_id: str, attempt_id: str, request: AttemptUpdateRequest
    ) -> AttemptFeedbackResponse | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        attempt = next(
            (item for item in conversation.attempts if item.attempt_id == attempt_id), None
        )
        if attempt is None:
            return None
        current_revision = conversation.case.current_revision if conversation.case else 1
        if attempt.execution_status == "withdrawn":
            raise ConflictError("attempt has been withdrawn")
        if attempt.execution_status in {"executed", "skipped"}:
            raise ConflictError("attempt already recorded")
        if request.based_on_revision is not None and request.based_on_revision != current_revision:
            raise ConflictError("stale case revision")
        if conversation.safety_hold.active or conversation.state == ConversationState.BLOCK:
            raise ConflictError("safety hold prevents continuing troubleshooting")
        if request.execution_status == "executed" and not request.observation:
            raise InvalidRequestError("observation is required when an attempt was executed")
        now = utc_now()
        attempt.execution_status = request.execution_status
        attempt.observation = request.observation
        attempt.outcome = request.outcome or (
            "unknown" if request.execution_status == "skipped" else None
        )
        attempt.updated_at = now
        observation_text = request.observation or ""
        safety = evaluate_safety(
            observation_text,
            hold=conversation.safety_hold,
            source="attempt_observation",
            mode="observation",
        )
        result_id = f"result_{uuid4().hex}"
        conversation.last_result_id = result_id
        conversation.updated_at = now
        current_attempt = attempt
        if safety.blocked:
            conversation.safety_hold = safety.hold
            conversation.state = ConversationState.BLOCK
            conversation.empathy_card.next_state = ConversationState.BLOCK
            conversation.empathy_card.risk_level = RiskLevel.HIGH
            conversation.empathy_card.risk_reasons = list(safety.hold.reasons)
            conversation.empathy_card.intent_source = "safety_rules"
            self._withdraw_proposed_attempts(conversation, "safety_hold")
            self._upsert_judgment(
                conversation,
                kind="safety",
                depends_on_facts=["safety_symptoms"],
                summary="; ".join(safety.hold.reasons) or "device safety hold",
            )
            card = conversation.empathy_card
            message, actions = self._consumer_copy(card, sticky_block=False)
        else:
            message, actions, current_attempt = self._advance_after_attempt(conversation, attempt)
            card = conversation.empathy_card
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "attempt_updated",
            {
                "attempt_id": attempt_id,
                "execution_status": request.execution_status,
                "next_state": conversation.state.value,
            },
        )
        response = self._consumer_response(
            conversation, card, result_id, message, actions, current_attempt
        )
        return AttemptFeedbackResponse(attempt=attempt, response=response)

    def _advance_after_attempt(
        self, conversation: StoredConversation, attempt: AttemptRecord
    ) -> tuple[str, list[str], AttemptRecord | None]:
        outcome = attempt.outcome
        if outcome == "improved":
            conversation.state = ConversationState.RESOLVE
            conversation.empathy_card.next_state = ConversationState.RESOLVE
            conversation.empathy_card.risk_level = RiskLevel.LOW
            message, actions = self._consumer_copy(conversation.empathy_card, attempt=attempt)
            return message, actions, None
        if outcome == "worse":
            conversation.state = ConversationState.HANDOFF
            conversation.empathy_card.next_state = ConversationState.HANDOFF
            message, actions = self._consumer_copy(conversation.empathy_card)
            return message, actions, None
        next_attempt = self._ensure_guide_attempt(conversation, conversation.empathy_card)
        if next_attempt is None:
            conversation.state = ConversationState.HANDOFF
            conversation.empathy_card.next_state = ConversationState.HANDOFF
            message, actions = self._consumer_copy(conversation.empathy_card)
            return message, actions, None
        conversation.state = ConversationState.GUIDE
        conversation.empathy_card.next_state = ConversationState.GUIDE
        message, actions = self._consumer_copy(conversation.empathy_card, attempt=next_attempt)
        return message, actions, next_attempt

    def inspect_feedback(self, conversation_id: str, comment: str | None) -> None:
        if not comment:
            return
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return
        safety = evaluate_safety(
            comment, hold=conversation.safety_hold, source="feedback", mode="feedback"
        )
        if not safety.blocked or not safety.terms:
            return
        conversation.safety_hold = safety.hold
        conversation.state = ConversationState.BLOCK
        conversation.empathy_card.next_state = ConversationState.BLOCK
        conversation.empathy_card.risk_level = RiskLevel.HIGH
        conversation.empathy_card.risk_reasons = list(safety.hold.reasons)
        self._withdraw_proposed_attempts(conversation, "safety_hold")
        conversation.updated_at = utc_now()
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "feedback_safety_hold",
            {"terms": list(safety.terms)},
        )

    def confirm_resolution(
        self, conversation_id: str, request: ResolutionRequest
    ) -> TicketRecord | None:
        return self.record_ticket_result(
            conversation_id,
            TicketResultRequest(event="user_confirmed_resolved", note=request.note),
            actor="consumer",
        )

    def record_ticket_result(
        self,
        conversation_id: str,
        request: TicketResultRequest,
        actor: str = "agent",
    ) -> TicketRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None or conversation.ticket is None:
            return None
        if request.event == "user_confirmed_resolved" and actor != "consumer":
            raise ConflictError("user confirmation must come from the consumer")
        if actor == "consumer" and request.event != "user_confirmed_resolved":
            raise ConflictError("consumers can only confirm resolution")
        status_map = {
            "agent_replied": "agent_replied",
            "action_completed": "action_completed",
            "user_confirmed_resolved": "resolved",
            "reopened": "reopened",
        }
        now = utc_now()
        conversation.ticket.status = status_map[request.event]
        conversation.ticket.version += 1
        conversation.ticket.updated_at = now
        conversation.ticket.result_events.append(
            {
                "event": request.event,
                "note": request.note,
                "actor": actor,
                "created_at": now.isoformat(),
            }
        )
        conversation.updated_at = now
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "ticket_result",
            {
                "event": request.event,
                "ticket_version": conversation.ticket.version,
                "actor": actor,
            },
        )
        return conversation.ticket

    @staticmethod
    def _needs_model_details(text: str, existing: StoredConversation | None) -> bool:
        model_selection_context = "型号" in text or bool(
            existing and existing.empathy_card.intent == Intent.PURCHASE
        )
        if not model_selection_context:
            return False
        informative = (
            "iPhone",
            "Android",
            "USB-C",
            "Lightning",
            "Type-C",
            "快充",
            "功率",
            "PD",
            "PPS",
        )
        unknown = ("不知道", "不清楚", "不会判断")
        has_details = any(term in text for term in informative)
        explicitly_unknown = any(term in text for term in unknown)
        return not has_details or explicitly_unknown

    @staticmethod
    def _scenario(intent: Intent) -> str:
        return {
            Intent.AFTER_SALES: "after_sales_service",
            Intent.PURCHASE: "product_selection",
            Intent.USAGE: "product_usage",
            Intent.COMPLAINT: "customer_complaint",
        }.get(intent, "product_consultation")

    def create_handoff(self, conversation_id: str, idempotency_key: str) -> EventSummary | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.ticket and conversation.ticket.status in OPEN_TICKET_STATUSES:
            event = self.repository.get_event(conversation.ticket.ticket_id)
            if event is None:
                event = self.repository.get_event_for_conversation(conversation_id)
            if event is not None:
                conversation.state = ConversationState.HANDOFF
                conversation.empathy_card.next_state = ConversationState.HANDOFF
                conversation.updated_at = utc_now()
                self.repository.save_conversation(conversation)
                self.repository.add_audit(
                    conversation_id,
                    "handoff_reused",
                    {
                        "event_id": event["event_id"],
                        "idempotency_key": idempotency_key,
                        "rule_version": self.settings.rule_version,
                    },
                )
                return self._event_summary(event)
        eta = utc_now() + timedelta(minutes=self.settings.handoff_eta_minutes)
        event = self.repository.create_event(
            {
                "event_id": f"evt_{uuid4().hex}",
                "conversation_id": conversation_id,
                "status": "waiting_for_agent",
                "priority": 100 if conversation.empathy_card.risk_level == RiskLevel.HIGH else 50,
                "reason": "; ".join(conversation.empathy_card.risk_reasons)
                or "依据不足或用户请求人工",
                "estimated_response_at": eta.isoformat(),
            },
            idempotency_key,
        )
        conversation.state = ConversationState.HANDOFF
        conversation.empathy_card.next_state = ConversationState.HANDOFF
        conversation.updated_at = utc_now()
        now = utc_now()
        conversation.ticket = TicketRecord(
            ticket_id=str(event["event_id"]),
            conversation_id=conversation_id,
            status="waiting_for_agent",
            created_at=now,
            updated_at=now,
        )
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "handoff_created",
            {"event_id": event["event_id"], "rule_version": self.settings.rule_version},
        )
        return self._event_summary(event)

    @staticmethod
    def _event_summary(event: dict[str, object]) -> EventSummary:
        return EventSummary(
            event_id=str(event["event_id"]),
            conversation_id=str(event["conversation_id"]),
            status=str(event["status"]),
            priority=int(event["priority"]),
            reason=str(event["reason"]),
            created_at=str(event["created_at"]),
            estimated_response_at=str(event["estimated_response_at"]),
        )

    def agent_view(self, conversation_id: str) -> AgentConversationView | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        event_row = self.repository.get_event_for_conversation(conversation_id)
        event = self._event_summary(event_row) if event_row else None
        actions = self.repository.get_service_actions(event.event_id) if event else []
        card = conversation.empathy_card
        package = HandoffPackage(
            conversation_id=conversation_id,
            original_messages=conversation.messages,
            summary=card.surface_issue,
            confirmed_facts=card.confirmed_facts,
            inferences=card.inferences,
            missing_information=card.missing_information,
            risk_level=card.risk_level,
            risk_reasons=card.risk_reasons,
            knowledge_refs=card.knowledge_refs,
            executed_actions=actions,
            suggested_next_step="优先核实设备型号、供电状态与安全风险，并按授权范围跟进"
            if card.risk_level == RiskLevel.HIGH
            else "核实诉求并补充可靠依据",
            event=event,
            current_state=conversation.state,
            schema_version=self.settings.schema_version,
            rule_version=self.settings.rule_version,
            knowledge_version=self.settings.knowledge_version,
            ticket=conversation.ticket,
            attempts=conversation.attempts,
            case=conversation.case,
        )
        return AgentConversationView(
            handoff_package=package,
            empathy_card=card,
            audit_trail=self.repository.get_audit(conversation_id),
        )

    def _ensure_guide_attempt(
        self, conversation: StoredConversation, card: EmpathyCard
    ) -> AttemptRecord | None:
        proposed = next(
            (item for item in conversation.attempts if item.execution_status == "proposed"),
            None,
        )
        if proposed is not None:
            return proposed
        knowledge_ids = [ref.knowledge_id for ref in card.knowledge_refs] or ["KB-CHARGING-001"]
        action = next_unused_action(conversation.attempts, knowledge_ids)
        if action is None:
            return None
        attempt = self._propose_action(conversation, action)
        self.repository.add_audit(
            conversation.conversation_id,
            "attempt_proposed",
            {"attempt_id": attempt.attempt_id, "action_id": action.action_id},
        )
        return attempt

    def _propose_action(
        self, conversation: StoredConversation, action: AllowedAction
    ) -> AttemptRecord:
        now = utc_now()
        revision = conversation.case.current_revision if conversation.case else 1
        judgment_ids = [
            item.judgment_id
            for item in conversation.judgments
            if item.status == "active" and item.kind in {"answerability", "missing_information"}
        ]
        attempt = AttemptRecord(
            attempt_id=f"attempt_{uuid4().hex}",
            conversation_id=conversation.conversation_id,
            recommendation=action.recommendation,
            purpose=action.purpose,
            instructions=action.instructions,
            observation_target=action.observation_target,
            exit_condition=action.exit_condition,
            action_id=action.action_id,
            knowledge_id=action.knowledge_id,
            depends_on_judgments=judgment_ids,
            depends_on_facts=list(action.depends_on_facts),
            based_on_revision=revision,
            created_at=now,
            updated_at=now,
        )
        conversation.attempts.append(attempt)
        self._upsert_judgment(
            conversation,
            kind="answerability",
            depends_on_facts=list(action.depends_on_facts),
            summary=f"action {action.action_id} is answerable from reviewed knowledge",
        )
        conversation.updated_at = now
        return attempt

    def _withdraw_proposed_attempts(
        self, conversation: StoredConversation, reason: str
    ) -> list[str]:
        return self._withdraw_attempts(
            conversation,
            reason,
            predicate=lambda item: item.execution_status == "proposed",
        )

    def _withdraw_impacted_attempts(
        self, conversation: StoredConversation, changed_facts: set[str], reason: str
    ) -> list[str]:
        return self._withdraw_attempts(
            conversation,
            reason,
            predicate=lambda item: (
                item.execution_status == "proposed"
                and bool(set(item.depends_on_facts) & changed_facts)
            ),
        )

    def _withdraw_attempts(
        self,
        conversation: StoredConversation,
        reason: str,
        predicate: Callable[[AttemptRecord], bool],
    ) -> list[str]:
        now = utc_now()
        withdrawn: list[str] = []
        for attempt in conversation.attempts:
            if not predicate(attempt):
                continue
            attempt.execution_status = "withdrawn"
            attempt.updated_at = now
            withdrawn.append(attempt.attempt_id)
        if withdrawn:
            self.repository.add_audit(
                conversation.conversation_id,
                "attempts_withdrawn",
                {"attempt_ids": withdrawn, "reason": reason},
            )
        return withdrawn

    def _withdraw_impacted_judgments(
        self, conversation: StoredConversation, changed_facts: set[str], reason: str
    ) -> None:
        now = utc_now()
        for judgment in conversation.judgments:
            if judgment.status != "active":
                continue
            if set(judgment.depends_on_facts) & changed_facts:
                judgment.status = "withdrawn"
                judgment.withdrawn_at = now
                judgment.withdrawn_reason = reason

    def _upsert_judgment(
        self,
        conversation: StoredConversation,
        *,
        kind: Literal["safety", "missing_information", "answerability"],
        depends_on_facts: list[str],
        summary: str,
    ) -> JudgmentRecord:
        now = utc_now()
        for judgment in conversation.judgments:
            if judgment.kind == kind and judgment.status == "active":
                judgment.depends_on_facts = depends_on_facts
                judgment.summary = summary
                return judgment
        record = JudgmentRecord(
            judgment_id=f"judge_{uuid4().hex}",
            kind=kind,
            depends_on_facts=depends_on_facts,
            summary=summary,
            created_at=now,
        )
        conversation.judgments.append(record)
        return record
