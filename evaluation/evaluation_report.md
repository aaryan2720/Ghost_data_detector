# Evaluation Report: Ghost Data Still Exists (Milestones 1–5)

## 1. Executive Summary & Evaluation Semantics

This evaluation report documents the comprehensive validation, independent evidence-grounding audit, and submission readiness for the HackerRank Orchestrate (October 2026) challenge, "Ghost Data Still Exists."

### Strict Separation of Evaluation Metrics
1. **Fixture Replay Baseline**: Verifies grader and validator correctness by replaying fixture files. As established in Milestone 2, fixture self-consistency reports 100% on identical data, but this is **strictly separated from model or investigator prediction accuracy**.
2. **Independent Investigator Evaluation**: Evaluates the genuine `CaseInvestigator` pipeline running on `dataset/sample_deletion_requests.csv` without reading `sample_output.csv`. Decisions and step sequences are derived solely from request text, identity history, participant-visible evidence, system activity, and deletion rules. Predictions are compared against `sample_output.csv` ground truth **only after generation**.
3. **Full-Dataset Generation & Contract Validation**: Evaluates the entire 518-case dataset (`dataset/deletion_requests.csv`) written to `output.csv`, validated against all 14 structural, temporal, and policy contract invariants.
4. **Generation Path Independence**: Enforced via regression test `test_generation_does_not_read_sample_output`, which intercepts and blocks any filesystem attempt to open `sample_output.csv` during prediction generation.
5. **Milestone 5 Independent Evidence-Grounding Audit**: Audits every public-sample discrepancy, investigates proximity-based resource associations across all 518 cases, audits intent classification correctness across multilingual requests, and fixes verified defects with automated regression tests.

---

## 2. Full-Dataset Generation & Validation Results (518 Cases)

The investigator was executed against all 518 evaluation requests in `dataset/deletion_requests.csv` to produce the candidate `output.csv` at the repository root.

- **Generation Command**: `python -m code.main --mode investigate --requests dataset/deletion_requests.csv --output output.csv`
- **Validation Command**: `python -m code.main --mode validate --output output.csv --expected dataset/deletion_requests.csv`
- **Validation Result**: **SUCCESS: 518 rows valid according to competition contract.**

### Full-Dataset Row & Step Summary

| Contract Invariant | Result | Detail |
| :--- | :---: | :--- |
| **Row Count** | **518 / 518** | Exactly 1 output row for every unique input `case_id` |
| **Header Schema** | **PASS** | Exact column names and order: `case_id,deletion_status,steps_json` |
| **Sort Order** | **PASS** | Rows sorted strictly by `case_id` ascending |
| **Duplicate / Missing Cases** | **0 / 0** | Zero duplicate case IDs; zero missing cases |
| **Allowed Statuses** | **PASS** | Strictly `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE` |
| **JSON Serialization** | **PASS** | 100% of `steps_json` values parse as valid JSON arrays |
| **Step Key Invariants** | **PASS** | Exactly `{step_no, phase, system_id, resource_id, operation, state, evidence_id}` |
| **Step Numbering** | **PASS** | Consecutive integers starting from 1 with no gaps |
| **Phase & Operation Order** | **PASS** | `FINDING` -> `REMEDIATION` -> `VERIFICATION` with canonical operation precedence |
| **NOT_APPLICABLE Steps** | **PASS** | All 10 non-deletion cases have strictly `steps_json=[]` |
| **COMPLETE Steps** | **PASS** | All 260 complete cases have only `VERIFICATION` steps citing valid evidence |
| **INCOMPLETE Steps** | **PASS** | All 248 incomplete cases have findings with evidence; remediation & future verification use `evidence_id=""` |
| **Evidence ID Resolution** | **PASS** | 100% of non-empty evidence citations resolve to participant-visible `file_id`, `activity_id`, or `audit_id` |

### Full-Dataset Status Breakdown (Post-Audit)

- **Total Requests**: 518
- **`COMPLETE`**: 260 cases (50.19%)
- **`INCOMPLETE`**: 248 cases (47.88%)
- **`NOT_APPLICABLE`**: 10 cases (1.93%)
- **Total Synthesized Steps**: 1,842 steps

---

## 3. Milestone 5 Independent Evidence-Grounding Audit

### A. Public Sample Mismatch Audit (32 Cases)
- **Cases Reviewed**: 32 public fixture cases.
- **Status Accuracy**: **32 / 32 (100.00%)**
- **Field-Level Accuracy**: **1,173 / 1,260 (93.10%)**
- **Exact Full-Row Matches**: **17 / 32 (53.12%)**
- **Mismatches Analyzed**: 15 non-exact cases:
  - `case_03`, `case_09`, `case_12`, `case_18`, `case_20`, `case_21`, `case_23`, `case_24`, `case_25`, `case_26`, `case_27`, `case_28`, `case_29`, `case_30`, `case_31`.
- **Missing Steps**: 13 steps total across all 32 public cases (pred step count: 180 vs truth step count: 193).
- **Extra Steps**: 0 steps total across all 32 public cases.
- **Misordered Steps**: 0 cases (100% follow phase and canonical operation ordering).

### B. Proximity-Based Association Audit (All 518 Cases)
- **Reviewed**: 665 proximity-based step instances identified across 470 cases in the pre-audit output where `_find_user_activity_resources` collected any activity by `deletion_worker` within a 2-hour window (`[-900, 7200]` seconds).
- **Supported Associations**: Direct user ID, current/historical emails, phones, email hashes in SQLite tables (`customer_profiles`), JSON snapshots (`customer_data_snapshot_bundle`), text records, and explicit identity-link events (`LINK_RESOURCE_IDENTITY`).
- **Corrected Defect (Cross-User Resource Bleed)**: Replaced unconstrained 2-hour temporal proximity in `_find_user_activity_resources` with strict identity grounding. This immediately eliminated false adoption of other users' anonymized analytics profiles (`analytics_1895`, `analytics_4566`, `analytics_4574`, `analytics_6077`) across `case_24`, `case_25`, `case_26`, `case_27`, `case_28`, and `case_29`.
- **Unresolved Associations**: In high-throughput concurrent deletion batches where primary account records in `system_activity.csv` have identical delta offsets without direct user identity tags, choosing between multiple concurrent accounts remains inherently ambiguous from participant-visible data alone.

### C. Decision Correctness & Multilingual Intent Audit
A comprehensive audit of all 518 request texts revealed two critical decision defects in `code/classifier.py`:
1. **False Non-Deletion Classifications (26 cases corrected)**:
   - 12 Korean deletion requests (`이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다...`) and 14 Portuguese deletion requests (`Solicito a exclusão permanente da conta associada a este e-mail...`) were falsely classified as `NOT_APPLICABLE` because Korean (`삭제`, `영구 삭제`) and Portuguese (`exclusão permanente`, `apagar`) keywords were omitted from `DELETION_PATTERNS`.
   - **Correction**: Added Korean and Portuguese patterns. All 26 genuine requests are now correctly audited as deletion requests.
2. **False Deletion Classifications (3 cases corrected)**:
   - `case_537`: "My surname is misspelled on the account. Can you correct it without removing any of my records?" (Rectification; previously matched `removing`).
   - `case_538`: "Please remove me from marketing lists only. I still want receipts and service messages for this account." (Marketing opt-out; previously matched `remove`).
   - `case_539`: "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it." (Information access request; previously matched `erase`).
   - **Correction**: Added explicit non-deletion patterns for negative and opt-out contexts. All 3 cases are now correctly classified as `NOT_APPLICABLE` with `steps_json=[]`.
3. **Confirmed Ground-Truth Non-Deletion Cases**:
   - Exactly 10 requests in the entire 518 dataset (`case_533` through `case_542`) are genuine non-deletion requests. All other 508 requests are genuine deletion requests.

### D. Log Evidence Exposed PII Detection Audit
- In `case_18`, `evidence_94` (`resource_lookup_trace_20260926_103856.log`) contained read events for `support_5569` and `analytics_037` with `requester_email=mori.ren@gmail.com` and `email=mori.ren@gmail.com`.
- **Defect**: The log parser previously searched only for `"message_pii_scan"` or `"rows=1"`, failing to detect exposed PII on `support_ticket_read_completed` and `analytics_profile_read_completed`.
- **Correction**: Updated `_inspect_log_evidence` to detect exposed PII when email fields match user identifiers. `case_18` now captures findings, remediations, and verifications for both resources.

---

## 4. Test Suite Verification

The automated test suite comprises 35 tests covering all contract requirements and verified defects:

- **Test Command**: `python -m pytest code/tests/ -v`
- **Result**: **35 passed in 1.16s**

### Test Suite Structure:
- **`test_milestone1.py` (11 tests)**: Historical email resolution, similar email isolation, inclusive cutoffs, post-cutoff exclusion, replica reconciliation, policy treatments, active flow ordering, restore blocking, schema invariants.
- **`test_milestone2.py` (9 tests)**: Independent generation proof, slice evaluations across all decision categories.
- **`test_milestone3.py` (4 tests)**: Distributed trace correlation, active connector heartbeats, restore candidate risk detection, step envelope scoping without alien lookups.
- **`test_milestone4.py` (7 tests)**: Adversarial tests for unknown identity, cutoff boundary, unrelated record isolation, step ordering, evidence ID contract, evidence requirement for COMPLETE, empty steps for NOT_APPLICABLE.
- **`test_milestone5.py` (4 tests)**:
  1. `test_korean_and_portuguese_deletion_intent`: Confirms multilingual Korean and Portuguese requests are recognized as authorized deletion requests.
  2. `test_non_deletion_rectification_and_marketing_exceptions`: Confirms negative/opt-out phrasing (`case_537`, `case_538`, `case_539`) yields `NOT_APPLICABLE`.
  3. `test_log_evidence_exposed_pii_detection`: Confirms read-completed log events with user email trigger `REPORT_EXPOSED_PII`.
  4. `test_no_cross_user_proximity_attribution`: Confirms concurrent deletion worker activity for unrelated users is not cross-attributed.

---

## 5. Remaining Risks & Candidacy Status

1. **Unobservable Security Audit Records in Incomplete Cases**: In public samples `case_09`, `case_20`, `case_23`, `case_24`, `case_29`, and `case_30`, ground truth includes post-remediation verification steps for `security_service:audit_record_XXXX VERIFY_RECORD_PRESENT (ev: "")`. In several cases (e.g. `audit_record_5569`), the specific ID does not appear in any participant-visible evidence prior to `audit_at`. We intentionally do not fabricate ungrounded IDs from organizer truth.
2. **Concurrent Batch Account Disambiguation**: When multiple accounts are processed in identical execution windows without direct user tags in `system_activity.csv`, participant-visible evidence may support multiple alternative account IDs.
3. **Candidacy Verification**: Per AGENTS.md rules and Milestone 5 instructions, the candidate has been audited, verified with regression tests, regenerated, and validated against the competition contract. The submission has NOT been uploaded to HackerRank.
