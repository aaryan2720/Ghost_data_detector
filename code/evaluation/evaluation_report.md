# Evaluation Report: Ghost Data Still Exists (Milestone 3)

## 1. Executive Summary & Evaluation Semantics

This evaluation report documents the implementation and results for **Milestone 3: Trace Correlation, Step Envelope Scoping, and Full Public Evaluation** of the HackerRank Orchestrate (October 2026) challenge, "Ghost Data Still Exists."

### Strict Separation of Evaluation Metrics
1. **Fixture Replay Baseline**: Verifies grader and validator correctness by replaying `dataset/sample_output.csv`. As established in Milestone 2, fixture self-consistency reports 100% on identical data, but this is **strictly separated from model or investigator prediction accuracy**.
2. **Independent Investigator Evaluation**: Evaluates the genuine `CaseInvestigator` pipeline running on `dataset/sample_deletion_requests.csv` without reading `sample_output.csv`. Decisions and step sequences are derived solely from request text, identity history, participant-visible evidence, system activity, and deletion rules. Predictions are compared against `sample_output.csv` ground truth **only after generation**.
3. **Generation Path Independence**: Enforced via regression test `test_generation_does_not_read_sample_output`, which intercepts and blocks any filesystem attempt to open `sample_output.csv` during prediction generation.

---

## 2. Before / After Comparison on 32 Public Cases

| Metric | Milestone 2 Baseline | Milestone 3 (After Improvements) | Delta / Improvement |
| :--- | :---: | :---: | :---: |
| **Case-level Status Accuracy** | 29 / 32 (90.62%) | **32 / 32 (100.00%)** | **+9.38% (All mismatches resolved)** |
| **Exact Case Matches (Full Sequence)** | 0 / 32 (0.00%) | **16 / 32 (50.00%)** | **+50.00% (16 cases matched 100%)** |
| **Field-level Accuracy** | 958 / 1,337 (71.65%) | **1,167 / 1,281 (91.10%)** | **+19.45%** |
| **Truth Step Count** | 193 steps | 193 steps | - |
| **Generated Step Count** | 306 steps (+58.5% excess) | **189 steps (-2.0%)** | **-117 steps (Overgeneration eliminated)** |
| **Status Mismatches** | 3 (`case_10`, `case_15`, `case_17`) | **0 mismatches** | **All 3 confirmed and resolved** |

---

## 3. Investigation & Resolution of the Three Status Mismatches

All three baseline status mismatches (`case_10`, `case_15`, `case_17`) were false negatives where the investigator incorrectly predicted `COMPLETE` instead of `INCOMPLETE`. Each case was traced end-to-end to its grounding in operational logs and system activity:

### Case 10: Nadia Ionescu (`nadia.ionescu@yahoo.com`)
- **Cutoff & Timestamps**: Requested `2026-08-31T15:42:00Z`, reported `2026-09-02T10:08:00Z`, `audit_at: 2026-09-18T12:25:00Z`.
- **Root Cause**: In `evidence/logs/support_replica.log` (`evidence_61`, captured `2026-09-17T22:00:19Z`), an initial log line recorded `lookup_key=nadia.ionescu@yahoo.com` with `trace_id=tr-rp-002`. Subsequent event lines logged `service=support_replica trace_id=tr-rp-002 event=contact_query_completed resource_id=support_002 rows=1` and `event=deletion_marker_check resource_id=support_002 marker_found=false`.
- **Resolution**:
  1. Implemented two-pass distributed trace correlation in `inspect_log` so subsequent event lines sharing `trace_id=tr-rp-002` inherit the matched identity.
  2. Normalized `service=support_replica` in operational logs to canonical `system_id="support_platform"`.
- **Outcome**: Finding `REPORT_REMAINING_RECORD` on `support_platform:support_002` correctly detected; case status correctly resolved as `INCOMPLETE`.

### Case 15: Lucia Torres (`lucia-torres@gmail.com`)
- **Cutoff & Timestamps**: Requested `2026-08-20T11:05:00Z`, reported `2026-08-22T12:51:00Z`, `audit_at: 2026-09-15T12:50:00Z`.
- **Root Cause**: In `evidence/logs/service_events_ap_south_20260915.log` (`evidence_01`, captured `2026-09-15T12:00:00Z`), the query start event logged `subject_key="lucia-torres@gmail.com"` with `trace_id=tr-9750867`. The subsequent event logged only `service=integration_service trace_id=tr-9750867 resource_id=data_flow_9846 event=connector_heartbeat enabled=true status=active`.
- **Resolution**: Distributed trace correlation connected the user identity to the active connector event.
- **Outcome**: Finding `REPORT_ACTIVE_DATA_FLOW` on `integration_service:data_flow_9846` correctly detected; case status correctly resolved as `INCOMPLETE`.

### Case 17: Leonie Gauthier (`leonie.g9352@outlook.com`)
- **Cutoff & Timestamps**: Requested `2026-08-20T11:14:00Z`, reported `2026-08-22T12:42:00Z`, `audit_at: 2026-09-15T12:50:00Z`.
- **Root Cause**: In `evidence/logs/service_events_ap_south_20260915.log` (`evidence_01`), trace `tr-8210651` correlated to `subject_key="leonie.g9352@outlook.com"`. The operational event recorded `service=backup_service trace_id=tr-8210651 resource_id=backup_3245 event=restore_candidate_evaluated eligible=true deletion_block=false destination=rds_replica`. The baseline parser looked for `restore_allowed=true`, failing to recognize the candidate evaluation format.
- **Resolution**: Extended backup service log inspection to match `eligible=true deletion_block=false`.
- **Outcome**: Finding `REPORT_RESTORE_RISK` on `backup_service:backup_3245` correctly detected; case status correctly resolved as `INCOMPLETE`.

---

## 4. Analysis and Resolution of Step Overgeneration

In the baseline evaluation, the investigator generated **306 steps against 193 expected steps (+58.5% overgeneration)**. The root causes were identified and eliminated with grounded evidence scoping rules:

### Root Causes of Overgeneration
1. **Ungrounded 404 Profile Lookups**: In `evidence_92` (`service_resource_export_20260915_114455.json`) and `evidence_89`, service exports recorded profile lookups returning HTTP 404 for 6 accounts (`account_3136`, `account_3866`, `account_5482`, `account_5684`, `account_6440`, `account_6813`). Because these items contained no user identifier, the baseline investigator indiscriminately added all 6 absent accounts to `verified_states` for *every* case.
2. **Ungrounded Anonymized Analytics Records**: In `evidence_56` (`customer_analytics_report_20260907.json`), record `analytics_901` had `user_id: null` and `email: null`. The baseline investigator treated any null-identity record as a verified anonymized state for *every* case.
3. **Multi-Service Snapshot Leakage**: Cross-cutting JSON bundles (such as `evidence_92`) contained resources belonging to multiple distinct users (`user_21`, `user_25`, `user_26`, `user_27`, `user_28`). Without strict reference checking against `user.user_id`, resources belonging to other users bled into unrelated cases.

### Grounded Scoping Rules Implemented
- **Account Grounding**: An absent account profile lookup (HTTP 404) is only accepted as evidence if `resource_id == primary_account_id`.
- **Workflow Resource Scoping**: An anonymized analytics record (`email: null`) is only accepted as evidence if that specific resource was targeted by the deletion workflow in `system_activity.csv` for that case during the request execution window.
- **Strict Subject Reference Matching**: In service exports and snapshot bundles, tickets, connectors, restore entries, and audit records are strictly filtered by `customer_reference == user.user_id` or `subject_reference == user.user_id` or explicit identity matching.
- **Step Count Reduction**: With these grounded rules, total generated steps dropped from **306 to 189**, achieving 98% concordance with the ground truth step envelope (193 expected).

---

## 5. Assessment of OCR and Image Evidence Gaps

The dataset includes 4 PNG console screenshots:
- `evidence_19`: `evidence/images/analytics_profile_view_20260713.png` (captured `2026-07-13`)
- `evidence_36`: `evidence/images/compliance_review_portal_20260408.png` (captured `2026-04-08`)
- `evidence_41`: `evidence/images/compliance_review_portal_20260314.png` (captured `2026-03-14`)
- `evidence_47`: `evidence/images/compliance_review_portal_20260216.png` (captured `2026-02-16`)

### Findings:
1. **Zero Evidence Dependency in Public Cases**: Inspection of `sample_output.csv` across all 32 public cases confirms that **zero steps cite any image file**. All findings and verified states cite SQL snapshots, JSON record exports, observability logs, pipe-delimited text exports, and PDF documents.
2. **PDF Documents Already Supported**: Document attachments (such as `evidence_60`: `customer_support_thread_20260908.pdf`) are fully parsed using `pypdf` via `inspect_pdf`, which extracts text content, matched tokens, and resource identifiers.
3. **Conclusion**: OCR / computer vision is **not required** to achieve 100% status accuracy or resolve any current public error. No OCR dependency was added, avoiding unnecessary runtime overhead and brittle external binary dependencies.

---

## 6. Participant-Created Evaluation Test Cases

The test suite in [`code/tests/test_milestone3.py`](../tests/test_milestone3.py) and [`code/tests/test_milestone2.py`](../tests/test_milestone2.py) exercises edge cases beyond the public sample set:

### Case 1: Two-Pass Distributed Trace Correlation
- **Test**: `test_m3_case_10_distributed_trace_correlation`
- **Scenario**: In distributed microservice logs, the search key appears on query initialization, while the resulting record state appears on a subsequent completion event without repeating the user's email.
- **Verification**: The log parser must correlate events by `trace_id` and report `support_platform:support_002` as `REPORT_REMAINING_RECORD`.

### Case 2: Active Connector Heartbeat Trace
- **Test**: `test_m3_case_15_active_connector_trace`
- **Scenario**: Distributed trace connects `lucia-torres@gmail.com` to `data_flow_9846` showing `connector_heartbeat enabled=true`.
- **Verification**: Reports `integration_service:data_flow_9846` as `REPORT_ACTIVE_DATA_FLOW` in `FINDING` phase with remediation `DISABLE_DATA_FLOW`.

### Case 3: Restore Candidate Evaluation Without Deletion Block
- **Test**: `test_m3_case_17_restore_candidate_risk`
- **Scenario**: Backup service logs `event=restore_candidate_evaluated eligible=true deletion_block=false`.
- **Verification**: Reports `backup_service:backup_3245` as `REPORT_RESTORE_RISK` in `FINDING` phase with remediation `BLOCK_RESTORE`.

### Case 4: Step Envelope Scoping and Alien Resource Isolation
- **Test**: `test_m3_step_envelope_scoping_no_alien_404_lookups`
- **Scenario**: Evidence file `evidence_92` contains 6 404 account lookups and an anonymized analytics profile. Case 1 (`case_01`, `account_001`) is investigated.
- **Verification**: Output steps must contain ONLY `account_001`. None of the alien accounts (`account_3136`, `account_3866`, `account_5482`, `account_5684`, `account_6440`, `account_6813`) or anonymized records may appear in the generated steps.

---

## 7. Failures Found and Improvements Made

1. **Failure**: Microservice logs omitted raw email addresses on violation lines, causing 3 cases to be misclassified as `COMPLETE`.
   - **Fix**: Implemented distributed trace correlation in `EvidenceIndex.inspect_log` to connect subject keys on start events to resource violations on completion events.
2. **Failure**: Unscoped JSON lookups polluted all cases with up to 7 spurious verification steps.
   - **Fix**: Restricted HTTP 404 profile lookups to the resolved primary account ID, and restricted anonymized analytics records to cases with grounded deletion worker activities.
3. **Failure**: Service names in logs (`support_replica`) did not match canonical system IDs (`support_platform`).
   - **Fix**: Added service name normalization in `CaseInvestigator._inspect_log_evidence`.
4. **Failure**: Backup service evaluated candidates with `eligible=true deletion_block=false` were missed.
   - **Fix**: Added candidate evaluation pattern matching alongside `restore_allowed=true`.

---

## 8. Acceptance Gate Verification

- [x] All 24 unit and regression tests pass (`code/tests/`).
- [x] All 3 status mismatches (`case_10`, `case_15`, `case_17`) are fully explained, fixed, and covered by regression tests.
- [x] Step overgeneration is reduced from 306 to 189 steps (within 2% of expected 193 steps).
- [x] Status accuracy on public evaluation reached **100.00% (32 / 32)**.
- [x] Exact sequence match rate reached **50.00% (16 / 32)**.
- [x] Full-dataset 518-case output generation is intentionally held until final review.
