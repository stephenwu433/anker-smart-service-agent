from fastapi.testclient import TestClient

from smart_service_agent.main import create_app
from smart_service_agent.repository import MemoryRepository


def make_client() -> TestClient:
    return TestClient(create_app(MemoryRepository()))


def test_pilling_flow_asks_once_then_returns_single_condition_guide() -> None:
    client = make_client()
    first = client.post("/v1/conversations", json={"message": "我的充电器总是无法充电"}).json()

    assert first["state"] == "ASK"
    assert "skip" in first["available_actions"]
    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "接通电源后没有指示灯，我已经试过更换充电线"},
    ).json()

    assert second["state"] == "GUIDE"
    assert second["evidence"][0]["knowledge_id"] == "KB-CHARGING-001"
    assert "只调整一个条件" in second["evidence"][0]["excerpt"]
    assert second["current_attempt"]["action_id"] == "swap_known_good_cable"
    assert second["current_attempt"]["execution_status"] == "proposed"
    attempts = client.get(f"/v1/conversations/{first['conversation_id']}/attempts").json()
    assert len(attempts) == 1


def test_case_revision_preserves_history_and_unknown_fields() -> None:
    client = make_client()
    created = client.post(
        "/v1/conversations", json={"message": "充电器无法充电", "product": "演示充电器"}
    ).json()
    path = f"/v1/conversations/{created['conversation_id']}/case/revisions"

    revised = client.post(
        path,
        json={
            "facts": {"product": "更正后的充电器", "step": "接入电源后"},
            "unknown_fields": ["skincare_amount"],
            "reason": "用户更正产品并补充步骤",
        },
    ).json()

    assert revised["current_revision"] == 2
    assert len(revised["revisions"]) == 2
    assert revised["revisions"][0]["facts"]["product"] == "演示充电器"
    assert revised["revisions"][1]["facts"]["product"] == "更正后的充电器"


def _start_guide(client: TestClient) -> dict:
    first = client.post("/v1/conversations", json={"message": "我的充电器总是无法充电"}).json()
    return client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "接通电源后没有指示灯，我已经试过更换充电线"},
    ).json()


def test_attempt_separates_skip_execution_and_observation_and_rejects_duplicate() -> None:
    client = make_client()
    conversation = _start_guide(client)
    conversation_id = conversation["conversation_id"]
    path = f"/v1/conversations/{conversation_id}/attempts"
    action_id = conversation["current_attempt"]["action_id"]

    duplicate = client.post(path, json={"action_id": action_id})
    assert duplicate.status_code == 409

    attempt_id = conversation["current_attempt"]["attempt_id"]
    skipped = client.patch(f"{path}/{attempt_id}", json={"execution_status": "skipped"}).json()
    assert skipped["attempt"]["execution_status"] == "skipped"
    assert skipped["attempt"]["outcome"] == "unknown"
    assert skipped["response"]["state"] == "GUIDE"
    assert skipped["response"]["current_attempt"]["action_id"] == "retry_direct_wall_adapter"


def test_executed_attempt_requires_observation() -> None:
    client = make_client()
    conversation = _start_guide(client)
    attempt_id = conversation["current_attempt"]["attempt_id"]
    response = client.patch(
        f"/v1/conversations/{conversation['conversation_id']}/attempts/{attempt_id}",
        json={"execution_status": "executed"},
    )
    assert response.status_code == 422


def test_ticket_result_events_remain_distinct_and_support_reopen() -> None:
    client = make_client()
    blocked = client.post("/v1/conversations", json={"message": "充电时出现异味"}).json()
    client.post(
        f"/v1/conversations/{blocked['conversation_id']}/handoff",
        json={"accepted": True, "idempotency_key": "ticket-state-test"},
    )
    agent_path = f"/v1/agent/conversations/{blocked['conversation_id']}/ticket/results"
    consumer_path = f"/v1/conversations/{blocked['conversation_id']}/resolution"

    statuses = []
    for event in ("agent_replied", "action_completed"):
        response = client.post(agent_path, json={"event": event, "note": event})
        assert response.status_code == 200
        statuses.append(response.json()["status"])

    forbidden = client.post(
        agent_path, json={"event": "user_confirmed_resolved", "note": "agent-forged"}
    )
    assert forbidden.status_code == 409

    confirmed = client.post(consumer_path, json={"note": "user confirmed"})
    assert confirmed.status_code == 200
    statuses.append(confirmed.json()["status"])

    reopened = client.post(agent_path, json={"event": "reopened", "note": "reopened"})
    assert reopened.status_code == 200
    statuses.append(reopened.json()["status"])

    assert statuses == ["agent_replied", "action_completed", "resolved", "reopened"]
    assert len(reopened.json()["result_events"]) == 4


def test_minimum_workspaces_are_available() -> None:
    client = make_client()

    assert "安克智能服务助手（比赛演示）" in client.get("/workspace/consumer").text
    assert "人工客服工作台" in client.get("/workspace/agent").text
