"""Public sample replay and diff harness.

Compares candidate audit outputs against expected outputs (e.g. sample_output.csv)
with step-level, field-level, and sequence diffing.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StepMismatch:
    step_no: int
    field_name: str
    expected_val: Any
    actual_val: Any


@dataclass
class CaseComparisonResult:
    case_id: str
    status_match: bool
    expected_status: str
    actual_status: str
    step_count_expected: int
    step_count_actual: int
    step_mismatches: List[StepMismatch] = field(default_factory=list)
    explanation: str = ""

    @property
    def is_exact_match(self) -> bool:
        return (
            self.status_match
            and self.step_count_expected == self.step_count_actual
            and len(self.step_mismatches) == 0
        )


@dataclass
class ReplayReport:
    total_cases: int
    status_matches: int
    exact_matches: int
    results: List[CaseComparisonResult]

    @property
    def status_accuracy(self) -> float:
        return self.status_matches / self.total_cases if self.total_cases else 0.0

    @property
    def exact_match_accuracy(self) -> float:
        return self.exact_matches / self.total_cases if self.total_cases else 0.0


def compare_case_output(
    case_id: str,
    expected_status: str,
    expected_steps: List[Dict[str, Any]],
    actual_status: str,
    actual_steps: List[Dict[str, Any]],
) -> CaseComparisonResult:
    """Compare a single case prediction against expected answer."""
    status_match = expected_status == actual_status
    mismatches: List[StepMismatch] = []
    explanations: List[str] = []

    if not status_match:
        explanations.append(
            f"Status mismatch: expected '{expected_status}', got '{actual_status}'"
        )

    exp_len = len(expected_steps)
    act_len = len(actual_steps)
    if exp_len != act_len:
        explanations.append(f"Step count mismatch: expected {exp_len}, got {act_len}")

    compare_len = min(exp_len, act_len)
    fields_to_check = [
        "step_no",
        "phase",
        "system_id",
        "resource_id",
        "operation",
        "state",
        "evidence_id",
    ]

    for idx in range(compare_len):
        e_step = expected_steps[idx]
        a_step = actual_steps[idx]
        for fld in fields_to_check:
            e_val = e_step.get(fld)
            a_val = a_step.get(fld)
            if e_val != a_val:
                mismatches.append(
                    StepMismatch(
                        step_no=idx + 1,
                        field_name=fld,
                        expected_val=e_val,
                        actual_val=a_val,
                    )
                )

    if mismatches:
        explanations.append(f"{len(mismatches)} field mismatches across {compare_len} steps")

    return CaseComparisonResult(
        case_id=case_id,
        status_match=status_match,
        expected_status=expected_status,
        actual_status=actual_status,
        step_count_expected=exp_len,
        step_count_actual=act_len,
        step_mismatches=mismatches,
        explanation="; ".join(explanations) if explanations else "Exact match",
    )


def replay_samples(
    expected_rows: List[Dict[str, Any]],
    actual_rows: List[Dict[str, Any]],
) -> ReplayReport:
    """Compare two lists of validated rows (case_id, deletion_status, steps)."""
    actual_by_id = {r["case_id"]: r for r in actual_rows}
    results: List[CaseComparisonResult] = []

    status_matches = 0
    exact_matches = 0

    for exp in expected_rows:
        cid = exp["case_id"]
        act = actual_by_id.get(cid)
        if act is None:
            res = CaseComparisonResult(
                case_id=cid,
                status_match=False,
                expected_status=exp["deletion_status"],
                actual_status="MISSING",
                step_count_expected=len(exp.get("steps", [])),
                step_count_actual=0,
                explanation="Case missing from candidate output",
            )
        else:
            res = compare_case_output(
                case_id=cid,
                expected_status=exp["deletion_status"],
                expected_steps=exp.get("steps", []),
                actual_status=act["deletion_status"],
                actual_steps=act.get("steps", []),
            )

        if res.status_match:
            status_matches += 1
        if res.is_exact_match:
            exact_matches += 1
        results.append(res)

    return ReplayReport(
        total_cases=len(expected_rows),
        status_matches=status_matches,
        exact_matches=exact_matches,
        results=results,
    )
