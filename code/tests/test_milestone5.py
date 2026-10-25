"""Regression tests for Milestone 5 verified defects in intent classification,
evidence attribution, and log inspection.
"""

import pytest

from code.classifier import classify_request
from code.evidence import EvidenceIndex
from code.identity import IdentityResolver
from code.investigator import CaseInvestigator
from code.loader import (
    load_deletion_requests,
    load_deletion_rules,
    load_evidence_manifest,
    load_system_activity,
    load_user_audit_log,
    load_user_identities,
)
from code.models import DeletionRequest


def test_korean_and_portuguese_deletion_intent():
    """Verify Korean and Portuguese deletion requests are authorized and not marked NOT_APPLICABLE."""
    korean_text = "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다. 개인정보 처리 절차에 따라 현재 및 이전 식별자를 검토해 주세요. 검토가 완료되면 결과를 확인해 주세요."
    portuguese_text = "Solicito a exclusão permanente da conta associada a este e-mail. Verifiquem os identificadores atuais e anteriores conforme o processo de privacidade. Por favor, confirmem o resultado quando a análise terminar."

    k_res = classify_request(korean_text)
    assert k_res.is_deletion_request is True
    assert k_res.detected_intent == "DELETION_REQUEST"

    p_res = classify_request(portuguese_text)
    assert p_res.is_deletion_request is True
    assert p_res.detected_intent == "DELETION_REQUEST"


def test_non_deletion_rectification_and_marketing_exceptions():
    """Verify non-deletion requests with words like 'remove' or 'erase' in negative/opt-out context are NOT_APPLICABLE."""
    # case_537: rectification without removal
    text_537 = "My surname is misspelled on the account. Can you correct it without removing any of my records?"
    res_537 = classify_request(text_537)
    assert res_537.is_deletion_request is False

    # case_538: marketing removal only
    text_538 = "Please remove me from marketing lists only. I still want receipts and service messages for this account."
    res_538 = classify_request(text_538)
    assert res_538.is_deletion_request is False

    # case_539: access request, not erasure
    text_539 = "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it."
    res_539 = classify_request(text_539)
    assert res_539.is_deletion_request is False


def test_log_evidence_exposed_pii_detection():
    """Verify log read events with matching email (evidence_94 pattern) trigger REPORT_EXPOSED_PII."""
    dataset_dir = "dataset"
    identities = load_user_identities(f"{dataset_dir}/user_identities.csv")
    audit = load_user_audit_log(f"{dataset_dir}/user_audit_log.csv")
    rules = load_deletion_rules(f"{dataset_dir}/deletion_rules.csv")
    activities = load_system_activity(f"{dataset_dir}/system_activity.csv")
    ev_index = EvidenceIndex(f"{dataset_dir}/evidence_files.csv", dataset_dir)
    resolver = IdentityResolver(identities, audit)

    investigator = CaseInvestigator(resolver, ev_index, rules, activities)

    # case_18 (user mori.ren@gmail.com)
    req = DeletionRequest(
        case_id="case_18",
        email="mori.ren@gmail.com",
        requested_at="2026-09-08T11:00:00Z",
        reported_status="NOT_STARTED",
        reported_at="2026-09-09T11:00:00Z",
        audit_at="2026-09-26T11:00:00Z",
        request_text="I want this account and the connected records erased completely. Please verify all copies are gone and confirm the result.",
    )

    result = investigator.investigate(req)
    step_ops = {(s.system_id, s.resource_id, s.operation) for s in result.steps}

    # Must find exposed PII on support_5569 and analytics_037 from evidence_94
    assert ("support_platform", "support_5569", "REPORT_EXPOSED_PII") in step_ops
    assert ("analytics_platform", "analytics_037", "REPORT_EXPOSED_PII") in step_ops


def test_no_cross_user_proximity_attribution():
    """Verify that case_24 does not adopt analytics_1895 or analytics_4566 merely due to proximity window."""
    dataset_dir = "dataset"
    identities = load_user_identities(f"{dataset_dir}/user_identities.csv")
    audit = load_user_audit_log(f"{dataset_dir}/user_audit_log.csv")
    rules = load_deletion_rules(f"{dataset_dir}/deletion_rules.csv")
    activities = load_system_activity(f"{dataset_dir}/system_activity.csv")
    ev_index = EvidenceIndex(f"{dataset_dir}/evidence_files.csv", dataset_dir)
    resolver = IdentityResolver(identities, audit)

    investigator = CaseInvestigator(resolver, ev_index, rules, activities)

    # case_24 (keiko.nakamura@gmail.com)
    req = DeletionRequest(
        case_id="case_24",
        email="keiko.nakamura@gmail.com",
        requested_at="2026-09-01T12:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-09-02T12:00:00Z",
        audit_at="2026-09-15T12:00:00Z",
        request_text="I am asking you to remove my account and the personal information linked to it. Please review any identifiers connected to this account as part of the request. Let me know when the request has been completed.",
    )

    result = investigator.investigate(req)
    step_resources = {s.resource_id for s in result.steps}

    # Neither analytics_1895 nor analytics_4566 belong to keiko.nakamura
    assert "analytics_1895" not in step_resources
    assert "analytics_4566" not in step_resources
