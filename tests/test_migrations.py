"""Unit tests for the SQL migrations and the migration runner.

These tests never require a database: they check file ordering, placeholder
rendering and checksum stability, which is where the safety properties live.
"""

from pathlib import Path

import pytest

from app.db import migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def test_migrations_are_loaded_in_order_and_unique():
    loaded = migrations.load_migrations(MIGRATIONS_DIR)

    versions = [migration.version for migration in loaded]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions[0] == "001_init"


def test_render_sql_substitutes_dimension():
    rendered = migrations.render_sql(
        "CREATE TABLE t (v vector({{embedding_dim}}));",
        embedding_dimension=768,
    )

    assert rendered == "CREATE TABLE t (v vector(768));"


def test_render_sql_requires_dimension_when_placeholder_present():
    with pytest.raises(migrations.MissingEmbeddingDimensionError):
        migrations.render_sql(
            "CREATE TABLE t (v vector({{embedding_dim}}));",
            embedding_dimension=None,
        )


def test_render_sql_rejects_non_positive_dimension():
    with pytest.raises(migrations.MissingEmbeddingDimensionError):
        migrations.render_sql("vector({{embedding_dim}})", embedding_dimension=0)


def test_render_sql_rejects_unknown_placeholder():
    with pytest.raises(migrations.UnknownPlaceholderError):
        migrations.render_sql("SELECT {{secret}}", embedding_dimension=768)


def test_render_sql_leaves_plain_sql_untouched():
    sql = "CREATE INDEX i ON t (a);"

    assert migrations.render_sql(sql, embedding_dimension=None) == sql


def test_checksum_is_stable_and_content_sensitive():
    assert migrations.checksum("a") == migrations.checksum("a")
    assert migrations.checksum("a") != migrations.checksum("b")


def test_init_migration_defines_required_chunk_columns():
    sql = (MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8")

    for column in (
        "document_id",
        "chunk_uid",
        "text",
        "page_number",
        "position",
        "metadata",
        "embedding vector({{embedding_dim}})",
        "embedding_model",
        "embedding_dim",
        "embedding_version",
        "created_at",
    ):
        assert column in sql, f"Missing column definition: {column}"


def test_init_migration_does_not_hardcode_dimension():
    sql = (MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8")

    assert "{{embedding_dim}}" in sql
    assert "vector(768)" not in sql


def test_indexes_migration_creates_hnsw_and_model_index():
    sql = (MIGRATIONS_DIR / "002_indexes.sql").read_text(encoding="utf-8")

    assert "USING hnsw" in sql
    assert "vector_cosine_ops" in sql
    assert "embedding_model, embedding_dim" in sql
