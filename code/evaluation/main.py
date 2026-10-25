"""Evaluation script for Ghost Data Still Exists.

Maintains strict separation between:
1. Validator & Diff Engine Self-Consistency (Fixture Replay Baseline)
2. Independent Model/Investigator Prediction Accuracy (Evaluated without sample_output.csv access)
3. External Predictions Evaluation
"""

import argparse
from pathlib import Path
import sys
from typing import Dict, List, Optional

# Ensure local package import works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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
from code.replay import ReplayReport, replay_samples
from code.validator import validate_output_file


def compute_metrics(truth_rows: List[Dict], pred_rows: List[Dict]) -> Dict:
    """Compute status, exact match, step count, and field-level metrics."""
    report = replay_samples(truth_rows, pred_rows)

    total_steps_truth = sum(len(r["steps"]) for r in truth_rows)
    total_steps_pred = sum(len(r["steps"]) for r in pred_rows)

    total_fields_checked = 0
    total_field_matches = 0

    fields = ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]
    pred_by_id = {r["case_id"]: r["steps"] for r in pred_rows}

    for t in truth_rows:
        cid = t["case_id"]
        t_steps = t["steps"]
        p_steps = pred_by_id.get(cid, [])
        for i in range(min(len(t_steps), len(p_steps))):
            for f in fields:
                total_fields_checked += 1
                if t_steps[i].get(f) == p_steps[i].get(f):
                    total_field_matches += 1

    field_acc = total_field_matches / total_fields_checked if total_fields_checked else 0.0

    return {
        "report": report,
        "total_cases": report.total_cases,
        "status_matches": report.status_matches,
        "status_accuracy": report.status_accuracy,
        "exact_matches": report.exact_matches,
        "exact_match_accuracy": report.exact_match_accuracy,
        "truth_steps": total_steps_truth,
        "pred_steps": total_steps_pred,
        "fields_checked": total_fields_checked,
        "field_matches": total_field_matches,
        "field_accuracy": field_acc,
    }


def print_metrics_summary(title: str, metrics: Dict):
    print("=" * 65)
    print(title)
    print("=" * 65)
    print(f"Total Cases:                   {metrics['total_cases']}")
    print(f"Case-level Status Matches:     {metrics['status_matches']} / {metrics['total_cases']} ({metrics['status_accuracy']:.2%})")
    print(f"Exact Case Matches (Full Row): {metrics['exact_matches']} / {metrics['total_cases']} ({metrics['exact_match_accuracy']:.2%})")
    print(f"Truth Step Count:              {metrics['truth_steps']}")
    print(f"Pred Step Count:               {metrics['pred_steps']}")
    print(f"Field-level Accuracy:          {metrics['field_matches']} / {metrics['fields_checked']} ({metrics['field_accuracy']:.2%})")
    print("=" * 65)


def run_fixture_replay_baseline(sample_output_path: Path):
    """Replays known fixture against itself to verify validator and diff engine.
    
    This is explicitly NOT a model accuracy evaluation.
    """
    print(f"[FIXTURE REPLAY] Validating self-consistency of {sample_output_path}...")
    sample_rows = validate_output_file(sample_output_path)
    metrics = compute_metrics(sample_rows, sample_rows)
    print_metrics_summary("FIXTURE REPLAY: VALIDATOR & DIFF BASELINE (NOT MODEL ACCURACY)", metrics)
    return metrics


def run_independent_investigator_evaluation(
    requests_path: Path,
    truth_output_path: Path,
    dataset_dir: str = "dataset",
) -> Dict:
    """Runs genuine CaseInvestigator without reading truth_output_path, then evaluates predictions."""
    print(f"[INDEPENDENT INVESTIGATION] Loading participant context from {dataset_dir}...")
    identities = load_user_identities(f"{dataset_dir}/user_identities.csv")
    audit = load_user_audit_log(f"{dataset_dir}/user_audit_log.csv")
    rules = load_deletion_rules(f"{dataset_dir}/deletion_rules.csv")
    activities = load_system_activity(f"{dataset_dir}/system_activity.csv")
    ev_index = EvidenceIndex(f"{dataset_dir}/evidence_files.csv", dataset_dir)
    resolver = IdentityResolver(identities, audit)

    investigator = CaseInvestigator(resolver, ev_index, rules, activities)
    requests = load_deletion_requests(requests_path)

    print(f"[INDEPENDENT INVESTIGATION] Generating predictions for {len(requests)} cases (WITHOUT reading truth)...")
    pred_rows = []
    for req in requests:
        audit_row = investigator.investigate(req)
        pred_rows.append({
            "case_id": audit_row.case_id,
            "deletion_status": audit_row.deletion_status,
            "steps": [s.to_dict() for s in audit_row.steps],
        })

    print(f"[INDEPENDENT INVESTIGATION] Comparing generated predictions against ground truth {truth_output_path}...")
    truth_rows = validate_output_file(truth_output_path)
    metrics = compute_metrics(truth_rows, pred_rows)
    print_metrics_summary("INDEPENDENT INVESTIGATOR ACCURACY (GENUINE PREDICTION)", metrics)

    # Discrepancy breakdown
    report: ReplayReport = metrics["report"]
    mismatches = [r for r in report.results if not r.is_exact_match]
    if mismatches:
        print(f"\nDiscrepancies ({len(mismatches)} cases):")
        for m in mismatches:
            status_tag = "STATUS_MATCH" if m.status_match else "STATUS_DIFF"
            print(f"  [{m.case_id}] ({status_tag}) Actual: {m.actual_status} | Exp: {m.expected_status} | Steps: act={m.step_count_actual}, exp={m.step_count_expected} | {m.explanation}")

    return metrics


def evaluate_custom_predictions(predictions_path: Path, truth_path: Path):
    """Evaluates an external prediction CSV against a ground truth CSV."""
    print(f"[EVALUATION] Comparing {predictions_path} against {truth_path}...")
    pred_rows = validate_output_file(predictions_path)
    truth_rows = validate_output_file(truth_path)
    metrics = compute_metrics(truth_rows, pred_rows)
    print_metrics_summary("CUSTOM PREDICTIONS EVALUATION", metrics)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Evaluate Ghost Data Still Exists predictions")
    parser.add_argument(
        "--mode",
        choices=["investigator", "fixture-replay", "custom"],
        default="investigator",
        help="Evaluation mode (default: investigator)",
    )
    parser.add_argument(
        "--requests",
        type=Path,
        default=Path("dataset/sample_deletion_requests.csv"),
        help="Requests file to evaluate",
    )
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("dataset/sample_output.csv"),
        help="Ground truth CSV for scoring",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Predictions CSV to score (for --mode custom)",
    )

    args = parser.parse_args()

    if args.mode == "investigator":
        run_independent_investigator_evaluation(args.requests, args.truth)
    elif args.mode == "fixture-replay":
        run_fixture_replay_baseline(args.truth)
    elif args.mode == "custom":
        if not args.predictions:
            print("Error: --predictions path required for custom mode")
            sys.exit(1)
        evaluate_custom_predictions(args.predictions, args.truth)


if __name__ == "__main__":
    main()
