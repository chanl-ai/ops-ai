"""kb-service's door to its database. The engine type is re-exported so only the store imports the driver
(the drivers-only-in-stores import contract)."""

from .knowledge import AsyncEngine, KnowledgeStore, engine_for, metadata, reachable

__all__ = ["AsyncEngine", "KnowledgeStore", "engine_for", "metadata", "reachable"]
