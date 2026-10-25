"""Milestone 3 regression tests: Trace correlation, step envelope scoping, and status resolution."""

import pytest
from code.loader import (
    load_deletion_requests,
    load_user_identities,
    load_user_audit_log,
    load_deletion_rules,
    load_system_activity,
)
from code.identity import IdentityResolver
from code.evidence import EvidenceIndex
from code.investigator import CaseInvestigator


@pytest.fixture(scope="module")
def investigator():
    requests = load_deletion_requests("dataset/sample_deletion_requests.csv")
    identities = load_user_identities("dataset/user_identities.csv")
    audit_log = load_user_audit_log("dataset/user_audit_log.csv")
    rules = load_deletion_rules("dataset/deletion_rules.csv")
    activities = load_system_activity("dataset/system_activity.csv")

    resolver = IdentityResolver(identities, audit_log)
    evidence_index = EvidenceIndex("dataset/evidence_files.csv", "dataset")

    return CaseInvestigator(
        resolver=resolver,
        evidence_index=evidence_index,
        rules=rules,
        activities=activities,
    )


def test_m3_case_10_distributed_trace_correlation(investigator):
    """Case 10: Trace correlation in support_replica.log must identify remaining record support_002."""
    requests = {r.case_id: r for r in load_deletion_requests("dataset/sample_deletion_requests.csv")}
    req = requests["case_10"]

    row = investigator.investigate(req)
    assert row.deletion_status == "INCOMPLETE", "Case 10 must be detected as INCOMPLETE due to surviving support ticket"
    
    finding_ops = [(s.system_id, s.resource_id, s.operation, s.evidence_id) for s in row.steps if s.phase == "FINDING"]
    assert ("support_platform", "support_002", "REPORT_REMAINING_RECORD", "evidence_61") in finding_ops


def test_m3_case_15_active_connector_trace(investigator):
    """Case 15: Distributed trace in service_events log must detect active connector data_flow_9846."""
    requests = {r.case_id: r for r in load_deletion_requests("dataset/sample_deletion_requests.csv")}
    req = requests["case_15"]

    row = investigator.investigate(req)
    assert row.deletion_status == "INCOMPLETE", "Case 15 must be detected as INCOMPLETE due to active connector"

    finding_ops = [(s.system_id, s.resource_id, s.operation, s.evidence_id) for s in row.steps if s.phase == "FINDING"]
    assert ("integration_service", "data_flow_9846", "REPORT_ACTIVE_DATA_FLOW", "evidence_01") in finding_ops


def test_m3_case_17_restore_candidate_risk(investigator):
    """Case 17: Restore candidate evaluated without deletion block must be detected as restore risk."""
    requests = {r.case_id: r for r in load_deletion_requests("dataset/sample_deletion_requests.csv")}
    req = requests["case_17"]

    row = investigator.investigate(req)
    assert row.deletion_status == "INCOMPLETE", "Case 17 must be detected as INCOMPLETE due to restore risk"

    finding_ops = [(s.system_id, s.resource_id, s.operation, s.evidence_id) for s in row.steps if s.phase == "FINDING"]
    assert ("backup_service", "backup_3245", "REPORT_RESTORE_RISK", "evidence_01") in finding_ops


def test_m3_step_envelope_scoping_no_alien_404_lookups(investigator):
    """Step scoping: 404 lookups for other accounts must not be added to unrelated cases."""
    requests = {r.case_id: r for r in load_deletion_requests("dataset/sample_deletion_requests.csv")}
    req_01 = requests["case_01"]

    row = investigator.investigate(req_01)
    # case_01 is account_001. It must NOT contain account_3136, account_3866, account_5482, etc.
    res_ids = [s.resource_id for s in row.steps]
    assert "account_3136" not in res_ids
    assert "account_3866" not in res_ids
    assert "account_5482" not in res_ids
    assert "account_5684" not in res_ids
    assert "account_6440" not in res_ids
    assert "account_6813" not in res_ids
    assert "analytics_901" not in res_ids
    assert res_ids == ["account_001"]
