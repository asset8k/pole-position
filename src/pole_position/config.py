from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str
    database_ssl: bool = False
    database_ssl_ca_file: Path | None = None
    test_database_url: str | None = None
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    openai_api_key: SecretStr
    answer_model: str = "gpt-6-luna"
    rerank_enabled: bool = True
    qdrant_url: str
    qdrant_api_key: SecretStr
    qdrant_collection: str = "fia_regulations"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    corpus_root: Path = Path(__file__).resolve().parents[2]
    validate_corpus_on_startup: bool = False


settings = Settings()  # type: ignore[call-arg] # Loaded from .env file
