"""HackerRank Orchestrate (October 2026) - Ghost Data Still Exists.

Main entry point for deterministic validation, public sample replay, and audit execution.
"""

import argparse
from pathlib import Path
import sys

# Ensure local package import works when invoked from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.loader import (
    load_deletion_requests,
    load_evidence_manifest,
    load_system_activity,
    load_user_audit_log,
)
from code.replay import replay_samples
from code.validator import OutputValidationError, validate_output_file


def run_validation(output_path: Path, expected_cases_path: Path) -> int:
    print(f"Validating output file: {output_path}")
    if not output_path.is_file():
        print(f"Error: Output file does not exist: {output_path}")
        return 1

    try:
        manifest = load_evidence_manifest("dataset/evidence_files.csv")
        activities = load_system_activity("dataset/system_activity.csv")
        audit_logs = load_user_audit_log("dataset/user_audit_log.csv")
        valid_ev_ids = (
            {e.file_id for e in manifest}
            | {a.activity_id for a in activities}
            | {u.audit_id for u in audit_logs}
        )

        expected_cases = None
        if expected_cases_path.is_file():
            requests = load_deletion_requests(expected_cases_path)
            expected_cases = [r.case_id for r in requests]

        validated = validate_output_file(
            output_path,
            expected_case_ids=expected_cases,
            valid_evidence_ids=valid_ev_ids,
        )
        print(f"Validation SUCCESS: {len(validated)} rows valid according to competition contract.")
        return 0
    except OutputValidationError as e:
        print(f"Validation FAILED: {e}")
        return 1
    except Exception as e:
        print(f"Unexpected error during validation: {e}")
        return 1


def run_replay(candidate_path: Path, sample_output_path: Path) -> int:
    print(f"Replaying candidate {candidate_path} against sample truth {sample_output_path}")
    try:
        sample_rows = validate_output_file(sample_output_path)
        candidate_rows = validate_output_file(candidate_path)

        report = replay_samples(sample_rows, candidate_rows)
        print(f"\n--- Replay Summary ---")
        print(f"Total Cases: {report.total_cases}")
        print(f"Status Matches: {report.status_matches} ({report.status_accuracy:.1%})")
        print(f"Exact Matches: {report.exact_matches} ({report.exact_match_accuracy:.1%})")

        mismatches = [r for r in report.results if not r.is_exact_match]
        if mismatches:
            print(f"\nMismatches ({len(mismatches)}):")
            for m in mismatches:
                print(f"  [{m.case_id}] Status: {m.actual_status} (exp {m.expected_status}) | Steps: {m.step_count_actual} (exp {m.step_count_expected}) | {m.explanation}")
        else:
            print("All cases match sample output exactly.")
        return 0 if report.exact_match_accuracy == 1.0 else 1
    except Exception as e:
        print(f"Replay error: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists: Audit Agent")
    parser.add_argument(
        "--mode",
        choices=["validate", "replay", "verify-samples"],
        default="verify-samples",
        help="Execution mode (default: verify-samples)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dataset/sample_output.csv"),
        help="Path to output CSV to validate or replay",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=Path("dataset/sample_deletion_requests.csv"),
        help="Path to requests CSV with expected case IDs",
    )

    args = parser.parse_args()

    if args.mode == "verify-samples":
        print("Running deterministic public-sample contract verification...")
        val_code = run_validation(Path("dataset/sample_output.csv"), Path("dataset/sample_deletion_requests.csv"))
        if val_code != 0:
            return val_code
        rep_code = run_replay(Path("dataset/sample_output.csv"), Path("dataset/sample_output.csv"))
        return rep_code
    elif args.mode == "validate":
        return run_validation(args.output, args.expected)
    elif args.mode == "replay":
        return run_replay(args.output, Path("dataset/sample_output.csv"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
