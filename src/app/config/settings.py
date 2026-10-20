from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DocuMind AI"
    env: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    max_upload_size_mb: int = 10

    # PostgreSQL (local development defaults; overridden by environment variables)
    postgres_user: str = "documind"
    postgres_password: str = "documind"
    postgres_db: str = "documind"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_connect_timeout: int = 5
    database_url: str = ""

    # Ollama (local inference server)
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen2.5:3b"
    ollama_embedding_model: str = "embeddinggemma"
    ollama_timeout_seconds: float = 120.0

    # Embedding vector dimension. It must stay unset until the real dimension of
    # the embedding model is verified with `python scripts/verify_ollama.py`.
    embedding_dimension: int | None = None
    embedding_version: str = "1"

    @field_validator("embedding_dimension", mode="before")
    @classmethod
    def _empty_embedding_dimension_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # Retrieval-augmented generation (RAG)
    chunk_size_chars: int = 900
    chunk_overlap_chars: int = 150
    embedding_batch_size: int = 8
    retrieval_top_k: int = 5
    # Minimum cosine similarity for a retrieved chunk to be considered evidence.
    # This is an initial heuristic, not a guarantee of correctness: it must be
    # calibrated with the evaluation set in demo/evaluation.json.
    retrieval_min_score: float = 0.35
    # Maximum number of characters of retrieved context sent to the LLM.
    max_context_chars: int = 6000
    max_question_chars: int = 1000

    def validate_for_rag(self) -> None:
        """Raise ``ValueError`` when the configuration cannot run the RAG flow."""
        if self.embedding_dimension is None:
            raise ValueError(
                "EMBEDDING_DIMENSION is not set. Verify it with "
                "`python scripts/verify_ollama.py` and set it before indexing."
            )
        if self.chunk_size_chars <= 0:
            raise ValueError("CHUNK_SIZE_CHARS must be a positive integer.")
        if self.chunk_overlap_chars < 0 or self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be >= 0 and smaller than CHUNK_SIZE_CHARS.")
        if self.embedding_batch_size <= 0:
            raise ValueError("EMBEDDING_BATCH_SIZE must be a positive integer.")
        if self.retrieval_top_k <= 0:
            raise ValueError("RETRIEVAL_TOP_K must be a positive integer.")
        if not 0.0 <= self.retrieval_min_score <= 1.0:
            raise ValueError("RETRIEVAL_MIN_SCORE must be between 0.0 and 1.0.")

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def resolved_database_url(self) -> str:
        """Connection string, either explicit or built from the POSTGRES_* values."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
