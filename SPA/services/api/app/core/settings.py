from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project_id: str = "the49-487609"
    firestore_database: str = "spa-db"
    service_assets_bucket: str = ""
    cors_origins: str = "http://localhost:3001,http://localhost:3000"
    app_env: str = "local"
    default_branch_id: str = "branch_001"
    capacity_bucket_minutes: int = 15
    health_retention_years: int = 3
    health_retention_policy_version: str = "health-3y-approved-v1"
    health_retention_policy_approved: bool = True
    health_consent_version: str = "health-consent-admin-line-th-2026-08-v2"
    privacy_notice_version: str = "privacy-draft-v2"
    booking_terms_version: str = "terms-draft-v1"
    no_show_grace_minutes: int = 15
    line_customer_login_channel_id: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
