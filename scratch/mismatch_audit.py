import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

dataset_dir = "dataset"
identities = load_user_identities(f"{dataset_dir}/user_identities.csv")
audit = load_user_audit_log(f"{dataset_dir}/user_audit_log.csv")
rules = load_deletion_rules(f"{dataset_dir}/deletion_rules.csv")
activities = load_system_activity(f"{dataset_dir}/system_activity.csv")
ev_index = EvidenceIndex(f"{dataset_dir}/evidence_files.csv", dataset_dir)
resolver = IdentityResolver(identities, audit)

investigator = CaseInvestigator(resolver, ev_index, rules, activities)
sample_requests = load_deletion_requests("dataset/sample_deletion_requests.csv")

sample_out_rows = validate_output_file("dataset/sample_output.csv")
expected_rows = {r["case_id"]: r for r in sample_out_rows}

mismatches = []
for req in sample_requests:
    cid = req.case_id
    exp = expected_rows[cid]
    exp_steps = exp["steps"]
    res = investigator.investigate(req)
    gen_steps = json.loads(res.steps_json())
    if gen_steps != exp_steps or res.deletion_status != exp["deletion_status"]:
        mismatches.append((cid, exp["deletion_status"], res.deletion_status, exp_steps, gen_steps))

lines = []
lines.append(f"Total mismatches: {len(mismatches)}")
for cid, exp_st, gen_st, exp_steps, gen_steps in mismatches:
    lines.append(f"\n==========================================")
    lines.append(f"=== Case: {cid} (Status Exp: {exp_st}, Gen: {gen_st}) ===")
    lines.append(f"  Exp steps ({len(exp_steps)}):")
    for s in exp_steps:
        lines.append(f"    [{s['phase']}] {s['system_id']}:{s['resource_id']} {s['operation']} -> {s['state']} (ev: {s.get('evidence_id')})")
    lines.append(f"  Gen steps ({len(gen_steps)}):")
    for s in gen_steps:
        lines.append(f"    [{s['phase']}] {s['system_id']}:{s['resource_id']} {s['operation']} -> {s['state']} (ev: {s.get('evidence_id')})")

with open("scratch/mismatch_details.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Wrote scratch/mismatch_details.txt in utf-8")
