from fastapi.testclient import TestClient

from smart_service_agent.main import create_app
from smart_service_agent.repository import MemoryRepository
from smart_service_agent.safety import detect_risk_terms, evaluate_safety, is_explicit_resolution


def make_client() -> TestClient:
    return TestClient(create_app(MemoryRepository()))


def test_detect_risk_ignores_negation_and_third_party() -> None:
    assert detect_risk_terms("我没有异味，只想问怎么用") == []
    assert detect_risk_terms("我朋友的充电器鼓包") == []
    assert "冒烟" in detect_risk_terms("充电器冒烟")


def test_explicit_resolution_does_not_clear_renewed_risk() -> None:
    assert is_explicit_resolution("已经好了")
    assert not is_explicit_resolution("已经好了，但现在又有异味")


def test_evaluate_safety_latches_until_explicit_resolution() -> None:
    first = evaluate_safety("无法充电而且鼓包", hold=None, source="message", mode="message")
    assert first.blocked
    stuck = evaluate_safety("我想继续使用", hold=first.hold, source="message", mode="message")
    assert stuck.blocked
    cleared = evaluate_safety("已经好了", hold=stuck.hold, source="message", mode="message")
    assert not cleared.blocked
    assert cleared.cleared


def test_bulge_then_continue_use_stays_blocked() -> None:
    client = make_client()
    first = client.post("/v1/conversations", json={"message": "无法充电而且鼓包"}).json()
    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "我想继续使用"},
    ).json()

    assert first["state"] == "BLOCK"
    assert second["state"] == "BLOCK"
    assert second["current_attempt"] is None
    assert "尚未解除" in second["message"]
