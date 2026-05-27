"""MCQ generation pipeline package."""

from __future__ import annotations

import sys


def _force_utf8_stdio() -> None:
    """Keep Vietnamese progress logs from crashing on Windows cp1252 consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            try:
                reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass


_force_utf8_stdio()
