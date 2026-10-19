"""Versioned, reproducible SQL migrations.

Migrations are plain ``.sql`` files under ``migrations/`` ordered by file name.
Each one is applied exactly once and recorded with a checksum so later edits to
an already applied file are detected instead of silently ignored.

SQL files may contain ``{{embedding_dim}}``. It is replaced with the verified
embedding dimension, which is why the runner refuses to run while that value is
unknown: no dimension is ever guessed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_ALLOWED_PLACEHOLDERS = frozenset({"embedding_dim"})

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    """Base class for migration failures."""


class MissingEmbeddingDimensionError(MigrationError):
    """A migration needs the embedding dimension but it is not configured."""


class UnknownPlaceholderError(MigrationError):
    """A migration uses a placeholder the runner does not understand."""


class ChecksumMismatchError(MigrationError):
    """An already applied migration file was modified afterwards."""


@dataclass(frozen=True)
class Migration:
    """A single versioned migration file."""

    version: str
    path: Path
    sql: str


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Load every ``.sql`` migration in deterministic file-name order."""
    files = sorted(directory.glob("*.sql"), key=lambda path: path.name)
    migrations: list[Migration] = []
    for path in files:
        migrations.append(
            Migration(
                version=path.stem,
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )
    return migrations


def render_sql(sql: str, *, embedding_dimension: int | None) -> str:
    """Replace allowed placeholders with validated values."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in _ALLOWED_PLACEHOLDERS:
            raise UnknownPlaceholderError(f"Unknown placeholder: {{{{{key}}}}}")
        if embedding_dimension is None:
            raise MissingEmbeddingDimensionError(
                "This migration needs EMBEDDING_DIMENSION. Verify it with "
                "`python scripts/verify_ollama.py` and set it before migrating."
            )
        if not isinstance(embedding_dimension, int) or embedding_dimension <= 0:
            raise MissingEmbeddingDimensionError(
                f"EMBEDDING_DIMENSION must be a positive integer, got: {embedding_dimension!r}"
            )
        return str(embedding_dimension)

    return _PLACEHOLDER_RE.sub(_replace, sql)


def checksum(sql: str) -> str:
    """Return a stable SHA-256 checksum of a migration template."""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def applied_migrations(conn) -> dict[str, str]:
    """Return ``{version: checksum}`` for every already applied migration."""
    with conn.cursor() as cur:
        cur.execute("SELECT version, checksum FROM schema_migrations")
        return {row[0]: row[1] for row in cur.fetchall()}


def apply_migrations(
    conn, *, embedding_dimension: int | None, directory: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply every pending migration and return the versions applied.

    The caller owns the connection and is responsible for committing.
    """
    migrations = load_migrations(directory)
    with conn.cursor() as cur:
        cur.execute(_CREATE_MIGRATIONS_TABLE)

    already_applied = applied_migrations(conn)
    newly_applied: list[str] = []

    for migration in migrations:
        current_checksum = checksum(migration.sql)
        if migration.version in already_applied:
            if already_applied[migration.version] != current_checksum:
                raise ChecksumMismatchError(
                    f"Migration {migration.version} changed after being applied."
                )
            continue

        rendered = render_sql(migration.sql, embedding_dimension=embedding_dimension)
        with conn.cursor() as cur:
            cur.execute(rendered)
            cur.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.version, current_checksum),
            )
        newly_applied.append(migration.version)

    return newly_applied
