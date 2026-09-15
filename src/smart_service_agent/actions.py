from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from smart_service_agent.models import AttemptRecord


@dataclass(frozen=True, slots=True)
class AllowedAction:
    action_id: str
    knowledge_id: str
    recommendation: str
    purpose: str
    instructions: str
    observation_target: str
    exit_condition: str
    depends_on_facts: tuple[str, ...]
    order: int


CHARGING_ACTIONS: tuple[AllowedAction, ...] = (
    AllowedAction(
        action_id="swap_known_good_cable",
        knowledge_id="KB-CHARGING-001",
        recommendation="更换已确认正常且参数匹配的充电线后重试",
        purpose="只调整线材这一个条件，排除线材接触或规格问题",
        instructions=(
            "保持原充电器和原设备不变，只更换为已确认正常且功率/协议匹配的充电线，"
            "观察是否开始稳定充电。"
        ),
        observation_target="更换线材后设备是否开始稳定充电，以及是否出现发热、异味、冒烟或鼓包",
        exit_condition="出现异常发热、异味、冒烟或鼓包时立即停止；无改善则进入下一步",
        depends_on_facts=("symptom", "tried_methods", "power_indicator", "product"),
        order=1,
    ),
    AllowedAction(
        action_id="retry_direct_wall_adapter",
        knowledge_id="KB-CHARGING-001",
        recommendation="改用原装或已知正常的墙插适配器直连，不经过延长线或扩展坞",
        purpose="只调整供电路径这一个条件，排除中间转接问题",
        instructions=("保持设备和线材不变，改为直接连接墙插适配器，不要经过插排、车充或扩展坞。"),
        observation_target="直连墙插后是否开始稳定充电，以及是否出现发热、异味、冒烟或鼓包",
        exit_condition="出现安全异常立即停止；仍无改善则转人工",
        depends_on_facts=("symptom", "tried_methods", "power_indicator", "product"),
        order=2,
    ),
)


def get_action(action_id: str) -> AllowedAction | None:
    return next((item for item in CHARGING_ACTIONS if item.action_id == action_id), None)


def actions_for_knowledge(knowledge_ids: Iterable[str]) -> tuple[AllowedAction, ...]:
    allowed = set(knowledge_ids)
    return tuple(item for item in CHARGING_ACTIONS if item.knowledge_id in allowed)


def used_action_ids(attempts: Iterable[AttemptRecord]) -> set[str]:
    return {
        item.action_id
        for item in attempts
        if item.action_id and item.execution_status in {"proposed", "executed", "skipped"}
    }


def next_unused_action(
    attempts: Iterable[AttemptRecord], knowledge_ids: Iterable[str]
) -> AllowedAction | None:
    used = used_action_ids(attempts)
    for item in actions_for_knowledge(knowledge_ids):
        if item.action_id not in used:
            return item
    return None
