"""Small cross-platform runtime helpers shared by CLI scripts."""

import sys


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
