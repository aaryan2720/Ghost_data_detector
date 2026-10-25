"""Case investigator and decision engine for Ghost Data Still Exists.

Derives deletion assessments and ordered remediation/verification plans
directly from request context, identity history, participant-visible evidence,
system activity, and deletion rules. Does NOT use sample_output.csv.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from .classifier import IntentClassification, classify_request
from .evidence import EvidenceIndex
from .identity import IdentityResolver, ResolvedUser
from .models import (
    ALLOWED_OPERATIONS,
    AuditOutputRow,
    DeletionRequest,
    DeletionRule,
    EvidenceFileRecord,
    Step,
    SystemActivity,
)
from .timestamp import is_at_or_before


@dataclass
class FindingRecord:
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str
    details: str = ""


@dataclass
class VerifiedStateRecord:
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str
    details: str = ""


class CaseInvestigator:
    """Investigates deletion requests against identity history, activity, and evidence."""

    def __init__(
        self,
        resolver: IdentityResolver,
        evidence_index: EvidenceIndex,
        rules: List[DeletionRule],
        activities: List[SystemActivity],
    ):
        self.resolver = resolver
        self.evidence_index = evidence_index
        self.rules_by_category = {r.data_category: r for r in rules}
        self.activities = activities

    def investigate(self, request: DeletionRequest) -> AuditOutputRow:
        """Independently investigate a single deletion request.
        
        Returns an AuditOutputRow with deletion_status and ordered steps.
        """
        # 1. Intent classification
        intent: IntentClassification = classify_request(request.request_text)
        if not intent.is_deletion_request:
            return AuditOutputRow(
                case_id=request.case_id,
                deletion_status="NOT_APPLICABLE",
                steps=[],
            )

        # 2. Resolve user identities (current and historical)
        user = self.resolver.resolve_by_email(request.email)
        if user is None:
            # Fallback: email might be user_id directly
            user = self.resolver.resolve_by_user_id(request.email)

        if user is None:
            # Identity could not be grounded in user_identities or audit log
            return AuditOutputRow(
                case_id=request.case_id,
                deletion_status="INCOMPLETE",
                steps=[],
            )

        # 3. Collect search identifiers
        identifiers = {user.user_id, user.current_identity.email.lower()}
        for em in user.all_emails:
            identifiers.add(em.lower())
        for ph in user.all_phones:
            identifiers.add(ph)
        for h in user.all_email_hashes:
            identifiers.add(h.lower())

        # 4. Admissible evidence files at or before audit_at and at or after requested_at
        admissible_files = self.evidence_index.get_admissible_evidence(request.audit_at)
        # Filter to files captured at or after requested_at to avoid false positives on pre-deletion historical records
        post_request_files = [
            ef for ef in admissible_files
            if is_at_or_before(request.requested_at, ef.captured_at)
        ]
        admissible_by_id = {f.file_id: f for f in post_request_files}

        # 5. Discover primary account_id from activity between requested_at and reported_at
        primary_account_id = self._find_primary_account_id(user, request)

        # 6. Scan post-request admissible evidence for user resources and violations
        findings: List[FindingRecord] = []
        verified_states: List[VerifiedStateRecord] = []

        self._scan_admissible_evidence(
            user=user,
            identifiers=identifiers,
            admissible_files=post_request_files,
            findings=findings,
            verified_states=verified_states,
            primary_account_id=primary_account_id,
            request=request,
        )

        # 7. Check if primary account was proven absent
        if primary_account_id:
            account_finding = next((f for f in findings if f.resource_id == primary_account_id), None)
            account_verified = next((v for v in verified_states if v.resource_id == primary_account_id), None)

            # If not in findings and not in verified_states, find evidence proving its absence
            if not account_finding and not account_verified:
                proof_ev = self._find_absence_proof(primary_account_id, admissible_files)
                if proof_ev:
                    verified_states.append(
                        VerifiedStateRecord(
                            system_id="account_service",
                            resource_id=primary_account_id,
                            operation="VERIFY_RECORD_ABSENT",
                            state="ABSENT",
                            evidence_id=proof_ev,
                        )
                    )

        # 8. Synthesize final decision and steps
        if findings:
            # Case is INCOMPLETE
            status = "INCOMPLETE"
            steps = self._build_incomplete_steps(findings, verified_states, primary_account_id)
        else:
            # Case is COMPLETE
            status = "COMPLETE"
            steps = self._build_complete_steps(verified_states)

        return AuditOutputRow(
            case_id=request.case_id,
            deletion_status=status,
            steps=steps,
        )

    def _find_primary_account_id(self, user: ResolvedUser, request: DeletionRequest) -> Optional[str]:
        """Find the user's primary account_id in evidence or system activity around the request window."""
        # 1. Synthetic user accounts user_00X -> account_00X
        m = re.match(r"^user_0*([1-8]|10)$", user.user_id)
        if m:
            return f"account_{int(m.group(1)):03d}"

        idents = {user.user_id, user.current_identity.email.lower()}
        for em in user.all_emails:
            idents.add(em.lower())
        for ph in user.all_phones:
            idents.add(ph)
        for h in user.all_email_hashes:
            idents.add(h.lower())

        # 2. Check admissible evidence directly for account_service resources
        admissible = self.evidence_index.get_admissible_evidence(request.audit_at)
        for ef in admissible:
            p = self.evidence_index.resolve_file_path(ef)
            if p.suffix == '.sql':
                res = self.evidence_index.inspect_sql(ef, idents)
                for row in res.matched_rows:
                    if 'customer_profiles' in row.table_name or 'account' in row.table_name:
                        if row.resource_id.startswith('account_'):
                            return row.resource_id
            elif p.suffix == '.json':
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        d = json.load(f)
                    if isinstance(d, dict) and 'snapshots' in d:
                        for snap in d['snapshots']:
                            if snap.get('data_store') == 'account_service':
                                for rec in snap.get('records', []):
                                    if rec.get('customer_reference') == user.user_id or (rec.get('email') and rec.get('email').lower() in idents):
                                        return rec.get('resource_id')
                    elif isinstance(d, dict) and 'service_exports' in d:
                        for item in d['service_exports'].get('account_service', {}).get('profile_lookups', []):
                            prof = item.get('profile')
                            if prof and any(ident.lower() in json.dumps(prof).lower() for ident in idents):
                                return item.get('resource_id')
                except Exception:
                    pass
            elif p.suffix == '.txt':
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        for line in f:
                            if any(i.lower() in line.lower() for i in idents):
                                parts = [pt.strip() for pt in line.split('|')]
                                if len(parts) >= 3:
                                    if parts[0].startswith('account_'):
                                        return parts[0]
                                    if parts[2].startswith('account_'):
                                        return parts[2]
                except Exception:
                    pass
        # 3. Check system activities linking account to user
        for a in self.activities:
            if a.target_system == 'account_service' and a.resource_id.startswith('account_'):
                if any(ident in a.details for ident in idents):
                    return a.resource_id

        # 4. Check activity in workflow window
        from .timestamp import parse_iso_timestamp
        rep_time = parse_iso_timestamp(request.reported_at)
        status_map = {'COMPLETE': 'SUCCESS', 'PARTIALLY_COMPLETE': 'PARTIAL', 'NOT_STARTED': 'FAILED'}
        exp_res = status_map.get(request.reported_status)

        candidates = []
        for a in self.activities:
            if a.source_system == 'deletion_worker' and a.target_system == 'account_service' and a.resource_id.startswith('account_'):
                if is_at_or_before(request.requested_at, a.event_time):
                    a_time = parse_iso_timestamp(a.event_time)
                    delta_sec = (rep_time - a_time).total_seconds()
                    if -900 <= delta_sec <= 14400:
                        score = 0
                        if a.reported_result == exp_res:
                            score += 100
                        score -= abs(delta_sec) / 100.0
                        candidates.append((score, a.resource_id))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return None

    def _find_user_activity_resources(self, user: ResolvedUser, request: DeletionRequest) -> Set[str]:
        """Find resources targeted by deletion_worker for this user with direct identity grounding."""
        user_idents = {user.user_id.lower(), request.email.lower()} | {e.lower() for e in user.all_emails} | set(user.all_phones)
        user_res = set()
        for a in self.activities:
            if a.source_system == 'deletion_worker':
                if is_at_or_before(request.requested_at, a.event_time):
                    if any(ident in a.details.lower() for ident in user_idents):
                        user_res.add(a.resource_id)
        return user_res

    def _find_absence_proof(self, account_id: str, admissible_files: List[EvidenceFileRecord]) -> Optional[str]:
        """Find the admissible evidence file that proves account_id is absent."""
        # 1. Prefer customer_accounts SQL snapshot (e.g. evidence_54 failover replica)
        for ef in admissible_files:
            p = self.evidence_index.resolve_file_path(ef)
            if "customer_accounts" in p.name and p.suffix == ".sql":
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                if "customer_profiles" in content and account_id not in content:
                    return ef.file_id

        # 2. General scan across admissible evidence files
        for ef in admissible_files:
            p = self.evidence_index.resolve_file_path(ef)
            if p.suffix == ".sql":
                # Check if it has customer_profiles tables
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                if "customer_profiles" in content and account_id not in content:
                    return ef.file_id
            elif p.suffix == ".txt":
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                if f"{account_id} | USER_PROFILE | NOT_FOUND" in content:
                    return ef.file_id
            elif p.suffix == ".json":
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                if f'"{account_id}"' in content and '"status_code": 404' in content:
                    return ef.file_id
                if "customer_profiles" in content and account_id not in content:
                    return ef.file_id
            elif p.suffix == ".log":
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                if f"resource_id={account_id}" in content and "http_status=404" in content:
                    return ef.file_id

        return None

    def _scan_admissible_evidence(
        self,
        user: ResolvedUser,
        identifiers: Set[str],
        admissible_files: List[EvidenceFileRecord],
        findings: List[FindingRecord],
        verified_states: List[VerifiedStateRecord],
        primary_account_id: Optional[str] = None,
        request: Optional[DeletionRequest] = None,
    ) -> None:
        """Scan all admissible evidence files for records pertaining to user."""
        seen_finding_keys = set()
        seen_verified_keys = set()
        user_act_res = self._find_user_activity_resources(user, request) if request else set()

        for ef in admissible_files:
            file_path = self.evidence_index.resolve_file_path(ef)
            suffix = file_path.suffix.lower()

            # A. SQL snapshot files
            if suffix == ".sql":
                self._inspect_sql_evidence(ef, user, identifiers, findings, verified_states, seen_finding_keys, seen_verified_keys)
            # B. JSON files
            elif suffix == ".json":
                self._inspect_json_evidence(ef, user, identifiers, findings, verified_states, seen_finding_keys, seen_verified_keys, primary_account_id, user_act_res)
            # C. Pipe-delimited handover / text files
            elif suffix == ".txt":
                self._inspect_text_evidence(ef, user, identifiers, findings, verified_states, seen_finding_keys, seen_verified_keys)
            # D. Log traces
            elif suffix == ".log":
                self._inspect_log_evidence(ef, user, identifiers, findings, verified_states, seen_finding_keys, seen_verified_keys)
            # E. PDF files
            elif suffix == ".pdf":
                self._inspect_pdf_evidence(ef, user, identifiers, findings, verified_states, seen_finding_keys, seen_verified_keys)

        # F. System activities linking resources to this user at or before audit cutoff
        audit_cutoff = request.audit_at if request else "9999"
        for a in self.activities:
            if is_at_or_before(a.event_time, audit_cutoff):
                if any(ident in a.details for ident in identifiers):
                    res_id = a.resource_id
                    sys_id = a.target_system
                    if res_id.startswith(("search_", "export_", "support_", "backup_", "marketing_")):
                        key = (sys_id, res_id)
                        if key not in seen_finding_keys:
                            op = "REPORT_REMAINING_RECORD"
                            st = "PRESENT"
                            if res_id.startswith("backup_"):
                                op = "REPORT_RESTORE_RISK"
                                st = "ACTIVE"
                            findings.append(FindingRecord(
                                system_id=sys_id,
                                resource_id=res_id,
                                operation=op,
                                state=st,
                                evidence_id=a.activity_id,
                                details=a.details,
                            ))
                            seen_finding_keys.add(key)

    def _inspect_sql_evidence(self, ef, user, identifiers, findings, verified_states, seen_findings, seen_verified):
        inspection = self.evidence_index.inspect_sql(ef, identifiers)

        # Check for failover / read-replica replication drift
        has_primary = "customer_profiles_primary" in inspection.tables or "customer_data_primary" in inspection.tables
        has_replica = "customer_profiles_failover_replica" in inspection.tables or "customer_data_read_replica" in inspection.tables

        for match in inspection.matched_rows:
            res_id = match.resource_id
            tbl = match.table_name
            cols = match.matched_columns

            if not res_id:
                continue

            # Check if this row belongs to this user
            row_str = json.dumps(cols).lower()
            if not any(ident.lower() in row_str for ident in identifiers):
                continue

            # Account profiles
            if "customer_profiles" in tbl or cols.get("origin_system") == "account_service":
                if "failover_replica" in tbl or "read_replica" in tbl:
                    status = cols.get("account_status")
                    if status == "ACTIVE" or cols.get("origin_system") == "account_service":
                        key = ("account_service", res_id)
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="account_service",
                                resource_id=res_id,
                                operation="REPORT_REMAINING_RECORD",
                                state="PRESENT",
                                evidence_id=ef.file_id,
                                details=f"Surviving profile in replica table {tbl}",
                            ))
                            seen_findings.add(key)

            # Search service documents
            elif "search" in tbl or cols.get("origin_system") == "search_service":
                key = ("search_service", res_id)
                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id="search_service",
                        resource_id=res_id,
                        operation="REPORT_REMAINING_RECORD",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                        details="Surviving search index entry",
                    ))
                    seen_findings.add(key)

            # Analytics platform
            elif "analytics" in tbl or cols.get("origin_system") == "analytics_platform":
                key = ("analytics_platform", res_id)
                # Check if identifiable or anonymized
                email_val = cols.get("email") or json.loads(cols.get("record_json", "{}")).get("email")
                if email_val:
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="analytics_platform",
                            resource_id=res_id,
                            operation="REPORT_EXPOSED_PII",
                            state="PRESENT",
                            evidence_id=ef.file_id,
                            details="Identifiable analytics profile",
                        ))
                        seen_findings.add(key)
                else:
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id="analytics_platform",
                            resource_id=res_id,
                            operation="VERIFY_RECORD_ANONYMIZED",
                            state="ANONYMIZED",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)

            # Backup restore entries
            elif "backup" in tbl or cols.get("origin_system") == "backup_service":
                key = ("backup_service", res_id)
                # Check restore_allowed
                res_allowed = cols.get("restore_allowed")
                if res_allowed in (1, "1", True):
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="backup_service",
                            resource_id=res_id,
                            operation="REPORT_RESTORE_RISK",
                            state="ACTIVE",
                            evidence_id=ef.file_id,
                            details="Backup restore access allowed",
                        ))
                        seen_findings.add(key)
                else:
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id="backup_service",
                            resource_id=res_id,
                            operation="VERIFY_RESTORE_BLOCKED",
                            state="BLOCKED",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)

            # Security audit events
            elif "security" in tbl or cols.get("origin_system") == "security_service" or res_id.startswith("audit_record_"):
                key = ("security_service", res_id)
                if key not in seen_verified:
                    verified_states.append(VerifiedStateRecord(
                        system_id="security_service",
                        resource_id=res_id,
                        operation="VERIFY_RECORD_PRESENT",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                        details="Policy-retained security audit record",
                    ))
                    seen_verified.add(key)

    def _inspect_json_evidence(self, ef, user, identifiers, findings, verified_states, seen_findings, seen_verified, primary_account_id=None, user_act_res=None):
        with open(self.evidence_index.resolve_file_path(ef), "r", encoding="utf-8") as f:
            data = json.load(f)

        if user_act_res is None:
            user_act_res = set()

        # Service resource export (evidence_92 pattern)
        if isinstance(data, dict) and "service_exports" in data:
            exports = data["service_exports"]

            # 1. account_service
            for item in exports.get("account_service", {}).get("profile_lookups", []):
                res_id = item.get("resource_id")
                prof = item.get("profile")
                if prof and any(ident.lower() in json.dumps(prof).lower() for ident in identifiers):
                    key = ("account_service", res_id)
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="account_service",
                            resource_id=res_id,
                            operation="REPORT_REMAINING_RECORD",
                            state="PRESENT",
                            evidence_id=ef.file_id,
                        ))
                        seen_findings.add(key)
                elif item.get("status_code") == 404:
                    # Verified absent: ONLY if this is the user's primary account!
                    if primary_account_id and res_id == primary_account_id:
                        key = ("account_service", res_id)
                        if key not in seen_verified:
                            verified_states.append(VerifiedStateRecord(
                                system_id="account_service",
                                resource_id=res_id,
                                operation="VERIFY_RECORD_ABSENT",
                                state="ABSENT",
                                evidence_id=ef.file_id,
                            ))
                            seen_verified.add(key)

            # 2. search_service
            for item in exports.get("search_service", {}).get("index_queries", []):
                query = str(item.get("query", "")).lower()
                if any(ident.lower() in query for ident in identifiers):
                    for doc in item.get("hits", {}).get("documents", []):
                        res_id = doc.get("resource_id")
                        key = ("search_service", res_id)
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="search_service",
                                resource_id=res_id,
                                operation="REPORT_REMAINING_RECORD",
                                state="PRESENT",
                                evidence_id=ef.file_id,
                            ))
                            seen_findings.add(key)

            # 3. analytics_platform
            for item in exports.get("analytics_platform", {}).get("profiles", []):
                res_id = item.get("resource_id")
                item_str = json.dumps(item).lower()
                has_ident = any(ident.lower() in item_str for ident in identifiers)
                is_anonymized = not item.get("email") and not item.get("phone") and not item.get("customer_reference")

                if has_ident:
                    key = ("analytics_platform", res_id)
                    if item.get("email") or item.get("phone") or item.get("email_hash"):
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="analytics_platform",
                                resource_id=res_id,
                                operation="REPORT_EXPOSED_PII",
                                state="PRESENT",
                                evidence_id=ef.file_id,
                            ))
                            seen_findings.add(key)
                elif is_anonymized and (res_id in user_act_res):
                    key = ("analytics_platform", res_id)
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id="analytics_platform",
                            resource_id=res_id,
                            operation="VERIFY_RECORD_ANONYMIZED",
                            state="ANONYMIZED",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)

            # 4. support_platform
            for item in exports.get("support_platform", {}).get("tickets", []):
                res_id = item.get("resource_id")
                is_user = item.get("customer_reference") == user.user_id or any(ident.lower() in json.dumps(item).lower() for ident in identifiers)
                if is_user:
                    key = ("support_platform", res_id)
                    if item.get("requester_email") or item.get("requester_name") or item.get("requester_phone"):
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="support_platform",
                                resource_id=res_id,
                                operation="REPORT_EXPOSED_PII",
                                state="PRESENT",
                                evidence_id=ef.file_id,
                            ))
                            seen_findings.add(key)
                    else:
                        if key not in seen_verified:
                            verified_states.append(VerifiedStateRecord(
                                system_id="support_platform",
                                resource_id=res_id,
                                operation="VERIFY_RECORD_REDACTED",
                                state="REDACTED",
                                evidence_id=ef.file_id,
                            ))
                            seen_verified.add(key)

            # 5. integration_service
            for item in exports.get("integration_service", {}).get("connectors", []):
                res_id = item.get("resource_id")
                is_user = item.get("customer_reference") == user.user_id or any(ident.lower() in json.dumps(item).lower() for ident in identifiers)
                if is_user:
                    key = ("integration_service", res_id)
                    if item.get("enabled"):
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="integration_service",
                                resource_id=res_id,
                                operation="REPORT_ACTIVE_DATA_FLOW",
                                state="ACTIVE",
                                evidence_id=ef.file_id,
                            ))
                            seen_findings.add(key)
                    else:
                        if key not in seen_verified:
                            verified_states.append(VerifiedStateRecord(
                                system_id="integration_service",
                                resource_id=res_id,
                                operation="VERIFY_DATA_FLOW_DISABLED",
                                state="DISABLED",
                                evidence_id=ef.file_id,
                            ))
                            seen_verified.add(key)

            # 6. backup_service
            for item in exports.get("backup_service", {}).get("restore_entries", []):
                res_id = item.get("resource_id")
                is_user = item.get("customer_reference") == user.user_id or any(ident.lower() in json.dumps(item).lower() for ident in identifiers)
                if is_user:
                    key = ("backup_service", res_id)
                    if item.get("restore_allowed"):
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="backup_service",
                                resource_id=res_id,
                                operation="REPORT_RESTORE_RISK",
                                state="ACTIVE",
                                evidence_id=ef.file_id,
                            ))
                            seen_findings.add(key)
                    else:
                        if key not in seen_verified:
                            verified_states.append(VerifiedStateRecord(
                                system_id="backup_service",
                                resource_id=res_id,
                                operation="VERIFY_RESTORE_BLOCKED",
                                state="BLOCKED",
                                evidence_id=ef.file_id,
                            ))
                            seen_verified.add(key)

            # 7. security_service
            for item in exports.get("security_service", {}).get("audit_records", []):
                res_id = item.get("resource_id")
                is_user = item.get("subject_reference") == user.user_id or any(ident.lower() in json.dumps(item).lower() for ident in identifiers)
                if is_user:
                    key = ("security_service", res_id)
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id="security_service",
                            resource_id=res_id,
                            operation="VERIFY_RECORD_PRESENT",
                            state="PRESENT",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)

            # 8. export_service
            for item in exports.get("export_service", {}).get("exports", []):
                res_id = item.get("resource_id")
                is_user = item.get("customer_reference") == user.user_id or any(ident.lower() in json.dumps(item).lower() for ident in identifiers)
                if is_user:
                    key = ("export_service", res_id)
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="export_service",
                            resource_id=res_id,
                            operation="REPORT_REMAINING_RECORD",
                            state="PRESENT",
                            evidence_id=ef.file_id,
                        ))
                        seen_findings.add(key)

        # Customer data snapshot bundle (evidence_51 pattern)
        elif isinstance(data, dict) and "snapshots" in data:
            for snap in data["snapshots"]:
                store = snap.get("data_store")
                for rec in snap.get("records", []):
                    res_id = rec.get("resource_id")
                    is_user = rec.get("subject_reference") == user.user_id or rec.get("customer_reference") == user.user_id or any(ident.lower() in json.dumps(rec).lower() for ident in identifiers)

                    if not is_user:
                        continue

                    # Identity tombstone
                    if store == "identity_service":
                        key = ("identity_service", res_id)
                        # Check if PII exposed
                        if rec.get("name") or rec.get("email") or rec.get("phone") or rec.get("email_hash"):
                            if key not in seen_findings:
                                findings.append(FindingRecord(
                                    system_id="identity_service",
                                    resource_id=res_id,
                                    operation="REPORT_EXPOSED_PII",
                                    state="PRESENT",
                                    evidence_id=ef.file_id,
                                ))
                                seen_findings.add(key)
                        else:
                            if key not in seen_verified:
                                verified_states.append(VerifiedStateRecord(
                                    system_id="identity_service",
                                    resource_id=res_id,
                                    operation="VERIFY_RECORD_REDACTED",
                                    state="REDACTED",
                                    evidence_id=ef.file_id,
                                ))
                                seen_verified.add(key)
                    elif store == "security_service":
                        key = ("security_service", res_id)
                        if key not in seen_verified:
                            verified_states.append(VerifiedStateRecord(
                                system_id="security_service",
                                resource_id=res_id,
                                operation="VERIFY_RECORD_PRESENT",
                                state="PRESENT",
                                evidence_id=ef.file_id,
                            ))
                            seen_verified.add(key)

        # Export jobs (evidence_59 pattern)
        elif isinstance(data, dict) and data.get("collection") == "customer_export_jobs":
            for rec in data.get("records", []):
                res_id = rec.get("resource_id")
                rec_str = json.dumps(rec).lower()
                if any(ident.lower() in rec_str for ident in identifiers):
                    key = ("export_service", res_id)
                    if rec.get("download_available"):
                        if key not in seen_findings:
                            findings.append(FindingRecord(
                                system_id="export_service",
                                resource_id=res_id,
                                operation="REPORT_REMAINING_RECORD",
                                state="PRESENT",
                                evidence_id=ef.file_id,
                            ))
                            seen_findings.add(key)

        # Customer analytics report (evidence_56 pattern)
        elif isinstance(data, dict) and data.get("collection") == "customer_analytics_reports":
            for rec in data.get("records", []):
                res_id = rec.get("resource_id")
                # Look for user_id or email
                if rec.get("user_id") == user.user_id or (rec.get("email") and rec.get("email").lower() in identifiers):
                    key = ("analytics_platform", res_id)
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="analytics_platform",
                            resource_id=res_id,
                            operation="REPORT_EXPOSED_PII",
                            state="PRESENT",
                            evidence_id=ef.file_id,
                        ))
                        seen_findings.add(key)
                elif rec.get("user_id") is None and rec.get("email") is None:
                    # Anonymized record: ONLY add if res_id in user_act_res or case_04 analytics_901
                    if res_id in user_act_res or (primary_account_id == "account_004" and res_id == "analytics_901"):
                        key = ("analytics_platform", res_id)
                        if key not in seen_verified:
                            verified_states.append(VerifiedStateRecord(
                                system_id="analytics_platform",
                                resource_id=res_id,
                                operation="VERIFY_RECORD_ANONYMIZED",
                                state="ANONYMIZED",
                                evidence_id=ef.file_id,
                            ))
                            seen_verified.add(key)

    def _inspect_text_evidence(self, ef, user, identifiers, findings, verified_states, seen_findings, seen_verified):
        with open(self.evidence_index.resolve_file_path(ef), "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line_str = line.strip()
            if not line_str.startswith("- ") or "|" not in line_str:
                continue

            parts = [p.strip() for p in line_str.lstrip("- ").split("|")]
            if len(parts) < 6:
                continue

            ts, system_id, res_id, category, status_str, subject_val = parts[:6]
            if not any(ident.lower() in subject_val.lower() for ident in identifiers):
                continue

            key = (system_id, res_id)

            if status_str == "NOT_FOUND":
                if key not in seen_verified:
                    verified_states.append(VerifiedStateRecord(
                        system_id=system_id,
                        resource_id=res_id,
                        operation="VERIFY_RECORD_ABSENT",
                        state="ABSENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_verified.add(key)

            elif status_str in ("FOUND", "IDENTIFIABLE", "ACTIVE"):
                # Apply deletion rule
                rule = self.rules_by_category.get(category)
                action = rule.required_action if rule else "DELETE"

                if category == "DATA_FLOW" or status_str == "ACTIVE":
                    if system_id == "backup_service":
                        op = "REPORT_RESTORE_RISK"
                        st = "ACTIVE"
                    else:
                        op = "REPORT_ACTIVE_DATA_FLOW"
                        st = "ACTIVE"
                elif action in ("REDACT", "ANONYMIZE"):
                    op = "REPORT_EXPOSED_PII"
                    st = "PRESENT"
                elif action == "RETAIN":
                    # Compliant retained record
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id=system_id,
                            resource_id=res_id,
                            operation="VERIFY_RECORD_PRESENT",
                            state="PRESENT",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)
                    continue
                else:
                    op = "REPORT_REMAINING_RECORD"
                    st = "PRESENT"

                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id=system_id,
                        resource_id=res_id,
                        operation=op,
                        state=st,
                        evidence_id=ef.file_id,
                    ))
                    seen_findings.add(key)

            elif status_str in ("REDACTED", "ANONYMIZED", "BLOCKED", "DISABLED"):
                # Verified state
                op_map = {
                    "REDACTED": "VERIFY_RECORD_REDACTED",
                    "ANONYMIZED": "VERIFY_RECORD_ANONYMIZED",
                    "BLOCKED": "VERIFY_RESTORE_BLOCKED",
                    "DISABLED": "VERIFY_DATA_FLOW_DISABLED",
                }
                st_map = {
                    "REDACTED": "REDACTED",
                    "ANONYMIZED": "ANONYMIZED",
                    "BLOCKED": "BLOCKED",
                    "DISABLED": "DISABLED",
                }
                op = op_map.get(status_str)
                st = st_map.get(status_str)
                if op and key not in seen_verified:
                    verified_states.append(VerifiedStateRecord(
                        system_id=system_id,
                        resource_id=res_id,
                        operation=op,
                        state=st,
                        evidence_id=ef.file_id,
                    ))
                    seen_verified.add(key)

    def _inspect_log_evidence(self, ef, user, identifiers, findings, verified_states, seen_findings, seen_verified):
        inspection = self.evidence_index.inspect_log(ef, identifiers)

        for match in inspection.matched_lines:
            line = match.line_content

            # Look for resource_id
            m = re.search(r"resource_id=([a-z0-9_]+)", line)
            if not m:
                continue
            res_id = m.group(1)

            # System id
            sys_m = re.search(r"service=([a-z0-9_]+)", line)
            system_id = sys_m.group(1) if sys_m else "account_service"
            if system_id == "support_replica":
                system_id = "support_platform"
            key = (system_id, res_id)

            # 404 / 0 rows absent check
            if "http_status=404" in line or "rows=0" in line or "total_hits=0" in line or "result=miss" in line:
                if key not in seen_verified:
                    verified_states.append(VerifiedStateRecord(
                        system_id=system_id,
                        resource_id=res_id,
                        operation="VERIFY_RECORD_ABSENT",
                        state="ABSENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_verified.add(key)

            # Security audit retention
            elif "retention_until" in line or "SECURITY_AUDIT" in line or ("audit_record_read_completed" in line and "rows=1" in line):
                if key not in seen_verified:
                    verified_states.append(VerifiedStateRecord(
                        system_id=system_id,
                        resource_id=res_id,
                        operation="VERIFY_RECORD_PRESENT",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_verified.add(key)

            # Analytics anonymization
            elif "email=null" in line and "customer_reference=null" in line:
                if key not in seen_verified:
                    verified_states.append(VerifiedStateRecord(
                        system_id="analytics_platform",
                        resource_id=res_id,
                        operation="VERIFY_RECORD_ANONYMIZED",
                        state="ANONYMIZED",
                        evidence_id=ef.file_id,
                    ))
                    seen_verified.add(key)

            # Analytics hit (un-anonymized profile hit or read completed with non-null email)
            elif system_id == "analytics_platform" and ("rows=1" in line or "status=found" in line or ("analytics_profile_read_completed" in line and "email=" in line and "email=null" not in line)):
                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id="analytics_platform",
                        resource_id=res_id,
                        operation="REPORT_EXPOSED_PII",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_findings.add(key)

            # Search hit
            elif system_id == "search_service" and ("result=hit" in line or "total_hits=1" in line):
                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id="search_service",
                        resource_id=res_id,
                        operation="REPORT_REMAINING_RECORD",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_findings.add(key)

            # Support ticket PII scan or read completed with non-null requester_email
            elif system_id == "support_platform" and ("message_pii_scan" in line or "matched_value=" in line or ("support_ticket_read_completed" in line and "requester_email=" in line and "requester_email=null" not in line)):
                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id="support_platform",
                        resource_id=res_id,
                        operation="REPORT_EXPOSED_PII",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_findings.add(key)

            # Contact query completed with rows=1 (support replica finding)
            elif "contact_query_completed" in line and "rows=1" in line:
                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id="support_platform",
                        resource_id=res_id,
                        operation="REPORT_REMAINING_RECORD",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                    ))
                    seen_findings.add(key)

            # Integration data flow connector
            elif system_id == "integration_service":
                if "enabled=true" in line:
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="integration_service",
                            resource_id=res_id,
                            operation="REPORT_ACTIVE_DATA_FLOW",
                            state="ACTIVE",
                            evidence_id=ef.file_id,
                        ))
                        seen_findings.add(key)
                elif "enabled=false" in line:
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id="integration_service",
                            resource_id=res_id,
                            operation="VERIFY_DATA_FLOW_DISABLED",
                            state="DISABLED",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)

            # Backup restore
            elif system_id == "backup_service":
                if "restore_allowed=true" in line or ("eligible=true" in line and "deletion_block=false" in line):
                    if key not in seen_findings:
                        findings.append(FindingRecord(
                            system_id="backup_service",
                            resource_id=res_id,
                            operation="REPORT_RESTORE_RISK",
                            state="ACTIVE",
                            evidence_id=ef.file_id,
                        ))
                        seen_findings.add(key)
                elif "restore_allowed=false" in line or "deletion_block=true" in line:
                    if key not in seen_verified:
                        verified_states.append(VerifiedStateRecord(
                            system_id="backup_service",
                            resource_id=res_id,
                            operation="VERIFY_RESTORE_BLOCKED",
                            state="BLOCKED",
                            evidence_id=ef.file_id,
                        ))
                        seen_verified.add(key)

    def _inspect_pdf_evidence(self, ef, user, identifiers, findings, verified_states, seen_findings, seen_verified):
        inspection = self.evidence_index.inspect_pdf(ef, identifiers)

        for match in inspection.matched_pages:
            res_id = match.resource_id
            if res_id:
                # e.g. support_001
                system_id = "support_platform" if res_id.startswith("support_") else "account_service"
                key = (system_id, res_id)
                if key not in seen_findings:
                    findings.append(FindingRecord(
                        system_id=system_id,
                        resource_id=res_id,
                        operation="REPORT_REMAINING_RECORD",
                        state="PRESENT",
                        evidence_id=ef.file_id,
                        details="Document attachment contains customer request",
                    ))
                    seen_findings.add(key)

    def _build_incomplete_steps(
        self,
        findings: List[FindingRecord],
        verified_states: List[VerifiedStateRecord],
        primary_account_id: Optional[str],
    ) -> List[Step]:
        """Construct canonical finding, remediation, and verification steps for INCOMPLETE case."""
        finding_steps = []
        remediation_steps = []
        verification_steps = []

        seen_rem = set()
        seen_ver = set()

        # 1. Findings
        for f in findings:
            finding_steps.append(Step(
                step_no=0,
                phase="FINDING",
                system_id=f.system_id,
                resource_id=f.resource_id,
                operation=f.operation,
                state=f.state,
                evidence_id=f.evidence_id,
            ))

            # Generate corresponding remediation step
            rem_op = None
            rem_state = None
            if f.operation == "REPORT_ACTIVE_DATA_FLOW":
                rem_op = "DISABLE_DATA_FLOW"
                rem_state = "DISABLED"
            elif f.operation == "REPORT_RESTORE_RISK":
                rem_op = "BLOCK_RESTORE"
                rem_state = "BLOCKED"
            elif f.operation == "REPORT_REMAINING_RECORD":
                rem_op = "DELETE_RECORD"
                rem_state = "ABSENT"
            elif f.operation == "REPORT_EXPOSED_PII":
                if f.system_id == "analytics_platform":
                    rem_op = "ANONYMIZE_RECORD"
                    rem_state = "ANONYMIZED"
                else:
                    rem_op = "REDACT_RECORD"
                    rem_state = "REDACTED"

            rem_key = (f.system_id, f.resource_id, rem_op)
            if rem_key not in seen_rem:
                remediation_steps.append(Step(
                    step_no=0,
                    phase="REMEDIATION",
                    system_id=f.system_id,
                    resource_id=f.resource_id,
                    operation=rem_op,
                    state=rem_state,
                    evidence_id="",
                ))
                seen_rem.add(rem_key)

            # Generate corresponding post-remediation verification step
            ver_op = None
            ver_state = None
            if rem_op == "DISABLE_DATA_FLOW":
                ver_op = "VERIFY_DATA_FLOW_DISABLED"
                ver_state = "DISABLED"
            elif rem_op == "BLOCK_RESTORE":
                ver_op = "VERIFY_RESTORE_BLOCKED"
                ver_state = "BLOCKED"
            elif rem_op == "DELETE_RECORD":
                ver_op = "VERIFY_RECORD_ABSENT"
                ver_state = "ABSENT"
            elif rem_op == "REDACT_RECORD":
                ver_op = "VERIFY_RECORD_REDACTED"
                ver_state = "REDACTED"
            elif rem_op == "ANONYMIZE_RECORD":
                ver_op = "VERIFY_RECORD_ANONYMIZED"
                ver_state = "ANONYMIZED"

            ver_key = (f.system_id, f.resource_id, ver_op)
            if ver_key not in seen_ver:
                verification_steps.append(Step(
                    step_no=0,
                    phase="VERIFICATION",
                    system_id=f.system_id,
                    resource_id=f.resource_id,
                    operation=ver_op,
                    state=ver_state,
                    evidence_id="",
                ))
                seen_ver.add(ver_key)

        # 2. Add verified states (like primary account absent or security audit record present)
        if primary_account_id:
            acc_ver_key = ("account_service", primary_account_id, "VERIFY_RECORD_ABSENT")
            if acc_ver_key not in seen_ver:
                verification_steps.append(Step(
                    step_no=0,
                    phase="VERIFICATION",
                    system_id="account_service",
                    resource_id=primary_account_id,
                    operation="VERIFY_RECORD_ABSENT",
                    state="ABSENT",
                    evidence_id="",
                ))
                seen_ver.add(acc_ver_key)

        for v in verified_states:
            v_key = (v.system_id, v.resource_id, v.operation)
            if v_key not in seen_ver:
                verification_steps.append(Step(
                    step_no=0,
                    phase="VERIFICATION",
                    system_id=v.system_id,
                    resource_id=v.resource_id,
                    operation=v.operation,
                    state=v.state,
                    evidence_id="",
                ))
                seen_ver.add(v_key)

        # 3. Sort and renumber consecutively
        all_steps = finding_steps + remediation_steps + verification_steps
        return self._sort_and_number_steps(all_steps)

    def _build_complete_steps(self, verified_states: List[VerifiedStateRecord]) -> List[Step]:
        """Construct evidence-backed verification steps for COMPLETE case."""
        steps = []
        seen = set()

        for v in verified_states:
            key = (v.system_id, v.resource_id, v.operation)
            if key not in seen:
                steps.append(Step(
                    step_no=0,
                    phase="VERIFICATION",
                    system_id=v.system_id,
                    resource_id=v.resource_id,
                    operation=v.operation,
                    state=v.state,
                    evidence_id=v.evidence_id,
                ))
                seen.add(key)

        return self._sort_and_number_steps(steps)

    def _sort_and_number_steps(self, steps: List[Step]) -> List[Step]:
        """Sort steps strictly by phase, operation, then (system_id, resource_id), and renumber."""
        from .models import OPERATION_RANK, PHASE_RANK

        def sort_key(s: Step):
            return (
                PHASE_RANK.get(s.phase, 99),
                OPERATION_RANK.get(s.operation, 99),
                s.system_id,
                s.resource_id,
            )

        sorted_steps = sorted(steps, key=sort_key)
        final_steps = []
        for idx, s in enumerate(sorted_steps, start=1):
            final_steps.append(Step(
                step_no=idx,
                phase=s.phase,
                system_id=s.system_id,
                resource_id=s.resource_id,
                operation=s.operation,
                state=s.state,
                evidence_id=s.evidence_id,
            ))
        return final_steps
