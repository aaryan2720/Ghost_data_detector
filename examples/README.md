# Synthetic Examples for Host Data Detector

This directory provides safe, synthetic, and completely fictional data fixtures designed for demonstration, local development, and pipeline verification without relying on proprietary competition artifacts.

## Directory Structure

```text
examples/
├── README.md
├── run_example.py
└── synthetic_data/
    ├── deletion_requests.csv
    ├── deletion_rules.csv
    ├── evidence_files.csv
    ├── system_activity.csv
    ├── user_audit_log.csv
    ├── user_identities.csv
    └── evidence/
        ├── databases/
        │   └── replica_snapshot.sql
        └── records/
            └── export_manifest.json
```

## Running the Example

Run the investigation engine against the synthetic data fixtures:

```bash
python examples/run_example.py
```

Or invoke `code.main` directly with the synthetic dataset path:

```bash
python -m code.main --mode investigate --requests examples/synthetic_data/deletion_requests.csv --output examples/synthetic_output.csv --dataset-dir examples/synthetic_data
```

To validate the generated output contract:

```bash
python -m code.main --mode validate --output examples/synthetic_output.csv --expected examples/synthetic_data/deletion_requests.csv --dataset-dir examples/synthetic_data
```

## Included Synthetic Scenarios

1. **`syn_case_001` (COMPLETE)**:
   - User `synth_user_01` submitted a deletion request.
   - Deletion was processed across primary services. The account was tombstones compliant with `ACCOUNT_TOMBSTONE` policy.
   - Evidence verifies tombstone presence and absence of direct PII.
   - Expected status: `COMPLETE`.

2. **`syn_case_002` (INCOMPLETE)**:
   - User `synth_user_02` requested complete erasure.
   - Active sync job `job_sync_99` is scheduled, and a surviving user record exists in an un-purged read replica `replica_snapshot.sql`.
   - Engine identifies the active data flow and lingering replica record.
   - Formulates ordered remediation plan: `DISABLE_DATA_FLOW` -> `DELETE_RECORD` -> post-verification.
   - Expected status: `INCOMPLETE`.

3. **`syn_case_003` (NOT_APPLICABLE)**:
   - User `synth_user_03` submitted a GDPR Article 15 Subject Access Request ("Please provide an export of my account data").
   - Intent classification detects an access/export request rather than an erasure/deletion request.
   - Expected status: `NOT_APPLICABLE` with empty steps `[]`.
