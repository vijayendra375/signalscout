#!/usr/bin/env python3
"""SignalScout — Top-level reproducible runner."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.cli import main

if __name__ == "__main__":
    main()
