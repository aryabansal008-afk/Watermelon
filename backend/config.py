from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://watermelon:watermelon@localhost:5432/watermelon"
    database_url_unpooled: str = ""
    redis_url: str = "redis://localhost:6379/0"
    api_service_token: str = ""
    owner_id: str = "local-owner"
    app_env: str = "development"
    github_token: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_installation_id: str = ""
    github_webhook_secret: str = ""
    github_publish_enabled: bool = False
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_verify_model: str = ""
    openrouter_embedding_model: str = ""
    model_calls_per_day: int = 30
    model_max_output_tokens: int = 3500
    model_max_input_chars: int = 48000
    jobs_per_project_per_hour: int = 12
    discourse_origins: str = "https://discuss.python.org"

    @model_validator(mode="after")
    def production_secrets(self):
        if self.app_env.lower() == "production":
            if len(self.api_service_token) < 32:
                raise ValueError("API_SERVICE_TOKEN must be configured with at least 32 characters in production")
            if not self.owner_id or self.owner_id == "local-owner":
                raise ValueError("OWNER_ID must be explicitly configured in production")
            if not self.database_url or "localhost" in self.database_url or "127.0.0.1" in self.database_url:
                raise ValueError("DATABASE_URL must point to the production PostgreSQL service")
            if not self.database_url_unpooled or "localhost" in self.database_url_unpooled or "127.0.0.1" in self.database_url_unpooled:
                raise ValueError("DATABASE_URL_UNPOOLED must point to the production PostgreSQL service")
            if not self.redis_url.startswith("rediss://"):
                raise ValueError("REDIS_URL must use TLS (rediss://) in production")
            if not self.openrouter_api_key or not self.openrouter_model or not self.openrouter_verify_model:
                raise ValueError("OpenRouter key, extraction model, and verification model are required in production")
            if self.github_publish_enabled and (not self.github_app_id or not self.github_app_private_key
                    or not self.github_installation_id or len(self.github_webhook_secret) < 32):
                raise ValueError("GitHub App credentials and a strong webhook secret are required when publishing is enabled")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
