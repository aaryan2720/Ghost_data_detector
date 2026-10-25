"""Multilingual request intent classifier for Ghost Data Still Exists.

Distinguishes genuine deletion requests from non-deletion requests
(access, export/download, invoice copy, rectification, marketing preference).
"""

from dataclasses import dataclass
import re
from typing import Optional


@dataclass(frozen=True)
class IntentClassification:
    is_deletion_request: bool
    detected_intent: str
    confidence: float
    reason: str


# Regex patterns across English, French, Spanish, Japanese
# Explicit non-deletion signals where user asks to retain profile/account
EXPLICIT_NON_DELETION_PATTERNS = [
    # English non-deletion requests (access, export, invoices, keeping account)
    (r"keep\s+the\s+account(\s+as\s+it\s+is)?", "KEEP_ACCOUNT"),
    (r"leave\s+my\s+profile(\s+and\s+purchase\s+history)?\s+in\s+place", "KEEP_PROFILE"),
    (r"do\s+not\s+(delete|close|remove|erase)", "DO_NOT_DELETE"),
    (r"copy\s+of\s+.*invoices?\s+for\s+my\s+records", "INVOICE_COPY_REQUEST"),
    (r"download\s+my\s+account\s+information\s+in\s+a\s+portable\s+format", "DATA_PORTABILITY_EXPORT"),
    (r"only\s+(want|need)\s+to\s+(update|change|correct)\s+my", "RECTIFICATION_REQUEST"),
    (r"unsubscribe\s+from\s+(marketing|newsletters?|promotions?)", "MARKETING_OPT_OUT"),
    # French non-deletion requests
    (r"garder?\s+le\s+compte", "KEEP_ACCOUNT_FR"),
    (r"ne\s+supprimez\s+pas", "DO_NOT_DELETE_FR"),
    (r"copie\s+de\s+mes\s+factures", "INVOICE_COPY_FR"),
    (r"exporter?\s+mes\s+donn[ée]es", "DATA_EXPORT_FR"),
    # Spanish non-deletion requests
    (r"mantener\s+la\s+cuenta", "KEEP_ACCOUNT_ES"),
    (r"no\s+elimine(n)?", "DO_NOT_DELETE_ES"),
    (r"copia\s+de\s+las?\s+facturas?", "INVOICE_COPY_ES"),
    (r"descargar\s+mis\s+datos", "DATA_EXPORT_ES"),
    # Japanese non-deletion requests
    (r"アカウントはそのまま", "KEEP_ACCOUNT_JA"),
    (r"削除しないで", "DO_NOT_DELETE_JA"),
    (r"請求書のコピー", "INVOICE_COPY_JA"),
]

# Deletion keywords in multiple languages
DELETION_PATTERNS = [
    # English inflections: delete, deleted, deleting, deletion, erase, erased, erasing, erasure, close, closed, closing, remove, removed, removing, removal
    r"\b(delet(e|es|ed|ing|ion)?|eras(e|es|ed|ing|ure)?|clos(e|es|ed|ing)?|remov(e|es|ed|ing|al)?|destroy(s|ed|ing)?)\b",
    r"\b(profile\s+is\s+gone|account\s+is\s+gone)\b",
    r"\b(audit(\s+the)?\s+deletion)\b",
    r"personal-data\s+deletion",
    # French
    r"\b(suppression|supprimer|supprim[ée]s?|effacer|effacement|fermeture|cl[oô]turer)\b",
    # Spanish
    r"\b(eliminar|eliminaci[oó]n|borrar|borrado|cerrar|cancelar)\b",
    # Japanese
    r"(削除|消去|解約|退会|抹消)",
]


def classify_request(request_text: str) -> IntentClassification:
    """Classify request_text into a deletion request or non-deletion request.
    
    Returns IntentClassification with boolean is_deletion_request.
    """
    if not request_text or not isinstance(request_text, str):
        return IntentClassification(
            is_deletion_request=False,
            detected_intent="EMPTY_REQUEST",
            confidence=1.0,
            reason="Request text is empty or missing",
        )

    text = request_text.strip()
    text_lower = text.lower()

    # 1. Check explicit non-deletion signals first
    for pattern, intent in EXPLICIT_NON_DELETION_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            return IntentClassification(
                is_deletion_request=False,
                detected_intent=intent,
                confidence=0.98,
                reason=f"Matched explicit non-deletion pattern '{match.group(0)}'",
            )

    # 2. Check for deletion authorization intent
    has_deletion_signal = False
    matched_kw = None
    for pattern in DELETION_PATTERNS:
        match = re.search(pattern, text_lower if not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text) else text, re.IGNORECASE)
        if match:
            has_deletion_signal = True
            matched_kw = match.group(0)
            break

    if has_deletion_signal:
        return IntentClassification(
            is_deletion_request=True,
            detected_intent="DELETION_REQUEST",
            confidence=0.95,
            reason=f"Authorized deletion request matched signal '{matched_kw}'",
        )

    # 3. Default fallback: ambiguous or non-deletion
    return IntentClassification(
        is_deletion_request=False,
        detected_intent="UNRECOGNIZED_NON_DELETION",
        confidence=0.70,
        reason="No authorized deletion signals detected in text",
    )
