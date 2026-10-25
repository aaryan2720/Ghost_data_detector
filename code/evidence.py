"""Evidence index and provenance-bearing content inspection.

Strict rules:
  1. Admissibility: Evidence captured strictly after audit_at is excluded.
  2. Grounded matching: Matches rely on inspected content (SQL rows, JSON objects,
     log lines), never on file paths or filenames alone.
  3. Structural inspection: SQL files are executed in SQLite to inspect tables and rows.
  4. OCR note: PDFs and images are noted as raw document/visual evidence; OCR is not
     claimed or fabricated in milestone 1.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from .loader import load_evidence_manifest
from .models import EvidenceFileRecord
from .timestamp import is_at_or_before


@dataclass
class SqlRowMatch:
    table_name: str
    resource_id: Optional[str]
    matched_columns: Dict[str, Any]
    raw_row: Tuple[Any, ...]


@dataclass
class SqlInspectionResult:
    file_id: str
    file_path: str
    captured_at: str
    tables: List[str]
    row_counts: Dict[str, int]
    matched_rows: List[SqlRowMatch] = field(default_factory=list)


@dataclass
class JsonRecordMatch:
    path: str
    resource_id: Optional[str]
    matched_data: Dict[str, Any]


@dataclass
class JsonInspectionResult:
    file_id: str
    file_path: str
    captured_at: str
    matched_records: List[JsonRecordMatch] = field(default_factory=list)


@dataclass
class LogLineMatch:
    line_no: int
    line_content: str
    matched_tokens: List[str]


@dataclass
class LogInspectionResult:
    file_id: str
    file_path: str
    captured_at: str
    matched_lines: List[LogLineMatch] = field(default_factory=list)


class EvidenceIndex:
    """Manages the participant-visible evidence manifest and inspects content."""

    def __init__(self, manifest_path: Path | str, evidence_root: Path | str):
        self.evidence_root = Path(evidence_root)
        self.records: List[EvidenceFileRecord] = load_evidence_manifest(manifest_path)
        self.by_id: Dict[str, EvidenceFileRecord] = {r.file_id: r for r in self.records}

    def get_admissible_evidence(self, audit_at: str) -> List[EvidenceFileRecord]:
        """Return evidence files captured on or before audit_at (inclusive cutoff).
        
        Files captured strictly after audit_at are completely excluded.
        """
        admissible = []
        for rec in self.records:
            if is_at_or_before(rec.captured_at, audit_at):
                admissible.append(rec)
        return admissible

    def resolve_file_path(self, record: EvidenceFileRecord) -> Path:
        """Resolve the relative file_path from the evidence manifest against dataset folder."""
        # e.g., 'evidence/databases/customer_accounts_failover_replica_20260902.sql'
        # The evidence_root is 'dataset/' or 'dataset/evidence/'
        p = Path(record.file_path)
        if (self.evidence_root / p).is_file():
            return self.evidence_root / p
        # If relative to evidence root
        rel_to_evidence = p.name
        for candidate in self.evidence_root.rglob(rel_to_evidence):
            if candidate.is_file():
                return candidate
        return self.evidence_root / p

    def inspect_sql(self, record: EvidenceFileRecord, search_terms: Set[str]) -> SqlInspectionResult:
        """Execute an SQLite-compatible SQL snapshot in memory and search content structurally."""
        file_path = self.resolve_file_path(record)
        if not file_path.is_file():
            raise FileNotFoundError(f"SQL evidence file missing: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            sql_text = f.read()

        con = sqlite3.connect(":memory:")
        con.executescript(sql_text)
        cur = con.cursor()

        tables = [
            row[0]
            for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        row_counts = {}
        matched_rows: List[SqlRowMatch] = []

        norm_terms = {t.strip().lower() for t in search_terms if t and t.strip()}

        for tbl in tables:
            cnt = cur.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            row_counts[tbl] = cnt

            cols = [col[1] for col in cur.execute(f"PRAGMA table_info({tbl})").fetchall()]
            rows = cur.execute(f"SELECT * FROM {tbl}").fetchall()

            for r in rows:
                row_dict = {col: val for col, val in zip(cols, r)}
                # Search values and inside JSON payloads
                matched = False
                matched_cols = {}
                resource_id = str(row_dict.get("resource_id", ""))

                for col, val in row_dict.items():
                    if val is None:
                        continue
                    str_val = str(val).lower()
                    for term in norm_terms:
                        if term in str_val:
                            matched = True
                            matched_cols[col] = val

                if matched:
                    matched_rows.append(
                        SqlRowMatch(
                            table_name=tbl,
                            resource_id=resource_id if resource_id else None,
                            matched_columns=row_dict,
                            raw_row=r,
                        )
                    )

        con.close()
        return SqlInspectionResult(
            file_id=record.file_id,
            file_path=str(file_path),
            captured_at=record.captured_at,
            tables=tables,
            row_counts=row_counts,
            matched_rows=matched_rows,
        )

    def inspect_json(self, record: EvidenceFileRecord, search_terms: Set[str]) -> JsonInspectionResult:
        """Parse JSON evidence file and search for objects containing identifiers."""
        file_path = self.resolve_file_path(record)
        if not file_path.is_file():
            raise FileNotFoundError(f"JSON evidence file missing: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        norm_terms = {t.strip().lower() for t in search_terms if t and t.strip()}
        matched_records: List[JsonRecordMatch] = []

        def walk(obj: Any, current_path: str):
            if isinstance(obj, dict):
                # Check if this dict matches
                str_rep = json.dumps(obj).lower()
                for term in norm_terms:
                    if term in str_rep:
                        # Extract resource_id if present
                        res_id = obj.get("resource_id") or obj.get("id")
                        matched_records.append(
                            JsonRecordMatch(
                                path=current_path,
                                resource_id=str(res_id) if res_id else None,
                                matched_data=obj,
                            )
                        )
                        break
                for k, v in obj.items():
                    walk(v, f"{current_path}.{k}" if current_path else k)
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    walk(item, f"{current_path}[{idx}]")

        walk(data, "")
        return JsonInspectionResult(
            file_id=record.file_id,
            file_path=str(file_path),
            captured_at=record.captured_at,
            matched_records=matched_records,
        )

    def inspect_log(self, record: EvidenceFileRecord, search_terms: Set[str]) -> LogInspectionResult:
        """Inspect log or plain-text file line-by-line, preserving line number provenance."""
        file_path = self.resolve_file_path(record)
        if not file_path.is_file():
            raise FileNotFoundError(f"Log evidence file missing: {file_path}")

        norm_terms = {t.strip().lower() for t in search_terms if t and t.strip()}
        matched_lines: List[LogLineMatch] = []

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                line_lower = line.lower()
                hits = [term for term in norm_terms if term in line_lower]
                if hits:
                    matched_lines.append(
                        LogLineMatch(
                            line_no=line_no,
                            line_content=line.strip(),
                            matched_tokens=hits,
                        )
                    )

        return LogInspectionResult(
            file_id=record.file_id,
            file_path=str(file_path),
            captured_at=record.captured_at,
            matched_lines=matched_lines,
        )
