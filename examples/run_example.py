#!/usr/bin/env python3
"""Host Data Detector - Example Runner

Demonstrates running the deletion audit investigator on synthetic data fixtures.
"""

from pathlib import Path
import sys

# Add repository root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

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
from code.validator import validate_output_file


def main() -> None:
    data_dir = ROOT_DIR / "examples" / "synthetic_data"
    output_path = ROOT_DIR / "examples" / "synthetic_output.csv"
    requests_path = data_dir / "deletion_requests.csv"

    print("=" * 60)
    print("HOST DATA DETECTOR - SYNTHETIC AUDIT DEMONSTRATION")
    print("=" * 60)
    print(f"Loading synthetic data from: {data_dir}")

    # Load fixtures
    identities = load_user_identities(str(data_dir / "user_identities.csv"))
    audit_logs = load_user_audit_log(str(data_dir / "user_audit_log.csv"))
    rules = load_deletion_rules(str(data_dir / "deletion_rules.csv"))
    activities = load_system_activity(str(data_dir / "system_activity.csv"))
    manifest = load_evidence_manifest(str(data_dir / "evidence_files.csv"))
    ev_index = EvidenceIndex(str(data_dir / "evidence_files.csv"), str(data_dir))
    resolver = IdentityResolver(identities, audit_logs)

    investigator = CaseInvestigator(resolver, ev_index, rules, activities)
    requests = load_deletion_requests(requests_path)

    print(f"\nProcessing {len(requests)} synthetic cases...")
    rows = []
    for req in requests:
        audit_row = investigator.investigate(req)
        print(f"  [{audit_row.case_id}] Status: {audit_row.deletion_status} | Steps: {len(audit_row.steps)}")
        for step in audit_row.steps:
            ev_label = f" (ev: {step.evidence_id})" if step.evidence_id else ""
            print(f"    - Step {step.step_no}: [{step.phase}] {step.system_id}:{step.resource_id} -> {step.operation} [{step.state}]{ev_label}")
        rows.append(audit_row)

    # Write output CSV
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write("case_id,deletion_status,steps_json\n")
        for r in rows:
            f.write(f'{r.case_id},{r.deletion_status},"{r.steps_json().replace(chr(34), chr(34)+chr(34))}"\n')

    print(f"\nResults written to: {output_path}")

    # Validate generated output
    valid_ev_ids = (
        {e.file_id for e in manifest}
        | {a.activity_id for a in activities}
        | {u.audit_id for u in audit_logs}
    )
    expected_case_ids = [r.case_id for r in requests]
    validated = validate_output_file(
        output_path,
        expected_case_ids=expected_case_ids,
        valid_evidence_ids=valid_ev_ids,
    )
    print(f"Contract Validation: SUCCESS ({len(validated)} rows valid)")
    print("=" * 60)


if __name__ == "__main__":
    main()
