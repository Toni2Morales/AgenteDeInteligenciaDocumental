"""Apply the versioned SQL migrations to the configured database.

Usage::

    python scripts/migrate.py

The embedding dimension is read from ``EMBEDDING_DIMENSION`` (or ``.env``).
The runner refuses to create the vector column while that value is unknown, so
the schema is never built on a guessed dimension.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.config.settings import settings  # noqa: E402
from app.db import migrations  # noqa: E402
from app.db.connection import connect  # noqa: E402


def main() -> int:
    if settings.embedding_dimension is None:
        print(
            "[X] EMBEDDING_DIMENSION is not set. Verify it first with "
            "`python scripts/verify_ollama.py` and set it in your .env file."
        )
        return 1

    with connect(register_vector_type=False) as conn:
        applied = migrations.apply_migrations(
            conn,
            embedding_dimension=settings.embedding_dimension,
        )
        conn.commit()

    if applied:
        print(f"[OK] Applied migrations: {', '.join(applied)}")
    else:
        print("[OK] No pending migrations. Database is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
