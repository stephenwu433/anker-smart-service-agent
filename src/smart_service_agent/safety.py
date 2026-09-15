from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from smart_service_agent.models import SafetyHold

HIGH_RISK_TERMS = ("冒烟", "异味", "起火", "漏液", "鼓包", "异常发热")
HYPOTHETICAL_PREFIXES = ("会不会", "是否会", "会否", "怕", "担心")
RESOLVED_TERMS = ("已经好了", "已恢复", "现在好了", "已消退")
RENEWED_RISK_TERMS = ("但是", "但", "不过", "又", "仍", "现在还")
SafetyMode = Literal["message", "revision", "observation", "feedback"]


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    blocked: bool
    terms: tuple[str, ...]
    hold: SafetyHold
    cleared: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_explicit_resolution(text: str) -> bool:
    return any(term in text for term in RESOLVED_TERMS) and not any(
        term in text for term in RENEWED_RISK_TERMS
    )


def detect_risk_terms(text: str) -> list[str]:
    if is_explicit_resolution(text):
        return []
    found: list[str] = []
    for term in HIGH_RISK_TERMS:
        index = text.find(term)
        if index < 0:
            continue
        prefix = text[max(0, index - 8) : index]
        negated = re.search(
            r"(?:没有|没|不|未|无)(?:闻到|出现|发生|发现|感到|检测到)?$",
            prefix,
        )
        hypothetical = any(prefix.endswith(marker) for marker in HYPOTHETICAL_PREFIXES)
        if negated or hypothetical:
            continue
        context = text[max(0, index - 12) : index]
        third_party = re.search(
            r"(?:朋友|同事|家人)(?:说|有|出现|使用后|用了以后)?[^，。！？]*$"
            r"|(?:^|[，。！？])(?:他|她)(?:说|有|出现|使用后|用了以后)[^，。！？]*$",
            context,
        )
        if third_party:
            continue
        found.append(term)
    return found


def evaluate_safety(
    text: str,
    *,
    hold: SafetyHold | None,
    source: str,
    mode: SafetyMode,
) -> SafetyDecision:
    terms = detect_risk_terms(text)
    current = hold.model_copy(deep=True) if hold is not None else SafetyHold()
    now = utc_now()
    if terms:
        merged_terms = list(dict.fromkeys([*current.terms, *terms]))
        updated = SafetyHold(
            active=True,
            reasons=[f"命中设备安全风险词：{term}" for term in merged_terms],
            source=source,
            terms=merged_terms,
            updated_at=now,
        )
        return SafetyDecision(blocked=True, terms=tuple(terms), hold=updated, cleared=False)
    if current.active:
        if mode == "feedback":
            return SafetyDecision(
                blocked=True, terms=tuple(current.terms), hold=current, cleared=False
            )
        can_clear = mode in {"message", "observation"} and is_explicit_resolution(text)
        if mode == "revision" or can_clear:
            cleared = SafetyHold(active=False, source=source, updated_at=now)
            return SafetyDecision(blocked=False, terms=(), hold=cleared, cleared=True)
        return SafetyDecision(blocked=True, terms=tuple(current.terms), hold=current, cleared=False)
    return SafetyDecision(blocked=False, terms=(), hold=current, cleared=False)
