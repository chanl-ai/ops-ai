"""Installs this plugin example through its existing public-API installer."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "install.py"), run_name="__main__")
