"""Slice 4: safe, auditable knowledge correction."""

from .ledger import (
    CorrectionLedgerError,
    correction_records,
    undo_correction,
)
from .service import (
    CorrectionValidationError,
    apply_correction,
    build_correction_preview,
)

__all__ = [
    "CorrectionLedgerError",
    "CorrectionValidationError",
    "apply_correction",
    "build_correction_preview",
    "correction_records",
    "undo_correction",
]
