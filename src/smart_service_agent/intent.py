from __future__ import annotations

from typing import Optional, Protocol

from smart_service_agent.models import Intent, IntentResult


class IntentProvider(Protocol):
    """Replaceable intent-classification boundary for an LLM or other provider."""

    def classify(self, text: str) -> IntentResult: ...


class RuleBasedIntentProvider:
    """Deterministic fallback that remains available without external services."""

    def classify(self, text: str) -> IntentResult:
        if any(term in text for term in ("订单", "退款", "退货", "换货", "售后")):
            return IntentResult(intent=Intent.AFTER_SALES, confidence=0.9, source="rules")
        if any(term in text for term in ("投诉", "骗人", "假货", "服务态度")):
            return IntentResult(intent=Intent.COMPLAINT, confidence=0.9, source="rules")
        if any(term in text for term in ("购买", "型号", "充电器", "功率", "协议", "适合买吗")):
            return IntentResult(intent=Intent.PURCHASE, confidence=0.85, source="rules")
        if any(term in text for term in ("使用", "怎么用", "第一次", "首次", "用法")):
            return IntentResult(intent=Intent.USAGE, confidence=0.9, source="rules")
        return IntentResult(intent=Intent.CONSULT, confidence=0.6, source="rules")


class FallbackIntentProvider:
    """Use a primary provider only when it returns a sufficiently confident result."""

    def __init__(
        self,
        primary: Optional[IntentProvider],
        fallback: IntentProvider,
        minimum_confidence: float,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.minimum_confidence = minimum_confidence

    def classify(self, text: str) -> IntentResult:
        if self.primary is not None:
            try:
                result = self.primary.classify(text)
                validated = IntentResult.model_validate(result)
                if validated.confidence >= self.minimum_confidence:
                    return validated
            except Exception:
                # Provider errors are intentionally contained at this trust boundary.
                pass
        return self.fallback.classify(text)
