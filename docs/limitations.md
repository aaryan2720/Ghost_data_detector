# Engineering Limitations & Trade-Offs

This document candidly outlines the technical boundaries, unobservable state challenges, and design trade-offs in **Host Data Detector**.

---

## 1. Unobservable Post-Cutoff Audit Records

### The Challenge
In certain enterprise architectures, policy requires retaining a security audit ledger record (e.g. `security_service:audit_record_XXXX`) when an account is deleted under a legal hold. In several sample evaluation cases, ground truth contains future verification steps citing specific audit record identifiers:

```json
{
  "step_no": 7,
  "phase": "VERIFICATION",
  "system_id": "security_service",
  "resource_id": "audit_record_5569",
  "operation": "VERIFY_RECORD_PRESENT",
  "state": "PRESENT",
  "evidence_id": ""
}
```

### Technical Boundary
In the supplied evidence, `audit_record_5569` does not exist in any file, database, or activity event prior to `audit_at`.
- **Engine Decision**: The engine strictly adheres to evidence grounding (§4 Rule 3). Synthesizing or guessing ungrounded internal identifiers without evidence would introduce hallucinated data into production audit trails.
- **Trade-Off**: The engine omits speculative future audit IDs when no evidence establishes their existence, accepting a minor step-count difference in exchange for 100% evidence grounding.

---

## 2. Concurrent Batch Account Disambiguation

### The Challenge
In high-throughput microservices, deletion workers process multiple accounts simultaneously within identical sub-second execution windows:
- Activity logs show entries like:
  ```text
  act_1241: Deletion worker submitted primary profile account_6523 to account_service
  act_1242: Deletion worker submitted primary profile account_7891 to account_service
  ```
- Neither activity row contains the user ID, email, or a direct session trace link in its text details.

### Technical Boundary
When testing log-based heuristics during Milestone 6 to link accounts from older trace logs, historical profile collisions occurred (e.g., attributing an old inactive profile `account_6523` instead of the current primary account, causing regression in exact matches).
- **Engine Decision**: The engine relies on direct identity links (user ID, current/historical emails, phones, hashes) and tight temporal proximity to the reported status. Where participant-visible evidence is genuinely ambiguous, speculative guessing is avoided.

---

## 3. Multimodal Artifact Processing Boundaries

### Image and Binary Screenshot Artifacts
- The dataset includes UI screenshots (e.g. `account_admin_console_20260926.png`, `backup_restore_console_20260429.png`).
- While human operators or vision-language models can OCR screenshots, deterministic local execution without heavy neural network dependencies relies on companion structured records (SQL exports, JSON manifests, and application logs) that reflect the underlying system state.
- **Future Work**: Integration of lightweight, deterministic local OCR (e.g. Tesseract) or local multimodal embeddings to parse image text directly during offline runs.

---

## 4. In-Memory SQLite Scale Limits

### Snapshot Execution Model
- The engine executes SQL evidence snapshots by loading them into in-memory SQLite instances (`:memory:`).
- **Advantage**: Fast, completely isolated, zero filesystem mutation, and full SQL query capability.
- **Limitation**: Highly effective for snapshots up to several gigabytes; for petabyte-scale production data warehouses, an external distributed query interface (e.g. Trino, DuckDB external table scanning) would replace in-memory script execution.

---

## 5. Scope of Portfolio Release

- **Competition Context**: This codebase originated as an engineering challenge for HackerRank Orchestrate (October 2026).
- **Independent Portfolio Status**: The October competition submission was not completed; this repository represents an independent, refactored open-source software engineering portfolio release.
- **Non-Production Disclaimer**: This software is provided as an architectural reference and validation framework. Production deployments must integrate with live organization IAM and database connection pools.
