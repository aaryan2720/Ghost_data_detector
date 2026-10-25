"""Milestone 2 regression tests for Ghost Data Still Exists.

Verifies:
1. Generation path never reads sample_output.csv (generation independence).
2. 8 Vertical Slices:
   - Slice 1: Genuinely complete case.
   - Slice 2: Surviving primary or replica record.
   - Slice 3: Historical email resolution and evidence matching.
   - Slice 4: Active data flow detection and remediation plan.
   - Slice 5: Restore risk detection and remediation plan.
   - Slice 6: Retained record requiring redaction/anonymization (account tombstone).
   - Slice 7: Non-deletion request (NOT_APPLICABLE with steps=[]).
   - Slice 8: Ambiguous identity / insufficient evidence safe failure.
"""

from pathlib import Path
import unittest.mock as mock
import pytest

from code.classifier import classify_request
from code.evidence import EvidenceIndex
from code.identity import IdentityResolver
from code.investigator import CaseInvestigator
from code.loader import (
    load_deletion_requests,
    load_deletion_rules,
    load_system_activity,
    load_user_audit_log,
    load_user_identities,
)
from code.models import DeletionRequest


@pytest.fixture(scope="module")
def context():
    identities = load_user_identities("dataset/user_identities.csv")
    audit = load_user_audit_log("dataset/user_audit_log.csv")
    rules = load_deletion_rules("dataset/deletion_rules.csv")
    activities = load_system_activity("dataset/system_activity.csv")
    ev_index = EvidenceIndex("dataset/evidence_files.csv", "dataset")
    resolver = IdentityResolver(identities, audit)
    investigator = CaseInvestigator(resolver, ev_index, rules, activities)
    requests = {r.case_id: r for r in load_deletion_requests("dataset/sample_deletion_requests.csv")}
    return {
        "investigator": investigator,
        "requests": requests,
        "resolver": resolver,
    }


def test_generation_does_not_read_sample_output(context):
    """Prove that CaseInvestigator runs and generates results without reading sample_output.csv."""
    investigator = context["investigator"]
    req = context["requests"]["case_01"]

    orig_open = open

    def guarded_open(file, *args, **kwargs):
        filepath = str(file)
        if "sample_output.csv" in filepath:
            raise PermissionError("CaseInvestigator attempted to read sample_output.csv!")
        return orig_open(file, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=guarded_open):
        result = investigator.investigate(req)

    assert result.case_id == "case_01"
    assert result.deletion_status == "COMPLETE"
    assert len(result.steps) >= 1


def test_slice_1_genuinely_complete_case(context):
    """Slice 1: A genuinely complete case (case_01).
    
    Verified state: primary account absent in failover replica evidence_54.
    Final status: COMPLETE with evidence-backed verification steps only.
    """
    investigator = context["investigator"]
    req = context["requests"]["case_01"]
    result = investigator.investigate(req)

    assert result.deletion_status == "COMPLETE"
    # Complete case must have NO finding or remediation steps
    assert all(s.phase == "VERIFICATION" for s in result.steps)
    # Verification steps must cite admissible evidence
    assert all(s.evidence_id != "" for s in result.steps)
    assert any(s.system_id == "account_service" and s.operation == "VERIFY_RECORD_ABSENT" for s in result.steps)


def test_slice_2_surviving_replica_record(context):
    """Slice 2: A surviving replica record (case_05).
    
    Evidence facts: customer account is still present in failover replica (evidence_54).
    Policy decision: DELETE rule applies.
    Steps: FINDING -> REMEDIATION -> VERIFICATION.
    Final status: INCOMPLETE.
    """
    investigator = context["investigator"]
    req = context["requests"]["case_05"]
    result = investigator.investigate(req)

    assert result.deletion_status == "INCOMPLETE"
    finding = next((s for s in result.steps if s.phase == "FINDING" and s.system_id == "account_service"), None)
    assert finding is not None
    assert finding.operation == "REPORT_REMAINING_RECORD"
    assert finding.state == "PRESENT"
    assert finding.evidence_id == "evidence_54"

    remediation = next((s for s in result.steps if s.phase == "REMEDIATION" and s.system_id == "account_service"), None)
    assert remediation is not None
    assert remediation.operation == "DELETE_RECORD"
    assert remediation.state == "ABSENT"
    assert remediation.evidence_id == ""  # Future remediation must have empty evidence_id

    verification = next((s for s in result.steps if s.phase == "VERIFICATION" and s.system_id == "account_service"), None)
    assert verification is not None
    assert verification.operation == "VERIFY_RECORD_ABSENT"
    assert verification.state == "ABSENT"
    assert verification.evidence_id == ""  # Future verification must have empty evidence_id


def test_slice_3_historical_email_resolution(context):
    """Slice 3: Case requesting deletion with a historical email or hash (case_12).
    
    Identities: minjun.kim@gmail.com matches historical email hash 44a65154...
    Evidence: analytics platform lookup in evidence_01 matched that historical hash.
    Final status: INCOMPLETE with finding citing evidence_01.
    """
    investigator = context["investigator"]
    req = context["requests"]["case_12"]
    result = investigator.investigate(req)

    assert result.deletion_status == "INCOMPLETE"
    finding = next((s for s in result.steps if s.phase == "FINDING" and s.system_id == "analytics_platform"), None)
    assert finding is not None
    assert finding.evidence_id == "evidence_01"


def test_slice_4_active_data_flow(context):
    """Slice 4: An active data flow (case_20).
    
    Evidence facts: connector data_flow_1770 is active (enabled=true in evidence_94).
    Policy decision: DISABLE_DATA_FLOW required before record modifications.
    Steps: FINDING (REPORT_ACTIVE_DATA_FLOW) -> REMEDIATION (DISABLE_DATA_FLOW).
    Final status: INCOMPLETE.
    """
    investigator = context["investigator"]
    req = context["requests"]["case_20"]
    result = investigator.investigate(req)

    assert result.deletion_status == "INCOMPLETE"
    finding = next((s for s in result.steps if s.phase == "FINDING" and s.system_id == "integration_service"), None)
    assert finding is not None
    assert finding.operation == "REPORT_ACTIVE_DATA_FLOW"
    assert finding.state == "ACTIVE"

    remediation = next((s for s in result.steps if s.phase == "REMEDIATION" and s.system_id == "integration_service"), None)
    assert remediation is not None
    assert remediation.operation == "DISABLE_DATA_FLOW"
    assert remediation.state == "DISABLED"


def test_slice_5_restore_risk(context):
    """Slice 5: A restore risk (case_09).
    
    Evidence facts: backup archive backup_009 has restore enabled in SQL dump (evidence_93).
    Policy decision: BLOCK_RESTORE required.
    Steps: FINDING (REPORT_RESTORE_RISK) -> REMEDIATION (BLOCK_RESTORE) -> VERIFICATION.
    Final status: INCOMPLETE.
    """
    investigator = context["investigator"]
    req = context["requests"]["case_09"]
    result = investigator.investigate(req)

    assert result.deletion_status == "INCOMPLETE"
    finding = next((s for s in result.steps if s.phase == "FINDING" and s.system_id == "backup_service"), None)
    assert finding is not None
    assert finding.operation == "REPORT_RESTORE_RISK"
    assert finding.state == "ACTIVE"

    remediation = next((s for s in result.steps if s.phase == "REMEDIATION" and s.system_id == "backup_service"), None)
    assert remediation is not None
    assert remediation.operation == "BLOCK_RESTORE"
    assert remediation.state == "BLOCKED"


def test_slice_6_tombstone_redaction_and_exposed_pii(context):
    """Slice 6: Retained record requiring redaction (case_31 complete vs case_32 incomplete).
    
    case_31: tombstone_440 has null direct identifiers -> VERIFY_RECORD_REDACTED.
    case_32: tombstone_9178 has exposed name, email, phone -> REPORT_EXPOSED_PII.
    """
    investigator = context["investigator"]
    # Case 31: compliant redacted tombstone
    req_31 = context["requests"]["case_31"]
    res_31 = investigator.investigate(req_31)
    assert res_31.deletion_status == "COMPLETE"
    tomb_31 = next((s for s in res_31.steps if s.system_id == "identity_service"), None)
    assert tomb_31 is not None
    assert tomb_31.operation == "VERIFY_RECORD_REDACTED"
    assert tomb_31.state == "REDACTED"

    # Case 32: unredacted tombstone with exposed direct identifiers
    req_32 = context["requests"]["case_32"]
    res_32 = investigator.investigate(req_32)
    assert res_32.deletion_status == "INCOMPLETE"
    tomb_32 = next((s for s in res_32.steps if s.phase == "FINDING" and s.system_id == "identity_service"), None)
    assert tomb_32 is not None
    assert tomb_32.operation == "REPORT_EXPOSED_PII"
    assert tomb_32.state == "PRESENT"


def test_slice_7_non_deletion_request(context):
    """Slice 7: A clearly non-deletion request (access, export, invoice copy, or keep account).
    
    Final status: NOT_APPLICABLE with steps=[].
    """
    investigator = context["investigator"]

    non_del_reqs = [
        # Data export request
        DeletionRequest(
            case_id="synth_non_del_01",
            email="test.user@gmail.com",
            requested_at="2026-08-01T10:00:00Z",
            reported_status="NOT_STARTED",
            reported_at="2026-08-01T10:00:00Z",
            audit_at="2026-08-01T12:00:00Z",
            request_text="I want to download my account information in a portable format. Please keep the account as it is.",
        ),
        # Invoice copy request
        DeletionRequest(
            case_id="synth_non_del_02",
            email="test.user@gmail.com",
            requested_at="2026-08-01T10:00:00Z",
            reported_status="NOT_STARTED",
            reported_at="2026-08-01T10:00:00Z",
            audit_at="2026-08-01T12:00:00Z",
            request_text="Could you please send me a copy of my invoices for my records? Do not delete or close my account.",
        ),
        # French keep account request
        DeletionRequest(
            case_id="synth_non_del_03",
            email="test.user@gmail.com",
            requested_at="2026-08-01T10:00:00Z",
            reported_status="NOT_STARTED",
            reported_at="2026-08-01T10:00:00Z",
            audit_at="2026-08-01T12:00:00Z",
            request_text="Veuillez exporter mes données personnelles mais garder le compte actif, ne supprimez pas mon profil.",
        ),
    ]

    for req in non_del_reqs:
        result = investigator.investigate(req)
        assert result.deletion_status == "NOT_APPLICABLE"
        assert result.steps == []


def test_slice_8_ambiguous_identity_safe_failure(context):
    """Slice 8: Ambiguous identity or insufficient evidence fails safely without fabricating facts."""
    investigator = context["investigator"]

    unknown_req = DeletionRequest(
        case_id="synth_unknown_01",
        email="completely.unknown.phantom@nowhere.com",
        requested_at="2026-08-01T10:00:00Z",
        reported_status="NOT_STARTED",
        reported_at="2026-08-01T10:00:00Z",
        audit_at="2026-08-01T12:00:00Z",
        request_text="Please delete all data associated with this address immediately.",
    )

    result = investigator.investigate(unknown_req)
    # Fails safely to INCOMPLETE with empty steps rather than inventing findings
    assert result.deletion_status == "INCOMPLETE"
    assert result.steps == []
