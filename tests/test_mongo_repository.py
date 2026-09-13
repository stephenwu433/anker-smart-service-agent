from datetime import timedelta

import mongomock

from smart_service_agent.models import (
    ConversationState,
    EmpathyCard,
    Intent,
    RiskLevel,
    StoredConversation,
)
from smart_service_agent.repository import MongoRepository, utc_now


def make_repository() -> MongoRepository:
    return MongoRepository(
        "mongodb://unused",
        "repository_test",
        100,
        client=mongomock.MongoClient(),
    )


def make_conversation(conversation_id: str) -> StoredConversation:
    now = utc_now()
    card = EmpathyCard(
        conversation_id=conversation_id,
        surface_issue="测试咨询",
        intent=Intent.CONSULT,
        scenario="test",
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.HANDOFF,
        schema_version="1.0",
    )
    return StoredConversation(
        conversation_id=conversation_id,
        state=ConversationState.HANDOFF,
        messages=["测试咨询"],
        empathy_card=card,
        last_result_id="result_test",
        created_at=now,
        updated_at=now,
    )


def test_mongo_repository_round_trips_conversation_and_audit() -> None:
    repository = make_repository()
    conversation = make_conversation("conv_test")

    repository.save_conversation(conversation)
    repository.add_audit("conv_test", "state_transition", {"to_state": "HANDOFF"})

    restored = repository.get_conversation("conv_test")
    assert restored == conversation
    assert repository.get_audit("conv_test")[0]["to_state"] == "HANDOFF"


def test_mongo_event_idempotency_is_scoped_to_conversation() -> None:
    repository = make_repository()
    eta = utc_now() + timedelta(minutes=30)

    first = repository.create_event(
        {
            "event_id": "evt_1",
            "conversation_id": "conv_1",
            "status": "waiting_for_agent",
            "priority": 100,
            "reason": "risk",
            "estimated_response_at": eta,
        },
        "same-key",
    )
    repeated = repository.create_event({**first, "event_id": "evt_should_not_replace"}, "same-key")
    other_conversation = repository.create_event(
        {
            **first,
            "event_id": "evt_2",
            "conversation_id": "conv_2",
        },
        "same-key",
    )

    assert repeated["event_id"] == "evt_1"
    assert other_conversation["event_id"] == "evt_2"


def test_mongo_repository_creates_required_indexes() -> None:
    repository = make_repository()
    repository.list_events()

    event_indexes = repository.service_events.index_information()
    assert any(index.get("unique") for index in event_indexes.values())
    assert any(
        index["key"] == [("priority", -1), ("created_at", 1)] for index in event_indexes.values()
    )
