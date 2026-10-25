# Evaluation Report: Ghost Data Still Exists (Milestones 1–4)

## 1. Executive Summary & Evaluation Semantics

This evaluation report documents the final validation, evaluation results, and submission readiness for the HackerRank Orchestrate (October 2026) challenge, "Ghost Data Still Exists."

### Strict Separation of Evaluation Metrics
1. **Fixture Replay Baseline**: Verifies grader and validator correctness by replaying fixture files. As established in Milestone 2, fixture self-consistency reports 100% on identical data, but this is **strictly separated from model or investigator prediction accuracy**.
2. **Independent Investigator Evaluation**: Evaluates the genuine `CaseInvestigator` pipeline running on `dataset/sample_deletion_requests.csv` without reading `sample_output.csv`. Decisions and step sequences are derived solely from request text, identity history, participant-visible evidence, system activity, and deletion rules. Predictions are compared against `sample_output.csv` ground truth **only after generation**.
3. **Full-Dataset Generation & Contract Validation**: Evaluates the entire 518-case dataset (`dataset/deletion_requests.csv`) written to `output.csv`, validated against all 14 structural, temporal, and policy contract invariants.
4. **Generation Path Independence**: Enforced via regression test `test_generation_does_not_read_sample_output`, which intercepts and blocks any filesystem attempt to open `sample_output.csv` during prediction generation.

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
| **NOT_APPLICABLE Steps** | **PASS** | All 33 non-deletion cases have strictly `steps_json=[]` |
| **COMPLETE Steps** | **PASS** | All 255 complete cases have only `VERIFICATION` steps citing valid evidence |
| **INCOMPLETE Steps** | **PASS** | All 230 incomplete cases have findings with evidence; remediation & future verification use `evidence_id=""` |
| **Evidence ID Resolution** | **PASS** | 100% of non-empty evidence citations resolve to participant-visible `file_id`, `activity_id`, or `audit_id` |

### Full-Dataset Status Breakdown

- **Total Requests**: 518
- **`COMPLETE`**: 255 cases (49.2%)
- **`INCOMPLETE`**: 230 cases (44.4%)
- **`NOT_APPLICABLE`**: 33 cases (6.4%)
- **Total Synthesized Steps**: 1,939 steps

---

## 3. Public-Sample Benchmark Accuracy (32 Cases)

The public evaluation harness independently evaluated the 32 cases in `dataset/sample_deletion_requests.csv` against `dataset/sample_output.csv` ground truth:

- **Evaluation Command**: `python -m code.evaluation.main --mode investigator`

| Metric | Milestone 2 | Milestone 3 | Milestone 4 Final | Overall Improvement |
| :--- | :---: | :---: | :---: | :---: |
| **Case-level Status Accuracy** | 29 / 32 (90.62%) | 32 / 32 (100.00%) | **32 / 32 (100.00%)** | **+9.38% (Zero status errors)** |
| **Exact Full-Row Matches** | 0 / 32 (0.00%) | 16 / 32 (50.00%) | **19 / 32 (59.38%)** | **+59.38% (19 cases matched 100%)** |
| **Field-level Accuracy** | 71.65% | 91.10% | **1,173 / 1,274 (92.07%)** | **+20.42%** |
| **Truth Step Count** | 193 steps | 193 steps | **193 steps** | - |
| **Generated Step Count** | 306 steps (+58.5%) | 189 steps (-2.0%) | **188 steps (-2.6%)** | **Step envelope closely bounded** |

*Note: Public-sample accuracy is evaluated on the 32 public cases only and is not conflated with full-dataset accuracy.*

---

## 4. Error Categorization Across the 13 Non-Exact-Matching Cases

Across the 13 public sample cases that did not match ground truth 100% at the character/sequence level:

- **Total Missing Steps**: 20 steps
- **Total Extra Steps**: 15 steps
- **Ordering Differences**: 0 cases (all generated steps follow canonical phase, operation, and resource order)

### Categorization Breakdown

| Discrepancy Category | Affected Cases | Root Cause & Analysis |
| :--- | :--- | :--- |
| **Missing Security Audit Verification** | `case_09`, `case_20`, `case_23`, `case_24`, `case_29`, `case_30` | In ground truth, post-remediation verification includes retained `audit_record_XXXX` from security audit logs. In these cases, the audit record was captured in structured log files with trace IDs disconnected from the request window. |
| **Cross-Window Analytics Profile Attribution** | `case_25`, `case_26`, `case_27`, `case_28`, `case_29` | High-throughput background workers anonymized multiple analytics profiles within overlapping 2-hour execution windows, causing minor over- or under-inclusion of anonymized analytics records. |
| **Microservice Log Trace Association** | `case_18` | A complex multi-service cascade spanning 4 services in `evidence_94` had partial trace segmentation where intermediate ticket and export records were unlinked. |
| **Primary Account Grounding Drift** | `case_20`, `case_23`, `case_25`, `case_28`, `case_31` | Account resolution between primary and regional replicas selected an alternative active account resource ID from system activity logs. |

---

## 5. Test Suite Verification & Adversarial Edge Cases

The complete test suite comprises 31 automated unit, regression, and adversarial test cases:

- **Test Command**: `python -m pytest code/tests/ -v`
- **Result**: **31 passed in 1.08s**

### Test Coverage Summary:
- **`test_milestone1.py` (11 tests)**: Historical email resolution, similar email isolation, inclusive cutoff boundaries, evidence exclusion after cutoff, contradictory replica records, replica reconciliation, policy-specific treatments, active data flow ordering, restore risk blocking, schema invariants.
- **`test_milestone2.py` (9 tests)**: Independent generation verification (ensures `sample_output.csv` cannot be opened by production code), slice evaluations across all decision categories.
- **`test_milestone3.py` (4 tests)**: Distributed trace correlation, active connector heartbeats, restore candidate risk detection, step envelope scoping without alien 404 lookups.
- **`test_milestone4.py` (7 tests)**:
  1. `test_adversarial_unknown_identity`: Completely unregistered email yields safe `INCOMPLETE` with compliant envelope without crashing.
  2. `test_adversarial_exact_cutoff_boundary`: Verifies exact-millisecond cutoff boundary conditions (inclusive cutoff vs strictly post-cutoff).
  3. `test_adversarial_unrelated_records_isolation`: Verifies decoy users and cross-talk records cannot leak into another user's case findings.
  4. `test_adversarial_step_ordering_and_phase_invariants`: Verifies validator catches phase order violations (e.g. `REMEDIATION` before `FINDING`).
  5. `test_adversarial_evidence_id_contract`: Verifies validator rejects INCOMPLETE case with evidence IDs on remediation or future verification.
  6. `test_adversarial_complete_case_requires_evidence`: Verifies validator rejects COMPLETE case when verification step lacks evidence citation.
  7. `test_adversarial_non_deletion_empty_steps`: Verifies validator rejects non-empty steps on `NOT_APPLICABLE` cases.

---

## 6. Packaging & Submission Readiness Verification

Packaging verification confirmed that the submission archive strictly adheres to competition constraints:

| Submission Requirement | Verification Status | Notes |
| :--- | :---: | :--- |
| **`output.csv` at root** | **VERIFIED** | Exactly 518 sorted rows, 100% contract compliant |
| **`code.zip` Archive Contents** | **VERIFIED** | Exactly 25 source files |
| **Dataset Exclusion** | **VERIFIED** | `dataset/` strictly excluded from archive |
| **Environment & Cache Exclusion** | **VERIFIED** | `.venv`, `__pycache__`, `.pytest_cache`, `.git` strictly excluded |
| **Secret & Credential Scrubbing** | **VERIFIED** | Zero API keys, passwords, or credentials in codebase or logs |
| **Participant Log (`log.txt`)** | **VERIFIED** | Formatted strictly per AGENTS.md §5.1 & §5.2 with authoritative `tool=Antigravity` and `model=Gemini 3.8 Flash (Medium)` |
| **Challenge Submission URL** | **VERIFIED** | `https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists` |

---

## 7. Known Limitations & Unresolved Risks

1. **Synthetic Audit Record Linkage**: On cases where multiple users undergo deletion within the same hourly batch without shared trace IDs, identifying the exact security audit record number relies on heuristic timestamp proximity.
2. **Replication Lag Resolution**: When replica snapshots are separated by weeks, intermediate replication events not recorded in observability logs cannot be fully reconstructed without SQL snapshot inspection.
3. **No External Network Dependencies**: The agent operates entirely offline and deterministically; any remote change in evaluation harness requirements must be reflected in local rule configurations.
