from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from smart_service_agent.models import StoredConversation


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StorageRepository(Protocol):
    def save_conversation(self, conversation: StoredConversation) -> None: ...

    def get_conversation(self, conversation_id: str) -> StoredConversation | None: ...

    def list_conversations(self) -> list[StoredConversation]: ...

    def add_audit(self, conversation_id: str, event_type: str, payload: dict[str, Any]) -> None: ...

    def get_audit(self, conversation_id: str) -> list[dict[str, Any]]: ...

    def create_event(self, event: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

    def get_event(self, event_id: str) -> dict[str, Any] | None: ...

    def get_event_for_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...

    def list_events(self) -> list[dict[str, Any]]: ...

    def record_feedback(
        self,
        conversation_id: str,
        result_id: str,
        resolved: bool,
        comment: str | None,
    ) -> None: ...

    def list_feedback(self) -> list[dict[str, Any]]: ...

    def add_service_action(
        self, event_id: str, action: str, parameters: dict[str, Any]
    ) -> None: ...

    def get_service_actions(self, event_id: str) -> list[dict[str, Any]]: ...


class MongoRepository:
    """MongoDB persistence adapter. The client connects lazily on first operation."""

    def __init__(
        self,
        uri: str,
        database_name: str,
        timeout_ms: int,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> None:
        self.client = client or MongoClient(
            uri,
            connect=False,
            connectTimeoutMS=timeout_ms,
            serverSelectionTimeoutMS=timeout_ms,
            uuidRepresentation="standard",
        )
        self.database: Database[dict[str, Any]] = self.client[database_name]
        self.conversations: Collection[dict[str, Any]] = self.database["conversations"]
        self.audit_events: Collection[dict[str, Any]] = self.database["audit_events"]
        self.service_events: Collection[dict[str, Any]] = self.database["service_events"]
        self.feedback: Collection[dict[str, Any]] = self.database["feedback"]
        self.service_actions: Collection[dict[str, Any]] = self.database["service_actions"]
        self._indexes_ready = False
        self._index_lock = Lock()

    def close(self) -> None:
        self.client.close()

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        with self._index_lock:
            if self._indexes_ready:
                return
            self.conversations.create_index("conversation_id", unique=True)
            self.audit_events.create_index(
                [("conversation_id", ASCENDING), ("created_at", ASCENDING)]
            )
            self.service_events.create_index("event_id", unique=True)
            self.service_events.create_index(
                [("conversation_id", ASCENDING), ("idempotency_key", ASCENDING)],
                unique=True,
            )
            self.service_events.create_index([("priority", DESCENDING), ("created_at", ASCENDING)])
            self.feedback.create_index("conversation_id")
            self.service_actions.create_index([("event_id", ASCENDING), ("created_at", ASCENDING)])
            self._indexes_ready = True

    @staticmethod
    def _clean(document: dict[str, Any] | None) -> dict[str, Any] | None:
        if document is None:
            return None
        document.pop("_id", None)
        return document

    def save_conversation(self, conversation: StoredConversation) -> None:
        self._ensure_indexes()
        self.conversations.replace_one(
            {"conversation_id": conversation.conversation_id},
            conversation.model_dump(mode="json"),
            upsert=True,
        )

    def get_conversation(self, conversation_id: str) -> StoredConversation | None:
        self._ensure_indexes()
        document = self._clean(self.conversations.find_one({"conversation_id": conversation_id}))
        return StoredConversation.model_validate(document) if document else None

    def list_conversations(self) -> list[StoredConversation]:
        self._ensure_indexes()
        return [
            StoredConversation.model_validate(self._clean(document))
            for document in self.conversations.find()
        ]

    def add_audit(self, conversation_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._ensure_indexes()
        self.audit_events.insert_one(
            {
                "conversation_id": conversation_id,
                "event_type": event_type,
                "created_at": utc_now(),
                **deepcopy(payload),
            }
        )

    def get_audit(self, conversation_id: str) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return list(
            self.audit_events.find(
                {"conversation_id": conversation_id}, {"_id": 0, "conversation_id": 0}
            ).sort("created_at", ASCENDING)
        )

    def create_event(self, event: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._ensure_indexes()
        selector = {
            "conversation_id": event["conversation_id"],
            "idempotency_key": idempotency_key,
        }
        now = utc_now()
        self.service_events.update_one(
            selector,
            {
                "$setOnInsert": {
                    **deepcopy(event),
                    "idempotency_key": idempotency_key,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        result = self._clean(self.service_events.find_one(selector))
        assert result is not None
        return result

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        self._ensure_indexes()
        return self._clean(self.service_events.find_one({"event_id": event_id}))

    def get_event_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        self._ensure_indexes()
        return self._clean(
            self.service_events.find_one(
                {"conversation_id": conversation_id}, sort=[("created_at", DESCENDING)]
            )
        )

    def list_events(self) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return list(
            self.service_events.find({}, {"_id": 0}).sort(
                [("priority", DESCENDING), ("created_at", ASCENDING)]
            )
        )

    def record_feedback(
        self,
        conversation_id: str,
        result_id: str,
        resolved: bool,
        comment: str | None,
    ) -> None:
        self._ensure_indexes()
        self.feedback.insert_one(
            {
                "conversation_id": conversation_id,
                "result_id": result_id,
                "resolved": resolved,
                "comment": comment,
                "created_at": utc_now(),
            }
        )

    def list_feedback(self) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return list(self.feedback.find({}, {"_id": 0}))

    def add_service_action(self, event_id: str, action: str, parameters: dict[str, Any]) -> None:
        self._ensure_indexes()
        new_status = "completed" if action == "close" else "processing"
        now = utc_now()
        self.service_actions.insert_one(
            {
                "event_id": event_id,
                "action": action,
                "parameters": deepcopy(parameters),
                "result": "recorded",
                "created_at": now,
            }
        )
        self.service_events.update_one(
            {"event_id": event_id}, {"$set": {"status": new_status, "updated_at": now}}
        )

    def get_service_actions(self, event_id: str) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return list(
            self.service_actions.find({"event_id": event_id}, {"_id": 0}).sort(
                "created_at", ASCENDING
            )
        )


class MemoryRepository:
    """Deterministic test adapter without an external database."""

    def __init__(self) -> None:
        self.conversations: dict[str, StoredConversation] = {}
        self.audits: list[dict[str, Any]] = []
        self.events: dict[str, dict[str, Any]] = {}
        self.feedback: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []

    def save_conversation(self, conversation: StoredConversation) -> None:
        self.conversations[conversation.conversation_id] = conversation.model_copy(deep=True)

    def get_conversation(self, conversation_id: str) -> StoredConversation | None:
        item = self.conversations.get(conversation_id)
        return item.model_copy(deep=True) if item else None

    def list_conversations(self) -> list[StoredConversation]:
        return [item.model_copy(deep=True) for item in self.conversations.values()]

    def add_audit(self, conversation_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.audits.append(
            {
                "conversation_id": conversation_id,
                "event_type": event_type,
                "created_at": utc_now(),
                **deepcopy(payload),
            }
        )

    def get_audit(self, conversation_id: str) -> list[dict[str, Any]]:
        return [
            {key: deepcopy(value) for key, value in item.items() if key != "conversation_id"}
            for item in self.audits
            if item["conversation_id"] == conversation_id
        ]

    def create_event(self, event: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        for existing in self.events.values():
            if (
                existing["conversation_id"] == event["conversation_id"]
                and existing["idempotency_key"] == idempotency_key
            ):
                return deepcopy(existing)
        now = utc_now()
        stored = {
            **deepcopy(event),
            "idempotency_key": idempotency_key,
            "created_at": now,
            "updated_at": now,
        }
        self.events[str(event["event_id"])] = stored
        return deepcopy(stored)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        event = self.events.get(event_id)
        return deepcopy(event) if event else None

    def get_event_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        items = [
            item for item in self.events.values() if item["conversation_id"] == conversation_id
        ]
        return deepcopy(max(items, key=lambda item: item["created_at"])) if items else None

    def list_events(self) -> list[dict[str, Any]]:
        return deepcopy(
            sorted(self.events.values(), key=lambda item: (-item["priority"], item["created_at"]))
        )

    def record_feedback(
        self,
        conversation_id: str,
        result_id: str,
        resolved: bool,
        comment: str | None,
    ) -> None:
        self.feedback.append(
            {
                "conversation_id": conversation_id,
                "result_id": result_id,
                "resolved": resolved,
                "comment": comment,
                "created_at": utc_now(),
            }
        )

    def list_feedback(self) -> list[dict[str, Any]]:
        return deepcopy(self.feedback)

    def add_service_action(self, event_id: str, action: str, parameters: dict[str, Any]) -> None:
        now = utc_now()
        self.actions.append(
            {
                "event_id": event_id,
                "action": action,
                "parameters": deepcopy(parameters),
                "result": "recorded",
                "created_at": now,
            }
        )
        self.events[event_id]["status"] = "completed" if action == "close" else "processing"
        self.events[event_id]["updated_at"] = now

    def get_service_actions(self, event_id: str) -> list[dict[str, Any]]:
        return deepcopy([item for item in self.actions if item["event_id"] == event_id])
