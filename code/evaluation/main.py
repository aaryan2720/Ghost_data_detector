"""Evaluation script for Ghost Data Still Exists.

Computes case-level, step-level, field-level, and sequence accuracy metrics.
"""

import argparse
from pathlib import Path
import sys

# Ensure local package import works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from code.replay import replay_samples
from code.validator import validate_output_file


def evaluate(predictions_path: Path, ground_truth_path: Path):
    print(f"Evaluating {predictions_path} against {ground_truth_path}...")
    pred_rows = validate_output_file(predictions_path)
    truth_rows = validate_output_file(ground_truth_path)

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

    print("=" * 60)
    print("EVALUATION METRICS SUMMARY")
    print("=" * 60)
    print(f"Total Cases:                   {report.total_cases}")
    print(f"Case-level Status Matches:     {report.status_matches} / {report.total_cases} ({report.status_accuracy:.2%})")
    print(f"Exact Case Matches (Full Row): {report.exact_matches} / {report.total_cases} ({report.exact_match_accuracy:.2%})")
    print(f"Truth Step Count:              {total_steps_truth}")
    print(f"Pred Step Count:               {total_steps_pred}")
    print(f"Field-level Accuracy:          {total_field_matches} / {total_fields_checked} ({field_acc:.2%})")
    print("=" * 60)

    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate Ghost Data Still Exists predictions")
    parser.add_argument("--predictions", type=Path, default=Path("dataset/sample_output.csv"))
    parser.add_argument("--truth", type=Path, default=Path("dataset/sample_output.csv"))
    args = parser.parse_args()

    evaluate(args.predictions, args.truth)


if __name__ == "__main__":
    main()
