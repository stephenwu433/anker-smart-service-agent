from fastapi.testclient import TestClient

from smart_service_agent.main import create_app
from smart_service_agent.repository import MemoryRepository


def make_client() -> TestClient:
    return TestClient(create_app(MemoryRepository()))


def start_guide(client: TestClient) -> dict:
    first = client.post("/v1/conversations", json={"message": "我的充电器总是无法充电"}).json()
    return client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "接通电源后没有指示灯，我已经试过更换充电线"},
    ).json()


def test_handoff_package_includes_consumer_attempts_and_case() -> None:
    client = make_client()
    conversation = start_guide(client)
    conversation_id = conversation["conversation_id"]
    attempt_id = conversation["current_attempt"]["attempt_id"]
    client.patch(
        f"/v1/conversations/{conversation_id}/attempts/{attempt_id}",
        json={
            "execution_status": "executed",
            "observation": "换线后没有改善",
            "outcome": "unchanged",
        },
    )
    client.post(
        f"/v1/conversations/{conversation_id}/handoff",
        json={"accepted": True, "idempotency_key": "handoff-attempts"},
    )

    view = client.get(f"/v1/agent/conversations/{conversation_id}").json()
    package = view["handoff_package"]
    assert package["attempts"]
    assert any(item["execution_status"] == "executed" for item in package["attempts"])
    assert package["case"]["revisions"]
    assert package["executed_actions"] == []


def test_open_ticket_is_reused_for_new_idempotency_key() -> None:
    client = make_client()
    blocked = client.post("/v1/conversations", json={"message": "充电器鼓包"}).json()
    conversation_id = blocked["conversation_id"]
    first = client.post(
        f"/v1/conversations/{conversation_id}/handoff",
        json={"accepted": True, "idempotency_key": "key-one"},
    ).json()
    second = client.post(
        f"/v1/conversations/{conversation_id}/handoff",
        json={"accepted": True, "idempotency_key": "key-two"},
    ).json()

    assert first["event_id"] == second["event_id"]
    view = client.get(f"/v1/agent/conversations/{conversation_id}").json()
    assert view["handoff_package"]["ticket"]["ticket_id"] == first["event_id"]
    events = client.get("/v1/agent/events").json()
    matching = [item for item in events if item["conversation_id"] == conversation_id]
    assert len(matching) == 1
