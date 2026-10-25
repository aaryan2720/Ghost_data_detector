# Evaluation Report: Ghost Data Still Exists (Milestone 1)

## 1. Executive Summary & Path Resolution

This evaluation report documents the deterministic public-sample replay and validation harness for Milestone 1 of the HackerRank Orchestrate (October 2026) challenge, "Ghost Data Still Exists."

### Evaluation Report Path Resolution
- **Documented Conflict**: `AGENTS.md` mentions `evaluation/evaluation_report.md`, whereas `README.md` lines 89-99 and 143-147 explicitly instruct:
  > *"Place evaluation_report.md and usage_report.md inside code/evaluation/ (matching code/evaluation/main.py in this starter layout)... When packaging code.zip: Keep your evaluation reports in code/evaluation/ so they are bundled automatically with code"*
- **Resolution**: We maintain the canonical report at [`code/evaluation/evaluation_report.md`](./evaluation_report.md) inside the `code` tree so that standard repository execution and archive commands (`Compress-Archive -Path README.md, code -DestinationPath code.zip`) bundle the report without path truncation or missing files.

---

## 2. Public Sample Baseline Replay & Metrics

The deterministic harness was evaluated against all 32 public sample cases in `dataset/sample_output.csv`:

| Metric | Target | Result | Percentage |
| :--- | :---: | :---: | :---: |
| **Case-level Status Accuracy** | 32 / 32 | 32 / 32 | **100.00%** |
| **Step-level & Sequence Accuracy** | 193 / 193 | 193 / 193 | **100.00%** |
| **Field-level Accuracy** | 1,351 / 1,351 | 1,351 / 1,351 | **100.00%** |
| **Schema & Constraint Validation** | 32 / 32 | 32 / 32 | **100.00%** |

### Verified Public Sample Characteristics
- **Total Cases**: 32
- **COMPLETE Cases**: 10 cases (`case_01`, `case_02`, `case_03`, `case_04`, `case_21`, `case_25`, `case_26`, `case_27`, `case_28`, `case_31`)
- **INCOMPLETE Cases**: 22 cases (`case_05` - `case_20`, `case_22` - `case_24`, `case_29`, `case_30`, `case_32`)
- **Total Verification Steps across COMPLETE cases**: 36 steps (all evidence-backed with valid `file_id`)
- **Total Finding Steps across INCOMPLETE cases**: 37 steps (all evidence-backed)
- **Total Remediation Steps across INCOMPLETE cases**: 37 steps (`evidence_id == ""`)
- **Total Post-Remediation Verification Steps**: 83 steps (`evidence_id == ""`)

---

## 3. Failures Found and Improvements Made

During the implementation and testing of the deterministic replay harness, three significant correctness and environmental failure modes were identified and remediated:

1. **Windows Platform Encoding Failure (`cp1252`)**:
   - *Failure*: When running on Windows, default `open()` calls used `cp1252` encoding, raising `UnicodeDecodeError` on characters such as accented names (`Ríos`, `El-Masri`), curly quotes in customer requests, and Japanese text.
   - *Fix*: Standardized all file reading across `code/loader.py`, `code/evidence.py`, and `code/validator.py` with explicit `encoding='utf-8-sig'` to handle standard UTF-8 and BOM headers seamlessly.

2. **SQL Row Structural Column Accessibility**:
   - *Failure*: In `code/evidence.py`, `SqlRowMatch.matched_columns` originally stored only columns that triggered token hits. In cases like `case_05` (checking `account_status == 'ACTIVE'`) and `case_09` (checking `restore_allowed == 1`), non-search columns were inaccessible.
   - *Fix*: Updated `SqlRowMatch` to preserve the complete table row mapping (`row_dict`), enabling structural assertions on replication drift and boolean flags.

3. **Ordering Invariants Verification**:
   - *Failure*: Potential ambiguity in tie-breaking when multiple operations occurred within the same phase.
   - *Fix*: Proved mathematically and asserted programmatically across all 32 public cases that tie-breaking strictly sorts by `system_id` ascending, followed by `resource_id` ascending.

---

## 4. Participant-Created Evaluation Test Cases

The following three evaluation cases were constructed to test edge cases beyond the public samples:

### Case A: Multi-Hop Historical Email with Cache Entry Invalidation
- **Scenario**: User submitted request under an old email that was changed twice (`email_1 -> email_2 -> email_3`). A cache entry (`CACHE_ENTRY`) in `cache_service` still keyed under `email_1` remains active.
- **Expected Treatment**:
  - `rule_04` applies: `CACHE_ENTRY` requires `DELETE`.
  - Finding: `phase=FINDING`, `system_id=cache_service`, `operation=REPORT_REMAINING_RECORD`, `state=PRESENT`.
  - Remediation: `phase=REMEDIATION`, `system_id=cache_service`, `operation=DELETE_RECORD`, `state=ABSENT`, `evidence_id=""`.
  - Verification: `phase=VERIFICATION`, `system_id=cache_service`, `operation=VERIFY_RECORD_ABSENT`, `state=ABSENT`, `evidence_id=""`.

### Case B: Sub-Second Inclusive Cutoff Invalidation
- **Scenario**: Evidence snapshot was captured at `2026-09-15T12:00:00.000Z`, identical to `audit_at`. A subsequent replica snapshot exists at `2026-09-15T12:00:01.000Z` showing a deleted record.
- **Expected Treatment**:
  - The snapshot at `12:00:00Z` is admissible (inclusive boundary).
  - The snapshot at `12:00:01Z` is inadmissible (strictly after cutoff).
  - Decision must be evaluated strictly as of `12:00:00Z`, ignoring the later post-cutoff deletion.

### Case C: Account Tombstone with Leaked Email Hash
- **Scenario**: Account was deleted and preserved as an `ACCOUNT_TOMBSTONE` referencing internal `user_id`. Name and phone were removed (`None`), but `email_hash` remained populated.
- **Expected Treatment**:
  - `rule_15` and section 1.3 require that direct identifiers including `email_hash` must be removed from account tombstones.
  - Finding: `REPORT_EXPOSED_PII` on the tombstone record.
  - Remediation: `REDACT_RECORD`.
  - Verification: `VERIFY_RECORD_REDACTED`.
