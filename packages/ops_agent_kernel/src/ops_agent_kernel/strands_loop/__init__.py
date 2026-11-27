"""The Strands Agents loop behind the kernel's contract (contract.py). The only package that imports strands."""

from .driver import close, run

__all__ = ["close", "run"]
