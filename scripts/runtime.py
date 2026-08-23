"""Small cross-platform runtime helpers shared by CLI scripts."""

import os
import sys

# Multilingual embedder (100+ languages, 384-dim via Matryoshka truncation).
# The stock MemPalace/ChromaDB default (all-MiniLM-L6-v2) is English-trained
# and scores poorly on Spanish chat data, so LazoGraph defaults to
# embeddinggemma. An explicit MEMPALACE_EMBEDDING_MODEL still wins.
DEFAULT_EMBEDDING_MODEL = 'embeddinggemma'


def configure_embedding_model() -> None:
    """Default to the multilingual embedder unless the user chose one."""
    os.environ.setdefault('MEMPALACE_EMBEDDING_MODEL', DEFAULT_EMBEDDING_MODEL)


def configure_safe_output() -> None:
    """Replace unsupported console glyphs instead of crashing on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


configure_embedding_model()
