from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from smart_service_agent.config import get_settings
from smart_service_agent.evaluation import (
    EvalSplit,
    ServiceEvalCase,
    ServiceEvalObservation,
    evaluate_run,
)
from smart_service_agent.main import create_app
from smart_service_agent.repository import MemoryRepository


def load_cases(path: Path) -> list[ServiceEvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        ServiceEvalCase(
            case_id=row["case_id"],
            message=row["message"],
            expected_states=tuple(row["expected_states"]),
            split=EvalSplit(row["split"]),
            tags=tuple(row.get("tags", [])),
            product=row.get("product"),
            duplicate_group=row.get("duplicate_group"),
        )
        for row in payload
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic service evaluation gate")
    parser.add_argument("--cases", type=Path, default=Path("data/eval/demo_cases.json"))
    parser.add_argument("--run-id", default="local-demo-eval")
    args = parser.parse_args()

    settings = get_settings()
    client = TestClient(create_app(MemoryRepository()))
    cases = load_cases(args.cases)
    observations = []
    for case in cases:
        body = {"message": case.message}
        if case.product:
            body["product"] = case.product
        response = client.post("/v1/conversations", json=body).json()
        observations.append(
            ServiceEvalObservation(
                case_id=case.case_id,
                actual_state=response["state"],
                evidence_count=len(response.get("evidence", [])),
            )
        )
    report = evaluate_run(
        run_id=args.run_id,
        cases=cases,
        observations=observations,
        rule_version=settings.rule_version,
        knowledge_version=settings.knowledge_version,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.release_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
