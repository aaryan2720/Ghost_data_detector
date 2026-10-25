"""CSV loading and schema validation with strict UTF-8 handling and actionable errors."""

import csv
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import (
    DeletionRequest,
    DeletionRule,
    EvidenceFileRecord,
    SystemActivity,
    UserAuditEntry,
    UserIdentity,
)


class LoaderError(Exception):
    """Base exception for data loading errors."""
    pass


class SchemaValidationError(LoaderError):
    """Raised when CSV header is missing required columns."""
    pass


class DuplicateIdentifierError(LoaderError):
    """Raised when a unique identifier appears multiple times."""
    pass


class MissingIdentifierError(LoaderError):
    """Raised when a required identifier column contains an empty or null value."""
    pass


def _read_csv_rows(file_path: Path | str, required_cols: List[str]) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read CSV file with strict utf-8 encoding and validate header."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise SchemaValidationError(f"File {path} is empty; missing header {required_cols}")

        clean_header = [col.strip() for col in header]
        missing = [c for c in required_cols if c not in clean_header]
        if missing:
            raise SchemaValidationError(
                f"File {path.name} missing required columns: {missing}. Present: {clean_header}"
            )

        rows = []
        for line_no, row in enumerate(reader, start=2):
            if not row or all(c.strip() == "" for c in row):
                continue
            if len(row) != len(clean_header):
                raise SchemaValidationError(
                    f"File {path.name}:{line_no}: Column count mismatch: expected {len(clean_header)}, got {len(row)} ({row})"
                )
            row_dict = {col: val.strip() for col, val in zip(clean_header, row)}
            rows.append(row_dict)

    return clean_header, rows


def load_deletion_requests(file_path: Path | str) -> List[DeletionRequest]:
    """Load deletion requests (sample or full).
    
    Required columns:
      case_id, email, requested_at, reported_status, reported_at, audit_at, request_text
    """
    req_cols = ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"]
    _, rows = _read_csv_rows(file_path, req_cols)

    seen_ids: Set[str] = set()
    requests: List[DeletionRequest] = []
    for idx, r in enumerate(rows, start=2):
        cid = r["case_id"]
        if not cid:
            raise MissingIdentifierError(f"Row {idx} in {file_path} has missing case_id")
        if cid in seen_ids:
            raise DuplicateIdentifierError(f"Duplicate case_id '{cid}' in {file_path} at row {idx}")
        seen_ids.add(cid)

        requests.append(
            DeletionRequest(
                case_id=cid,
                email=r["email"],
                requested_at=r["requested_at"],
                reported_status=r["reported_status"],
                reported_at=r["reported_at"],
                audit_at=r["audit_at"],
                request_text=r["request_text"],
            )
        )
    return requests


def load_user_identities(file_path: Path | str) -> List[UserIdentity]:
    """Load user identity snapshot.
    
    Required columns:
      user_id, name, email, phone, email_hash, updated_at
    """
    req_cols = ["user_id", "name", "email", "phone", "email_hash", "updated_at"]
    _, rows = _read_csv_rows(file_path, req_cols)

    seen_ids: Set[str] = set()
    identities: List[UserIdentity] = []
    for idx, r in enumerate(rows, start=2):
        uid = r["user_id"]
        if not uid:
            raise MissingIdentifierError(f"Row {idx} in {file_path} has missing user_id")
        if uid in seen_ids:
            raise DuplicateIdentifierError(f"Duplicate user_id '{uid}' in {file_path} at row {idx}")
        seen_ids.add(uid)

        identities.append(
            UserIdentity(
                user_id=uid,
                name=r["name"],
                email=r["email"],
                phone=r["phone"],
                email_hash=r["email_hash"],
                updated_at=r["updated_at"],
            )
        )
    return identities


def load_user_audit_log(file_path: Path | str) -> List[UserAuditEntry]:
    """Load user identity audit log.
    
    Required columns:
      audit_id, user_id, event_time, field_name, old_value, new_value
    """
    req_cols = ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"]
    _, rows = _read_csv_rows(file_path, req_cols)

    seen_ids: Set[str] = set()
    entries: List[UserAuditEntry] = []
    for idx, r in enumerate(rows, start=2):
        aid = r["audit_id"]
        if not aid:
            raise MissingIdentifierError(f"Row {idx} in {file_path} has missing audit_id")
        if aid in seen_ids:
            raise DuplicateIdentifierError(f"Duplicate audit_id '{aid}' in {file_path} at row {idx}")
        seen_ids.add(aid)

        entries.append(
            UserAuditEntry(
                audit_id=aid,
                user_id=r["user_id"],
                event_time=r["event_time"],
                field_name=r["field_name"],
                old_value=r["old_value"],
                new_value=r["new_value"],
            )
        )
    return entries


def load_system_activity(file_path: Path | str) -> List[SystemActivity]:
    """Load system activity events.
    
    Required columns:
      activity_id, event_time, event_type, source_system, target_system, resource_id, reported_result, details
    """
    req_cols = [
        "activity_id",
        "event_time",
        "event_type",
        "source_system",
        "target_system",
        "resource_id",
        "reported_result",
        "details",
    ]
    _, rows = _read_csv_rows(file_path, req_cols)

    seen_ids: Set[str] = set()
    activities: List[SystemActivity] = []
    for idx, r in enumerate(rows, start=2):
        aid = r["activity_id"]
        if not aid:
            raise MissingIdentifierError(f"Row {idx} in {file_path} has missing activity_id")
        if aid in seen_ids:
            raise DuplicateIdentifierError(f"Duplicate activity_id '{aid}' in {file_path} at row {idx}")
        seen_ids.add(aid)

        activities.append(
            SystemActivity(
                activity_id=aid,
                event_time=r["event_time"],
                event_type=r["event_type"],
                source_system=r["source_system"],
                target_system=r["target_system"],
                resource_id=r["resource_id"],
                reported_result=r["reported_result"],
                details=r["details"],
            )
        )
    return activities


def load_deletion_rules(file_path: Path | str) -> List[DeletionRule]:
    """Load deletion rules.
    
    Required columns:
      rule_id, data_category, condition, required_action
    """
    req_cols = ["rule_id", "data_category", "condition", "required_action"]
    _, rows = _read_csv_rows(file_path, req_cols)

    seen_ids: Set[str] = set()
    rules: List[DeletionRule] = []
    for idx, r in enumerate(rows, start=2):
        rid = r["rule_id"]
        if not rid:
            raise MissingIdentifierError(f"Row {idx} in {file_path} has missing rule_id")
        if rid in seen_ids:
            raise DuplicateIdentifierError(f"Duplicate rule_id '{rid}' in {file_path} at row {idx}")
        seen_ids.add(rid)

        rules.append(
            DeletionRule(
                rule_id=rid,
                data_category=r["data_category"],
                condition=r["condition"],
                required_action=r["required_action"],
            )
        )
    return rules


def load_evidence_manifest(file_path: Path | str) -> List[EvidenceFileRecord]:
    """Load evidence manifest.
    
    Required columns:
      file_id, file_path, origin, captured_at
    """
    req_cols = ["file_id", "file_path", "origin", "captured_at"]
    _, rows = _read_csv_rows(file_path, req_cols)

    seen_ids: Set[str] = set()
    records: List[EvidenceFileRecord] = []
    for idx, r in enumerate(rows, start=2):
        fid = r["file_id"]
        if not fid:
            raise MissingIdentifierError(f"Row {idx} in {file_path} has missing file_id")
        if fid in seen_ids:
            raise DuplicateIdentifierError(f"Duplicate file_id '{fid}' in {file_path} at row {idx}")
        seen_ids.add(fid)

        records.append(
            EvidenceFileRecord(
                file_id=fid,
                file_path=r["file_path"],
                origin=r["origin"],
                captured_at=r["captured_at"],
            )
        )
    return records
