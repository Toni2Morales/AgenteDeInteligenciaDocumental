-- 001_init: core tables for documents and their embedded chunks.
--
-- The vector dimension is NOT hardcoded here. The migration runner replaces
-- {{embedding_dim}} with the real dimension of the configured embedding model,
-- previously verified with `python scripts/verify_ollama.py`.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    sha256 char(64) NOT NULL,
    page_count integer NOT NULL CHECK (page_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT documents_sha256_key UNIQUE (sha256)
);

CREATE TABLE IF NOT EXISTS chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_uid text NOT NULL,
    text text NOT NULL,
    page_number integer NOT NULL CHECK (page_number >= 1),
    position integer NOT NULL CHECK (position >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding vector({{embedding_dim}}) NOT NULL,
    embedding_model text NOT NULL,
    embedding_dim integer NOT NULL,
    embedding_version text NOT NULL DEFAULT '1',
    created_at timestamptz NOT NULL DEFAULT now(),
    -- A chunk is unique per document and embedding model, so reprocessing with
    -- the same model replaces instead of duplicating, while a different model
    -- can coexist without ever mixing incompatible vectors.
    CONSTRAINT chunks_identity_key UNIQUE (document_id, chunk_uid, embedding_model)
);
