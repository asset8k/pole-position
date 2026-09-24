from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str
    test_database_url: str | None = None
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    openai_api_key: SecretStr
    qdrant_url: str
    qdrant_api_key: SecretStr
    qdrant_collection: str = "fia_regulations"


settings = Settings()  # type: ignore[call-arg] # Loaded from .env file
