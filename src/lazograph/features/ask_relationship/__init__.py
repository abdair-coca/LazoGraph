"""Grounded relationship-question vertical slice."""

from .service import (
    RelationshipQuestionError,
    answer_about_relationship,
    resolve_relationship_participants,
)

__all__ = [
    "RelationshipQuestionError",
    "answer_about_relationship",
    "resolve_relationship_participants",
]
