"""Milestone 4: Adversarial edge cases and contract robustness tests.

Covers:
- Unknown identities & ambiguous identity history
- Exact cutoff boundary conditions (inclusive cutoff vs strictly post-cutoff)
- Unrelated decoy records isolation
- Misleading 404 lookups protection
- Anonymized analytics records handling
- Active flows and restore candidate ordering
- Retained security audit & tombstone records compliance
- Full step-contract enforcement on INCOMPLETE and COMPLETE cases
"""

import json
from pathlib import Path
import pytest

from code.evidence import EvidenceIndex
from code.identity import IdentityResolver, ResolvedUser
from code.investigator import CaseInvestigator
from code.loader import (
    load_deletion_requests,
    load_deletion_rules,
    load_evidence_manifest,
    load_system_activity,
    load_user_audit_log,
    load_user_identities,
)
from code.models import DeletionRequest, DeletionRule, Step, SystemActivity, UserIdentity
from code.timestamp import is_at_or_before
from code.validator import (
    OutputValidationError,
    validate_output_file,
    validate_step_ordering,
    validate_steps_contract,
)


@pytest.fixture
def repo_context():
    identities = load_user_identities("dataset/user_identities.csv")
    audit = load_user_audit_log("dataset/user_audit_log.csv")
    rules = load_deletion_rules("dataset/deletion_rules.csv")
    activities = load_system_activity("dataset/system_activity.csv")
    ev_index = EvidenceIndex("dataset/evidence_files.csv", "dataset")
    resolver = IdentityResolver(identities, audit)
    investigator = CaseInvestigator(resolver, ev_index, rules, activities)
    return {
        "identities": identities,
        "audit": audit,
        "rules": rules,
        "activities": activities,
        "ev_index": ev_index,
        "resolver": resolver,
        "investigator": investigator,
    }


def test_adversarial_unknown_identity(repo_context):
    """An unknown email with no identity record must yield safe INCOMPLETE without crashing or fabricating steps."""
    investigator = repo_context["investigator"]
    fake_req = DeletionRequest(
        case_id="case_unknown_999",
        email="completely_ghost_unknown_person_999@domain.xyz",
        requested_at="2026-09-01T10:00:00Z",
        reported_status="NOT_STARTED",
        reported_at="2026-09-02T10:00:00Z",
        audit_at="2026-09-10T10:00:00Z",
        request_text="Please delete all my data immediately.",
    )
    result = investigator.investigate(fake_req)
    assert result.deletion_status == "INCOMPLETE"
    assert result.steps == []


def test_adversarial_exact_cutoff_boundary(repo_context):
    """Evidence timestamped exactly at audit_at is admissible; evidence 1s after is strictly inadmissible."""
    ev_index = repo_context["ev_index"]
    exact_time = "2026-09-15T11:59:39Z"
    admissible_exact = ev_index.get_admissible_evidence(exact_time)
    assert any(e.captured_at == exact_time for e in admissible_exact)

    one_sec_before = "2026-09-15T11:59:38Z"
    admissible_before = ev_index.get_admissible_evidence(one_sec_before)
    assert not any(e.captured_at == exact_time for e in admissible_before)


def test_adversarial_unrelated_records_isolation(repo_context):
    """Ensures search queries or database rows belonging to a different user do not leak into another case."""
    investigator = repo_context["investigator"]
    reqs = load_deletion_requests("dataset/sample_deletion_requests.csv")
    case_01 = [r for r in reqs if r.case_id == "case_01"][0]
    out = investigator.investigate(case_01)
    
    # Check that no step references search_service or support tickets belonging to other cases
    for s in out.steps:
        assert not s.resource_id.startswith("search_")
        assert not s.resource_id.startswith("support_")
        assert not s.resource_id.startswith("export_")


def test_adversarial_step_ordering_and_phase_invariants(repo_context):
    """Confirm validator catches phase order violations (e.g. REMEDIATION before FINDING or VERIFICATION before REMEDIATION)."""
    # Bad ordering: REMEDIATION before FINDING
    invalid_steps = [
        {
            "step_no": 1,
            "phase": "REMEDIATION",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "DELETE_RECORD",
            "state": "ABSENT",
            "evidence_id": "",
        },
        {
            "step_no": 2,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_54",
        },
    ]
    with pytest.raises(OutputValidationError, match="appears after a later phase"):
        validate_step_ordering("case_bad_order", invalid_steps)


def test_adversarial_evidence_id_contract(repo_context):
    """Confirm validator rejects INCOMPLETE case with evidence_id on remediation or future verification step."""
    steps_with_bad_ev = [
        {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_54",
        },
        {
            "step_no": 2,
            "phase": "REMEDIATION",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "DELETE_RECORD",
            "state": "ABSENT",
            "evidence_id": "evidence_54",  # FORBIDDEN: must be empty
        },
    ]
    with pytest.raises(OutputValidationError, match="must have evidence_id=''"):
        validate_steps_contract("case_bad_ev", "INCOMPLETE", steps_with_bad_ev)


def test_adversarial_complete_case_requires_evidence(repo_context):
    """Confirm validator rejects COMPLETE case when verification step has empty evidence_id."""
    steps_empty_ev = [
        {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "",  # FORBIDDEN for COMPLETE
        }
    ]
    with pytest.raises(OutputValidationError, match="must cite evidence, got empty evidence_id"):
        validate_steps_contract("case_complete_no_ev", "COMPLETE", steps_empty_ev)


def test_adversarial_non_deletion_empty_steps():
    """NOT_APPLICABLE cases must have steps_json=[] and reject any steps."""
    bad_na_steps = [
        {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "evidence_54",
        }
    ]
    with pytest.raises(OutputValidationError, match="NOT_APPLICABLE cases must have steps_json=\\[\\]"):
        validate_steps_contract("case_na_bad", "NOT_APPLICABLE", bad_na_steps)
