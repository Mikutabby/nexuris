#!/usr/bin/env python3
"""Lanzador de Nexo 2.0 CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nexuris.cli import main

if __name__ == "__main__":
    main()
