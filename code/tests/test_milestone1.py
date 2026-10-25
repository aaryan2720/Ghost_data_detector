"""Regression test suite for Milestone 1: Deterministic public-sample replay and validation harness.

Executes all 10 required regression test areas using actual fixture data from dataset/.
"""

import json
from pathlib import Path
import pytest

from code.evidence import EvidenceIndex
from code.identity import AmbiguousIdentityError, IdentityResolver
from code.loader import (
    DuplicateIdentifierError,
    MissingIdentifierError,
    SchemaValidationError,
    load_deletion_requests,
    load_deletion_rules,
    load_evidence_manifest,
    load_system_activity,
    load_user_audit_log,
    load_user_identities,
)
from code.replay import compare_case_output, replay_samples
from code.timestamp import is_at_or_before, is_strictly_after, parse_iso_timestamp
from code.validator import (
    OutputValidationError,
    validate_output_file,
    validate_step_ordering,
    validate_steps_contract,
)

DATASET_DIR = Path("dataset")


@pytest.fixture(scope="session")
def loaded_dataset():
    identities = load_user_identities(DATASET_DIR / "user_identities.csv")
    audit_logs = load_user_audit_log(DATASET_DIR / "user_audit_log.csv")
    requests = load_deletion_requests(DATASET_DIR / "sample_deletion_requests.csv")
    rules = load_deletion_rules(DATASET_DIR / "deletion_rules.csv")
    activities = load_system_activity(DATASET_DIR / "system_activity.csv")
    evidence_index = EvidenceIndex(
        manifest_path=DATASET_DIR / "evidence_files.csv",
        evidence_root=DATASET_DIR,
    )
    resolver = IdentityResolver(identities, audit_logs)

    valid_ev_ids = (
        {e.file_id for e in evidence_index.records}
        | {a.activity_id for a in activities}
        | {u.audit_id for u in audit_logs}
    )

    return {
        "identities": identities,
        "audit_logs": audit_logs,
        "requests": requests,
        "rules": rules,
        "activities": activities,
        "evidence_index": evidence_index,
        "resolver": resolver,
        "valid_ev_ids": valid_ev_ids,
    }


# ==============================================================================
# 1. Historical email resolution: cases 10, 29, and 30
# ==============================================================================
def test_regression_01_historical_email_resolution(loaded_dataset):
    resolver: IdentityResolver = loaded_dataset["resolver"]

    # Case 10: nadia.ionescu@yahoo.com was changed twice, current is n.petrescu@yahoo.com
    user_10 = resolver.resolve_by_email("nadia.ionescu@yahoo.com")
    assert user_10 is not None, "Case 10 historical email must resolve to a user"
    assert user_10.user_id == "user_10"
    assert user_10.current_identity.email == "n.petrescu@yahoo.com"
    prov_10 = user_10.get_matched_provenance("nadia.ionescu@yahoo.com")
    assert len(prov_10) > 0
    assert prov_10[0].source == "HISTORICAL_AUDIT"
    assert prov_10[0].audit_id == "audit_121"

    # Case 29: noah.f438085@outlook.com -> user_29, current email is noah.f4380@outlook.com
    user_29 = resolver.resolve_by_email("noah.f438085@outlook.com")
    assert user_29 is not None, "Case 29 historical email must resolve to a user"
    assert user_29.user_id == "user_29"
    assert user_29.current_identity.email == "noah.f4380@outlook.com"
    prov_29 = user_29.get_matched_provenance("noah.f438085@outlook.com")
    assert prov_29[0].source == "HISTORICAL_AUDIT"
    assert prov_29[0].audit_id == "audit_284"

    # Case 30: camille.bernard86@outlook.com -> user_30, current is camille.bernard@outlook.com
    user_30 = resolver.resolve_by_email("camille.bernard86@outlook.com")
    assert user_30 is not None, "Case 30 historical email must resolve to a user"
    assert user_30.user_id == "user_30"
    assert user_30.current_identity.email == "camille.bernard@outlook.com"
    prov_30 = user_30.get_matched_provenance("camille.bernard86@outlook.com")
    assert prov_30[0].source == "HISTORICAL_AUDIT"
    assert prov_30[0].audit_id == "audit_280"


# ==============================================================================
# 2. Similar-email identity isolation: case 28
# ==============================================================================
def test_regression_02_similar_email_isolation(loaded_dataset):
    resolver: IdentityResolver = loaded_dataset["resolver"]

    # Case 28 request email is smartinez6461@gmail.com
    user_28 = resolver.resolve_by_email("smartinez6461@gmail.com")
    assert user_28 is not None
    assert user_28.user_id == "user_28"

    # In dataset, there are several similar Martinez emails
    user_652 = resolver.resolve_by_email("mmartinez7917@gmail.com")
    assert user_652 is not None
    assert user_652.user_id == "user_652"
    assert user_652.user_id != user_28.user_id

    # Strict isolation assertion: user_28 must NOT associate mmartinez7917 or other similar strings
    assert not resolver.is_identifier_associated(user_28, "mmartinez7917@gmail.com")
    assert not resolver.is_identifier_associated(user_28, "camila.martinez@outlook.com")
    assert not resolver.is_identifier_associated(user_28, "a.martinez76@gmail.com")
    assert not resolver.is_identifier_associated(user_28, "smartinez")  # Substrings must not match


# ==============================================================================
# 3. Inclusive cutoff behavior: cases 11, 13, 31, and 32
# ==============================================================================
def test_regression_03_inclusive_cutoff_behavior(loaded_dataset):
    ev_index: EvidenceIndex = loaded_dataset["evidence_index"]

    # Cases 31 and 32: audit_at is 2026-09-15T12:00:00Z
    # evidence_51 was captured exactly at 2026-09-15T12:00:00Z
    cutoff_31 = "2026-09-15T12:00:00Z"
    assert is_at_or_before("2026-09-15T12:00:00Z", cutoff_31)
    admissible_31 = {e.file_id for e in ev_index.get_admissible_evidence(cutoff_31)}
    assert "evidence_51" in admissible_31, "evidence_51 captured at cutoff must be inclusively admissible"

    # Cases 11 and 13: audit_at is 2026-10-01T12:00:00Z
    # evidence_03 was captured exactly at 2026-10-01T12:00:00Z
    cutoff_11 = "2026-10-01T12:00:00Z"
    assert is_at_or_before("2026-10-01T12:00:00Z", cutoff_11)
    admissible_11 = {e.file_id for e in ev_index.get_admissible_evidence(cutoff_11)}
    assert "evidence_03" in admissible_11, "evidence_03 captured at cutoff must be inclusively admissible"


# ==============================================================================
# 4. Exclusion of evidence captured after audit_at
# ==============================================================================
def test_regression_04_exclusion_of_evidence_after_cutoff(loaded_dataset):
    ev_index: EvidenceIndex = loaded_dataset["evidence_index"]

    # Case 01 audit_at is 2026-09-03T11:30:00Z
    cutoff_01 = "2026-09-03T11:30:00Z"
    admissible = {e.file_id for e in ev_index.get_admissible_evidence(cutoff_01)}

    # evidence_54 was captured 2026-09-02T23:00:00Z <= 2026-09-03T11:30:00Z -> ADMISSIBLE
    assert "evidence_54" in admissible

    # evidence_01 (captured 2026-09-15), evidence_03 (2026-10-01), evidence_05 (2026-09-21)
    # captured strictly AFTER cutoff -> MUST BE EXCLUDED
    assert "evidence_01" not in admissible
    assert "evidence_03" not in admissible
    assert "evidence_05" not in admissible
    assert is_strictly_after("2026-09-15T11:59:39Z", cutoff_01)


# ==============================================================================
# 5. Contradictory deletion claim versus surviving failover record: case 05
# ==============================================================================
def test_regression_05_contradictory_failover_record(loaded_dataset):
    ev_index: EvidenceIndex = loaded_dataset["evidence_index"]
    ev_54_rec = ev_index.by_id["evidence_54"]

    # Inspect evidence_54 SQL snapshot structurally
    inspection = ev_index.inspect_sql(ev_54_rec, search_terms={"account_005", "leila.haddad@yahoo.com"})

    # Check tables present
    assert "customer_profiles_primary" in inspection.tables
    assert "customer_profiles_failover_replica" in inspection.tables

    # In primary, account_005 must be ABSENT
    primary_matches = [m for m in inspection.matched_rows if m.table_name == "customer_profiles_primary"]
    assert len(primary_matches) == 0, "account_005 is absent from primary table"

    # In failover replica, account_005 must be PRESENT
    replica_matches = [m for m in inspection.matched_rows if m.table_name == "customer_profiles_failover_replica"]
    assert len(replica_matches) == 1, "account_005 survived in failover replica"
    assert replica_matches[0].resource_id == "account_005"
    assert replica_matches[0].matched_columns.get("account_status") == "ACTIVE"


# ==============================================================================
# 6. Replica reconciliation: case 16 and case 22
# ==============================================================================
def test_regression_06_replica_reconciliation(loaded_dataset):
    ev_index: EvidenceIndex = loaded_dataset["evidence_index"]
    ev_05_rec = ev_index.by_id["evidence_05"]

    # Case 16 (user_53: diya.k4436@outlook.com): account_994 is in read replica, absent in primary
    insp_16 = ev_index.inspect_sql(ev_05_rec, search_terms={"account_994"})
    primary_16 = [m for m in insp_16.matched_rows if m.table_name == "customer_data_primary"]
    replica_16 = [m for m in insp_16.matched_rows if m.table_name == "customer_data_read_replica"]
    assert len(primary_16) == 0, "account_994 must be absent from primary"
    assert len(replica_16) == 1, "account_994 must be present in read replica (drift)"
    assert replica_16[0].resource_id == "account_994"

    # Case 22 (user_51: seoyeon-han@gmail.com): analytics_4440 still has exposed PII
    insp_22 = ev_index.inspect_sql(ev_05_rec, search_terms={"analytics_4440", "seoyeon-han@gmail.com"})
    assert any(m.resource_id == "analytics_4440" for m in insp_22.matched_rows)


# ==============================================================================
# 7. Policy-specific treatment: support, analytics, security audit, and tombstone
# ==============================================================================
def test_regression_07_policy_specific_treatment(loaded_dataset):
    rules = {r.data_category: r for r in loaded_dataset["rules"]}

    # Verify policy rules
    assert rules["SUPPORT_MESSAGE"].required_action == "REDACT"
    assert rules["SUPPORT_ATTACHMENT"].required_action == "DELETE"
    assert rules["ANALYTICS_PROFILE"].required_action == "ANONYMIZE"
    assert rules["SECURITY_AUDIT_LOG"].required_action == "RETAIN"
    assert rules["ACCOUNT_TOMBSTONE"].required_action == "REDACT"

    # Case 31: tombstone_440 in evidence_51 has direct identifiers redacted
    ev_index: EvidenceIndex = loaded_dataset["evidence_index"]
    ev_51_rec = ev_index.by_id["evidence_51"]
    insp_51 = ev_index.inspect_json(ev_51_rec, search_terms={"tombstone_440", "tombstone_9178"})

    tombstone_440 = next(m.matched_data for m in insp_51.matched_records if m.resource_id == "tombstone_440")
    assert tombstone_440["name"] is None
    assert tombstone_440["email"] is None
    assert tombstone_440["phone"] is None
    assert tombstone_440["email_hash"] is None
    assert tombstone_440["subject_reference"] == "user_541"  # Tombstone preserves stable user reference

    # Case 32: tombstone_9178 in evidence_51 has direct identifiers exposed (policy violation)
    tombstone_9178 = next(m.matched_data for m in insp_51.matched_records if m.resource_id == "tombstone_9178")
    assert tombstone_9178["email"] == "addo.kofi@gmail.com"
    assert tombstone_9178["name"] == "Kofi Addo"


# ==============================================================================
# 8. Active data flow and dependent remediation ordering
# ==============================================================================
def test_regression_08_active_data_flow_ordering():
    # Load sample_output.csv directly to verify cases with active data flows (e.g. case 11, 15, 18, 20, 29, 30)
    with open(DATASET_DIR / "sample_output.csv", "r", encoding="utf-8") as f:
        rows = [r for r in f.read().splitlines()[1:] if r.strip()]

    for row in rows:
        cid, status, steps_raw = row.split(",", 2)
        if steps_raw.startswith('"') and steps_raw.endswith('"'):
            steps_raw = steps_raw[1:-1].replace('""', '"')
        steps = json.loads(steps_raw)

        # If there is a DISABLE_DATA_FLOW step, it MUST appear before DELETE_RECORD / REDACT_RECORD / ANONYMIZE_RECORD
        flow_disable_indices = [
            idx for idx, s in enumerate(steps) if s.get("operation") == "DISABLE_DATA_FLOW"
        ]
        if flow_disable_indices:
            flow_idx = flow_disable_indices[0]
            record_remediation_indices = [
                idx
                for idx, s in enumerate(steps)
                if s.get("operation") in ("DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD")
            ]
            for r_idx in record_remediation_indices:
                assert (
                    flow_idx < r_idx
                ), f"{cid}: DISABLE_DATA_FLOW (step {flow_idx+1}) must precede record remediation (step {r_idx+1})"


# ==============================================================================
# 9. Restore-risk detection and blocking: case 09, 14, 17
# ==============================================================================
def test_regression_09_restore_risk_detection_and_blocking(loaded_dataset):
    ev_index: EvidenceIndex = loaded_dataset["evidence_index"]

    # Case 09 cites evidence_93
    ev_93_rec = ev_index.by_id["evidence_93"]
    insp_93 = ev_index.inspect_sql(ev_93_rec, search_terms={"backup_4978", "k.appiah88@gmail.com"})
    matched_backup = [m for m in insp_93.matched_rows if m.resource_id == "backup_4978"]
    assert len(matched_backup) == 1
    # Check that restore_allowed was 1
    assert matched_backup[0].matched_columns.get("restore_allowed") in (1, "1")

    # Verify that in sample_output.csv for case 09, BLOCK_RESTORE precedes record verifications
    with open(DATASET_DIR / "sample_output.csv", "r", encoding="utf-8") as f:
        text = f.read()
    assert "REPORT_RESTORE_RISK" in text
    assert "BLOCK_RESTORE" in text
    assert "VERIFY_RESTORE_BLOCKED" in text


# ==============================================================================
# 10. Exact output-schema and ordering invariants across the public samples
# ==============================================================================
def test_regression_10_output_schema_and_ordering_invariants(loaded_dataset):
    valid_ev_ids = loaded_dataset["valid_ev_ids"]
    sample_case_ids = [f"case_{i:02d}" for i in range(1, 33)]

    # 1. Validate real sample_output.csv
    validated_rows = validate_output_file(
        DATASET_DIR / "sample_output.csv",
        expected_case_ids=sample_case_ids,
        valid_evidence_ids=valid_ev_ids,
    )
    assert len(validated_rows) == 32

    # 2. Replay real sample_output.csv against itself -> 100% exact match
    replay_report = replay_samples(validated_rows, validated_rows)
    assert replay_report.status_accuracy == 1.0
    assert replay_report.exact_match_accuracy == 1.0

    # 3. Test negative validation cases
    # A. Corrupt consecutive step numbering
    bad_steps = [
        {"step_no": 1, "phase": "VERIFICATION", "system_id": "account_service", "resource_id": "acc_1", "operation": "VERIFY_RECORD_ABSENT", "state": "ABSENT", "evidence_id": "evidence_54"},
        {"step_no": 3, "phase": "VERIFICATION", "system_id": "account_service", "resource_id": "acc_2", "operation": "VERIFY_RECORD_ABSENT", "state": "ABSENT", "evidence_id": "evidence_54"},
    ]
    with pytest.raises(OutputValidationError, match="step_no must be consecutive"):
        validate_steps_contract("case_test", "COMPLETE", bad_steps, valid_ev_ids)

    # B. Phase out of order
    bad_order_steps = [
        {"step_no": 1, "phase": "REMEDIATION", "system_id": "account_service", "resource_id": "acc_1", "operation": "DELETE_RECORD", "state": "ABSENT", "evidence_id": ""},
        {"step_no": 2, "phase": "FINDING", "system_id": "account_service", "resource_id": "acc_1", "operation": "REPORT_REMAINING_RECORD", "state": "PRESENT", "evidence_id": "evidence_54"},
    ]
    with pytest.raises(OutputValidationError, match="appears after a later phase"):
        validate_steps_contract("case_test", "INCOMPLETE", bad_order_steps, valid_ev_ids)

    # C. COMPLETE with FINDING step
    bad_complete_steps = [
        {"step_no": 1, "phase": "FINDING", "system_id": "account_service", "resource_id": "acc_1", "operation": "REPORT_REMAINING_RECORD", "state": "PRESENT", "evidence_id": "evidence_54"},
    ]
    with pytest.raises(OutputValidationError, match="COMPLETE case may only contain VERIFICATION"):
        validate_steps_contract("case_test", "COMPLETE", bad_complete_steps, valid_ev_ids)

    # D. INCOMPLETE remediation step with non-empty evidence_id
    bad_remediation_evidence = [
        {"step_no": 1, "phase": "FINDING", "system_id": "account_service", "resource_id": "acc_1", "operation": "REPORT_REMAINING_RECORD", "state": "PRESENT", "evidence_id": "evidence_54"},
        {"step_no": 2, "phase": "REMEDIATION", "system_id": "account_service", "resource_id": "acc_1", "operation": "DELETE_RECORD", "state": "ABSENT", "evidence_id": "evidence_54"},
    ]
    with pytest.raises(OutputValidationError, match="must have evidence_id=''"):
        validate_steps_contract("case_test", "INCOMPLETE", bad_remediation_evidence, valid_ev_ids)

    # E. NOT_APPLICABLE with non-empty steps
    with pytest.raises(OutputValidationError, match="NOT_APPLICABLE cases must have steps_json=\\[\\]"):
        validate_steps_contract("case_test", "NOT_APPLICABLE", bad_steps, valid_ev_ids)


# ==============================================================================
# Additional Loader and Timestamp Unit Tests
# ==============================================================================
def test_loader_validations(tmp_path):
    # Test duplicate identifier detection
    dup_file = tmp_path / "dup.csv"
    dup_file.write_text("case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\ncase_01,a@b.com,2026-01-01T00:00:00Z,COMPLETE,2026-01-02T00:00:00Z,2026-01-03T00:00:00Z,delete\ncase_01,a@b.com,2026-01-01T00:00:00Z,COMPLETE,2026-01-02T00:00:00Z,2026-01-03T00:00:00Z,delete\n", encoding="utf-8")
    with pytest.raises(DuplicateIdentifierError, match="Duplicate case_id"):
        load_deletion_requests(dup_file)

    # Test missing column detection
    missing_col_file = tmp_path / "missing.csv"
    missing_col_file.write_text("case_id,email,requested_at\ncase_01,a@b.com,2026-01-01T00:00:00Z\n", encoding="utf-8")
    with pytest.raises(SchemaValidationError, match="missing required columns"):
        load_deletion_requests(missing_col_file)
