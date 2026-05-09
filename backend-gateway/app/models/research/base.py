"""Declarative base for the Lohi-Research SQLAlchemy 2.0 ORM layer.

All ORM classes in this package inherit from :class:`Base` so they share a
single ``MetaData`` instance — this is what lets Alembic autogeneration target
the research tables as a coherent unit once the adapter at Task 4.1 is in
place.

No mixins are defined yet; if shared behaviour (e.g. ``created_at`` timestamp
helpers) becomes useful later it should be added here so every model picks
it up uniformly.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every Lohi-Research ORM model."""
