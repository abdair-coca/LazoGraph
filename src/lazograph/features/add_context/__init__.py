"""Slice 3: add auditable manual context."""

from .service import (
    ContextPreview,
    ContextRecord,
    ContextValidationError,
    build_context_preview,
)

__all__ = [
    "ContextPreview",
    "ContextRecord",
    "ContextValidationError",
    "build_context_preview",
]
