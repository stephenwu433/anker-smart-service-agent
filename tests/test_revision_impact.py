from fastapi.testclient import TestClient

from smart_service_agent.main import create_app
from smart_service_agent.repository import MemoryRepository


def make_client() -> TestClient:
    return TestClient(create_app(MemoryRepository()))


def start_guide(client: TestClient) -> dict:
    first = client.post(
        "/v1/conversations",
        json={"message": "我的充电器总是无法充电", "product": "演示充电器"},
    ).json()
    return client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "接通电源后没有指示灯，我已经试过更换充电线"},
    ).json()


def test_revision_withdraws_proposed_attempt_and_keeps_executed() -> None:
    client = make_client()
    conversation = start_guide(client)
    conversation_id = conversation["conversation_id"]
    first_id = conversation["current_attempt"]["attempt_id"]
    client.patch(
        f"/v1/conversations/{conversation_id}/attempts/{first_id}",
        json={
            "execution_status": "executed",
            "observation": "换线后仍然无法充电",
            "outcome": "unchanged",
        },
    )
    proposed = client.get(f"/v1/conversations/{conversation_id}/attempts").json()
    active = next(item for item in proposed if item["execution_status"] == "proposed")

    revised = client.post(
        f"/v1/conversations/{conversation_id}/case/revisions",
        json={
            "facts": {"product": "更正后的充电器"},
            "unknown_fields": [],
            "reason": "用户更正产品型号",
        },
    ).json()

    attempts = client.get(f"/v1/conversations/{conversation_id}/attempts").json()
    executed = next(item for item in attempts if item["attempt_id"] == first_id)
    withdrawn = next(item for item in attempts if item["attempt_id"] == active["attempt_id"])
    assert executed["execution_status"] == "executed"
    assert withdrawn["execution_status"] == "withdrawn"
    assert revised["current_revision"] >= 2
    remaining = [item for item in attempts if item["execution_status"] == "proposed"]
    assert remaining
    assert remaining[0]["attempt_id"] != active["attempt_id"]


def test_revision_can_clear_incorrect_safety_fact() -> None:
    client = make_client()
    blocked = client.post("/v1/conversations", json={"message": "无法充电而且鼓包"}).json()
    client.post(
        f"/v1/conversations/{blocked['conversation_id']}/case/revisions",
        json={
            "facts": {},
            "unknown_fields": ["safety_symptoms"],
            "reason": "没有鼓包，只是充不上电",
        },
    )
    card = client.get(f"/v1/agent/conversations/{blocked['conversation_id']}").json()[
        "empathy_card"
    ]
    assert card["next_state"] != "BLOCK"
    assert card["risk_level"] == "low"


def test_stale_attempt_patch_is_rejected_after_revision() -> None:
    client = make_client()
    conversation = start_guide(client)
    conversation_id = conversation["conversation_id"]
    attempt_id = conversation["current_attempt"]["attempt_id"]
    current_revision = client.get(f"/v1/conversations/{conversation_id}/case").json()[
        "current_revision"
    ]

    client.post(
        f"/v1/conversations/{conversation_id}/case/revisions",
        json={
            "facts": {},
            "unknown_fields": ["extra_note"],
            "reason": "迟到页面上的无关更正",
        },
    )

    stale = client.patch(
        f"/v1/conversations/{conversation_id}/attempts/{attempt_id}",
        json={
            "execution_status": "executed",
            "observation": "旧页面提交",
            "based_on_revision": current_revision,
        },
    )
    assert stale.status_code == 409
