"""Strict output validator for HackerRank Ghost Data Still Exists submission contract."""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import (
    ALLOWED_OPERATIONS,
    ALLOWED_PHASES,
    ALLOWED_STATUSES,
    OPERATION_RANK,
    PHASE_RANK,
    STEP_KEYS,
)


class OutputValidationError(Exception):
    """Raised when an output file or row violates the competition contract."""
    pass


StepDict = Dict[str, Any]


def validate_step_ordering(case_id: str, steps: List[Dict[str, Any]]) -> None:
    """Validate phase ordering, operation ordering within phase, and tie-breaking by (system_id, resource_id)."""
    last_phase_rank = -1
    last_op_rank = -1
    last_tie_key = ("", "")

    for idx, step in enumerate(steps, start=1):
        actual_step_no = step.get("step_no")
        if actual_step_no != idx:
            raise OutputValidationError(
                f"{case_id}: step_no must be consecutive starting at 1. Step {idx} has step_no={actual_step_no}"
            )

        phase = step.get("phase", "")
        op = step.get("operation", "")
        p_rank = PHASE_RANK.get(phase, -1)
        op_rank = OPERATION_RANK.get(op, -1)
        tie_key = (str(step.get("system_id", "")), str(step.get("resource_id", "")))

        if p_rank < last_phase_rank:
            raise OutputValidationError(
                f"{case_id}: Step {idx} phase '{phase}' appears after a later phase (rank {last_phase_rank})"
            )
        elif p_rank > last_phase_rank:
            last_phase_rank = p_rank
            last_op_rank = op_rank
            last_tie_key = tie_key
        else:
            # Same phase
            if op_rank < last_op_rank:
                raise OutputValidationError(
                    f"{case_id}: Step {idx} operation '{op}' out of order in phase '{phase}'"
                )
            elif op_rank > last_op_rank:
                last_op_rank = op_rank
                last_tie_key = tie_key
            else:
                # Same operation: sort by system_id and resource_id ascending
                if tie_key < last_tie_key:
                    raise OutputValidationError(
                        f"{case_id}: Step {idx} resource key {tie_key} must be sorted ascending after {last_tie_key}"
                    )
                last_tie_key = tie_key


def validate_steps_contract(
    case_id: str,
    status: str,
    steps: List[Dict[str, Any]],
    valid_evidence_ids: Optional[Set[str]] = None,
) -> None:
    """Validate steps_json contents according to deletion_status contract."""
    if status == "NOT_APPLICABLE":
        if steps:
            raise OutputValidationError(
                f"{case_id}: NOT_APPLICABLE cases must have steps_json=[], found {len(steps)} steps"
            )
        return

    if not steps:
        raise OutputValidationError(
            f"{case_id}: Status {status} requires steps, found empty array"
        )

    for idx, step in enumerate(steps, start=1):
        # 1. Exact keys check
        keys = tuple(step.keys())
        missing_keys = [k for k in STEP_KEYS if k not in step]
        if missing_keys:
            raise OutputValidationError(
                f"{case_id}: Step {idx} is missing required keys: {missing_keys}"
            )
        extra_keys = [k for k in step if k not in STEP_KEYS]
        if extra_keys:
            raise OutputValidationError(
                f"{case_id}: Step {idx} contains forbidden extra keys: {extra_keys}"
            )

        phase = step["phase"]
        if phase not in ALLOWED_PHASES:
            raise OutputValidationError(
                f"{case_id}: Step {idx} has invalid phase '{phase}'. Allowed: {sorted(ALLOWED_PHASES)}"
            )

        op = step["operation"]
        if op not in ALLOWED_OPERATIONS:
            raise OutputValidationError(
                f"{case_id}: Step {idx} has invalid operation '{op}'"
            )

        expected_phase, expected_state = ALLOWED_OPERATIONS[op]
        if phase != expected_phase:
            raise OutputValidationError(
                f"{case_id}: Step {idx} operation '{op}' belongs to phase '{expected_phase}', not '{phase}'"
            )

        state = step["state"]
        if state != expected_state:
            raise OutputValidationError(
                f"{case_id}: Step {idx} operation '{op}' requires state '{expected_state}', got '{state}'"
            )

        evidence_id = step.get("evidence_id", "")

        # 2. Status-specific evidence and phase constraints
        if status == "COMPLETE":
            if phase != "VERIFICATION":
                raise OutputValidationError(
                    f"{case_id}: COMPLETE case may only contain VERIFICATION steps, found '{phase}' at step {idx}"
                )
            if not evidence_id or not evidence_id.strip():
                raise OutputValidationError(
                    f"{case_id}: COMPLETE case verification step {idx} must cite evidence, got empty evidence_id"
                )
            if valid_evidence_ids and evidence_id not in valid_evidence_ids:
                raise OutputValidationError(
                    f"{case_id}: Step {idx} cites unknown evidence_id '{evidence_id}'"
                )
        elif status == "INCOMPLETE":
            if phase == "FINDING":
                if not evidence_id or not evidence_id.strip():
                    raise OutputValidationError(
                        f"{case_id}: INCOMPLETE finding step {idx} must cite evidence, got empty evidence_id"
                    )
                if valid_evidence_ids and evidence_id not in valid_evidence_ids:
                    raise OutputValidationError(
                        f"{case_id}: Step {idx} cites unknown evidence_id '{evidence_id}'"
                    )
            elif phase in ("REMEDIATION", "VERIFICATION"):
                if evidence_id != "":
                    raise OutputValidationError(
                        f"{case_id}: INCOMPLETE {phase.lower()} step {idx} must have evidence_id='', got '{evidence_id}'"
                    )

    # 3. Validate ordering
    validate_step_ordering(case_id, steps)


def validate_output_file(
    output_path: Path | str,
    expected_case_ids: Optional[List[str]] = None,
    valid_evidence_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Validate an output.csv file against all schema, syntax, and business rules.
    
    Returns parsed list of rows if valid.
    """
    path = Path(output_path)
    if not path.is_file():
        raise FileNotFoundError(f"Output file missing: {path}")

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise OutputValidationError(f"Output file {path} is empty")

        clean_header = [c.strip() for c in header]
        expected_header = ["case_id", "deletion_status", "steps_json"]
        if clean_header != expected_header:
            raise OutputValidationError(
                f"Invalid output header: expected {expected_header}, got {clean_header}"
            )

        rows = []
        seen_case_ids = []
        for line_no, row in enumerate(reader, start=2):
            if not row or all(c.strip() == "" for c in row):
                continue
            if len(row) != 3:
                raise OutputValidationError(
                    f"Line {line_no}: Expected 3 columns (case_id, deletion_status, steps_json), got {len(row)}: {row}"
                )

            cid = row[0].strip()
            status = row[1].strip()
            steps_raw = row[2].strip()

            if not cid:
                raise OutputValidationError(f"Line {line_no}: Empty case_id")
            if status not in ALLOWED_STATUSES:
                raise OutputValidationError(
                    f"Line {line_no}: Invalid status '{status}'. Allowed: {sorted(ALLOWED_STATUSES)}"
                )

            try:
                steps = json.loads(steps_raw)
            except Exception as e:
                raise OutputValidationError(
                    f"Line {line_no} ({cid}): steps_json is not valid JSON: {e}"
                ) from e

            if not isinstance(steps, list):
                raise OutputValidationError(
                    f"Line {line_no} ({cid}): steps_json must be a JSON array, got {type(steps).__name__}"
                )

            validate_steps_contract(cid, status, steps, valid_evidence_ids)

            seen_case_ids.append(cid)
            rows.append({"case_id": cid, "deletion_status": status, "steps": steps})

    # Validate sorting and uniqueness
    sorted_case_ids = sorted(seen_case_ids)
    if seen_case_ids != sorted_case_ids:
        raise OutputValidationError("Rows in output.csv must be sorted by case_id in ascending order")

    if len(seen_case_ids) != len(set(seen_case_ids)):
        duplicates = [cid for cid in seen_case_ids if seen_case_ids.count(cid) > 1]
        raise OutputValidationError(f"Duplicate case_ids in output.csv: {set(duplicates)}")

    if expected_case_ids is not None:
        if len(rows) != len(expected_case_ids):
            raise OutputValidationError(
                f"Expected exactly {len(expected_case_ids)} rows, got {len(rows)}"
            )
        if seen_case_ids != expected_case_ids:
            missing = set(expected_case_ids) - set(seen_case_ids)
            extra = set(seen_case_ids) - set(expected_case_ids)
            raise OutputValidationError(
                f"Case ID mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
            )

    return rows
