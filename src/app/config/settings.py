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
