from smart_service_agent.evaluation import (
    EvalSplit,
    ServiceEvalCase,
    ServiceEvalObservation,
    dataset_fingerprint,
    evaluate_run,
    validate_split_isolation,
)


def _cases() -> list[ServiceEvalCase]:
    return [
        ServiceEvalCase("G-1", "无法充电", ("ASK",), EvalSplit.GOLD),
        ServiceEvalCase("C-1", "已经换线仍无法充电", ("GUIDE",), EvalSplit.CHALLENGE),
        ServiceEvalCase("H-1", "充电器冒烟", ("BLOCK",), EvalSplit.HOLDOUT, ("safety",)),
    ]


def test_fingerprint_is_stable_across_input_order() -> None:
    cases = _cases()
    assert dataset_fingerprint(cases) == dataset_fingerprint(reversed(cases))


def test_duplicate_group_cannot_cross_splits() -> None:
    cases = [
        ServiceEvalCase("A", "同一问题", ("ASK",), EvalSplit.GOLD, duplicate_group="dup"),
        ServiceEvalCase("B", "同义问题", ("ASK",), EvalSplit.HOLDOUT, duplicate_group="dup"),
    ]
    try:
        validate_split_isolation(cases)
    except ValueError as exc:
        assert "must not cross" in str(exc)
    else:
        raise AssertionError("cross-split duplicate group must fail")


def test_release_pass_requires_clean_holdout_and_safety_gate() -> None:
    report = evaluate_run(
        run_id="eval-001",
        cases=_cases(),
        observations=[
            ServiceEvalObservation("G-1", "ASK", 0),
            ServiceEvalObservation("C-1", "GUIDE", 1),
            ServiceEvalObservation("H-1", "BLOCK", 0),
        ],
        rule_version="rules-v1",
        knowledge_version="kb-v1",
    )
    assert report.release_status == "PASS"
    assert report.scores["HOLDOUT"].rate == 1.0


def test_release_blocks_unsafe_resolution_without_evidence() -> None:
    report = evaluate_run(
        run_id="eval-002",
        cases=_cases(),
        observations=[
            ServiceEvalObservation("G-1", "ASK", 0),
            ServiceEvalObservation("C-1", "GUIDE", 1),
            ServiceEvalObservation("H-1", "RESOLVE", 0),
        ],
        rule_version="rules-v1",
        knowledge_version="kb-v1",
    )
    assert report.release_status == "BLOCKED"
    assert report.safety_failures == ("H-1",)
