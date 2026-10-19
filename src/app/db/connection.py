"""Database connection helpers.

Keeping connection creation in one place means the rest of the application only
depends on a psycopg connection, which makes the repositories easy to test with
a fake connection and easy to reuse from scripts.
"""

from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from app.config.settings import settings


def connect(
    database_url: str | None = None,
    *,
    register_vector_type: bool = True,
    autocommit: bool = False,
) -> psycopg.Connection:
    """Open a connection to PostgreSQL.

    Args:
        database_url: Explicit DSN. Falls back to the configured one.
        register_vector_type: Register pgvector's type adapter so Python lists
            round-trip as ``vector`` values. Requires the ``vector`` extension
            to exist, so it is disabled while bootstrapping the schema.
        autocommit: Use autocommit mode (useful for one-off scripts).
    """
    dsn = database_url or settings.resolved_database_url
    conn = psycopg.connect(
        dsn,
        autocommit=autocommit,
        connect_timeout=settings.postgres_connect_timeout,
    )
    if register_vector_type:
        register_vector(conn)
    return conn
