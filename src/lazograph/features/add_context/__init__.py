"""Slice 3: add auditable manual context."""

from .service import (
    ContextApplyResult,
    ContextPreview,
    ContextRecord,
    ContextValidationError,
    apply_context,
    build_context_preview,
)

__all__ = [
    "ContextApplyResult",
    "ContextPreview",
    "ContextRecord",
    "ContextValidationError",
    "apply_context",
    "build_context_preview",
]
