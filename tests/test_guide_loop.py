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


def test_guide_creates_attempt_and_observation_smoke_blocks() -> None:
    client = make_client()
    conversation = start_guide(client)
    attempt_id = conversation["current_attempt"]["attempt_id"]

    result = client.patch(
        f"/v1/conversations/{conversation['conversation_id']}/attempts/{attempt_id}",
        json={
            "execution_status": "executed",
            "observation": "现在冒烟了",
            "outcome": "worse",
        },
    ).json()

    assert result["attempt"]["execution_status"] == "executed"
    assert result["response"]["state"] == "BLOCK"
    assert "停止使用" in result["response"]["message"]
    attempts = client.get(f"/v1/conversations/{conversation['conversation_id']}/attempts").json()
    assert attempts[0]["execution_status"] == "executed"
    assert all(item["execution_status"] != "proposed" for item in attempts)


def test_guide_improved_observation_resolves() -> None:
    client = make_client()
    conversation = start_guide(client)
    attempt_id = conversation["current_attempt"]["attempt_id"]

    result = client.patch(
        f"/v1/conversations/{conversation['conversation_id']}/attempts/{attempt_id}",
        json={
            "execution_status": "executed",
            "observation": "更换线材后已经可以稳定充电",
            "outcome": "improved",
        },
    ).json()

    assert result["response"]["state"] == "RESOLVE"
    assert result["response"]["current_attempt"] is None


def test_exhausted_catalog_hands_off() -> None:
    client = make_client()
    conversation = start_guide(client)
    conversation_id = conversation["conversation_id"]
    first_id = conversation["current_attempt"]["attempt_id"]
    first = client.patch(
        f"/v1/conversations/{conversation_id}/attempts/{first_id}",
        json={"execution_status": "skipped"},
    ).json()
    second_id = first["response"]["current_attempt"]["attempt_id"]
    second = client.patch(
        f"/v1/conversations/{conversation_id}/attempts/{second_id}",
        json={"execution_status": "skipped"},
    ).json()

    assert second["response"]["state"] == "HANDOFF"
    assert second["response"]["current_attempt"] is None


def test_freeform_attempt_payload_is_rejected() -> None:
    client = make_client()
    conversation = start_guide(client)
    response = client.post(
        f"/v1/conversations/{conversation['conversation_id']}/attempts",
        json={
            "recommendation": "随便写一个步骤",
            "purpose": "绕过目录",
            "instructions": "拆机",
            "observation_target": "是否好转",
            "exit_condition": "无",
        },
    )
    assert response.status_code == 422
