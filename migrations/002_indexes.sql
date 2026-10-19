-- 002_indexes: lookup and vector indexes.
--
-- The HNSW index requires a fixed-dimension vector column, which is why the
-- dimension must be verified before this migration runs.

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);

CREATE INDEX IF NOT EXISTS chunks_model_dim_idx ON chunks (embedding_model, embedding_dim);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
