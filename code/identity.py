"""Identity resolution with provenance tracking, historical audit chaining, and isolation."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .models import UserAuditEntry, UserIdentity


class IdentityResolutionError(Exception):
    """Base exception for identity resolution failures."""
    pass


class AmbiguousIdentityError(IdentityResolutionError):
    """Raised when an identifier matches multiple distinct users."""
    pass


@dataclass(frozen=True)
class ProvenanceLink:
    source: str  # "CURRENT_IDENTITY" or "HISTORICAL_AUDIT"
    field_name: str  # "email", "phone", "email_hash", "name"
    value: str
    audit_id: Optional[str] = None
    event_time: Optional[str] = None


@dataclass
class ResolvedUser:
    user_id: str
    current_identity: UserIdentity
    all_emails: Set[str] = field(default_factory=set)
    all_phones: Set[str] = field(default_factory=set)
    all_email_hashes: Set[str] = field(default_factory=set)
    provenance_links: List[ProvenanceLink] = field(default_factory=list)

    def get_matched_provenance(self, identifier: str) -> List[ProvenanceLink]:
        norm = identifier.strip().lower()
        return [p for p in self.provenance_links if p.value.strip().lower() == norm]


class IdentityResolver:
    """Resolves current and historical user identities from identities and audit log.
    
    Ensures:
      - Historical changes from user_audit_log are linked with full provenance.
      - Similar emails (e.g. smartinez6461 vs mmartinez7917) are strictly isolated.
      - Ambiguous matches across users are detected and flagged.
    """

    def __init__(self, identities: List[UserIdentity], audit_logs: List[UserAuditEntry]):
        self._identities: Dict[str, UserIdentity] = {u.user_id: u for u in identities}
        self._audit_by_user: Dict[str, List[UserAuditEntry]] = {}
        for a in audit_logs:
            self._audit_by_user.setdefault(a.user_id, []).append(a)

        self._resolved_cache: Dict[str, ResolvedUser] = {}
        self._email_to_users: Dict[str, Set[str]] = {}
        self._phone_to_users: Dict[str, Set[str]] = {}
        self._hash_to_users: Dict[str, Set[str]] = {}

        self._build_indexes()

    def _build_indexes(self) -> None:
        for user_id, current_id in self._identities.items():
            resolved = ResolvedUser(
                user_id=user_id,
                current_identity=current_id,
                all_emails=set(),
                all_phones=set(),
                all_email_hashes=set(),
                provenance_links=[],
            )

            # 1. Add current identity attributes with provenance
            if current_id.email:
                c_email = current_id.email.strip().lower()
                resolved.all_emails.add(c_email)
                resolved.provenance_links.append(
                    ProvenanceLink(
                        source="CURRENT_IDENTITY",
                        field_name="email",
                        value=current_id.email.strip(),
                        event_time=current_id.updated_at,
                    )
                )

            if current_id.phone:
                c_phone = current_id.phone.strip()
                resolved.all_phones.add(c_phone)
                resolved.provenance_links.append(
                    ProvenanceLink(
                        source="CURRENT_IDENTITY",
                        field_name="phone",
                        value=c_phone,
                        event_time=current_id.updated_at,
                    )
                )

            if current_id.email_hash:
                c_hash = current_id.email_hash.strip().lower()
                resolved.all_email_hashes.add(c_hash)
                resolved.provenance_links.append(
                    ProvenanceLink(
                        source="CURRENT_IDENTITY",
                        field_name="email_hash",
                        value=c_hash,
                        event_time=current_id.updated_at,
                    )
                )

            # 2. Add historical audit attributes for this user
            user_audits = self._audit_by_user.get(user_id, [])
            for a in user_audits:
                f_name = a.field_name.strip()
                if f_name == "email":
                    for val in (a.old_value, a.new_value):
                        if val and val.strip():
                            clean_val = val.strip().lower()
                            resolved.all_emails.add(clean_val)
                            resolved.provenance_links.append(
                                ProvenanceLink(
                                    source="HISTORICAL_AUDIT",
                                    field_name="email",
                                    value=val.strip(),
                                    audit_id=a.audit_id,
                                    event_time=a.event_time,
                                )
                            )
                elif f_name == "phone":
                    for val in (a.old_value, a.new_value):
                        if val and val.strip():
                            clean_val = val.strip()
                            resolved.all_phones.add(clean_val)
                            resolved.provenance_links.append(
                                ProvenanceLink(
                                    source="HISTORICAL_AUDIT",
                                    field_name="phone",
                                    value=clean_val,
                                    audit_id=a.audit_id,
                                    event_time=a.event_time,
                                )
                            )
                elif f_name == "email_hash":
                    for val in (a.old_value, a.new_value):
                        if val and val.strip():
                            clean_val = val.strip().lower()
                            resolved.all_email_hashes.add(clean_val)
                            resolved.provenance_links.append(
                                ProvenanceLink(
                                    source="HISTORICAL_AUDIT",
                                    field_name="email_hash",
                                    value=clean_val,
                                    audit_id=a.audit_id,
                                    event_time=a.event_time,
                                )
                            )

            self._resolved_cache[user_id] = resolved

            # Build reverse lookups
            for em in resolved.all_emails:
                self._email_to_users.setdefault(em, set()).add(user_id)
            for ph in resolved.all_phones:
                self._phone_to_users.setdefault(ph, set()).add(user_id)
            for eh in resolved.all_email_hashes:
                self._hash_to_users.setdefault(eh, set()).add(user_id)

    def resolve_by_email(self, email: str) -> Optional[ResolvedUser]:
        """Resolve a user by current or historical email address.
        
        Performs strict exact email matching (case-insensitive).
        Raises AmbiguousIdentityError if email maps to multiple users.
        """
        if not email or not email.strip():
            return None
        norm_email = email.strip().lower()
        matched_user_ids = self._email_to_users.get(norm_email, set())

        if not matched_user_ids:
            return None
        if len(matched_user_ids) > 1:
            raise AmbiguousIdentityError(
                f"Email '{email}' matches multiple users: {sorted(matched_user_ids)}"
            )

        uid = next(iter(matched_user_ids))
        return self._resolved_cache[uid]

    def resolve_by_user_id(self, user_id: str) -> Optional[ResolvedUser]:
        """Resolve directly by stable user_id."""
        return self._resolved_cache.get(user_id)

    def is_identifier_associated(self, user: ResolvedUser, candidate_identifier: str) -> bool:
        """Check if candidate string strictly matches any email, phone, hash, or user_id for this user.
        
        Never uses fuzzy or substring matching.
        """
        if not candidate_identifier or not isinstance(candidate_identifier, str):
            return False
        clean = candidate_identifier.strip()
        clean_lower = clean.lower()

        if clean == user.user_id:
            return True
        if clean_lower in user.all_emails:
            return True
        if clean in user.all_phones:
            return True
        if clean_lower in user.all_email_hashes:
            return True
        return False
