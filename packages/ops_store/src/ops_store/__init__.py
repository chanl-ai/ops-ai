"""The store seam: every service reaches its database through repositories that declare the guarantees they need
(`Guarantee`), and each guarantee a port relies on has a conformance suite run against every registered backend.

  from ops_store import Guarantee, Repository, Backend, unmet
  from ops_store.ports import LeasePort, TimerClaimPort, AuditPort
  from ops_store.conformance import lease_suite, timer_claim_suite, audit_suite
"""

from __future__ import annotations

from .guarantees import Backend, Guarantee, Repository, unmet

__all__ = ["Backend", "Guarantee", "Repository", "unmet"]
