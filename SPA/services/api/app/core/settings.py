from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project_id: str = "the49-487609"
    firestore_database: str = "spa-db"
    service_assets_bucket: str = ""
    cors_origins: str = Field(
        default="http://localhost:3001,http://localhost:3000",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )
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
    line_customer_messaging_channel_secret: str = ""
    booking_phone_pepper: SecretStr | None = None
    idempotency_ttl_hours: int = 24
    beam_enabled: bool = False
    beam_api_base_url: str = "https://playground.api.beamcheckout.com"
    beam_merchant_id: str | None = None
    beam_api_key: SecretStr | None = None
    beam_webhook_hmac_key: SecretStr | None = None
    beam_return_url: str | None = None
    beam_request_timeout_seconds: float = 15.0
    tip_custom_max_satang: int | None = None

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def deployment_environment(self) -> str:
        return "prod" if self.app_env.lower() in {"prod", "production"} else "test"

    @property
    def expected_firestore_database(self) -> str:
        if self.app_env.lower() in {"local", "development", "dev"}:
            return self.firestore_database
        return "spa-db" if self.deployment_environment == "prod" else "spa-test-db"

    @property
    def resolved_firestore_database(self) -> str:
        return self.firestore_database

    def beam_readiness_errors(self) -> tuple[str, ...]:
        if not self.beam_enabled:
            return ("BEAM_DISABLED",)
        missing = []
        for code, value in (
            ("BEAM_MERCHANT_ID_MISSING", self.beam_merchant_id),
            ("BEAM_API_KEY_MISSING", self.beam_api_key),
            ("BEAM_WEBHOOK_KEY_MISSING", self.beam_webhook_hmac_key),
            ("BEAM_RETURN_URL_MISSING", self.beam_return_url),
        ):
            if not value:
                missing.append(code)
        expected_url = (
            "https://api.beamcheckout.com"
            if self.deployment_environment == "prod"
            else "https://playground.api.beamcheckout.com"
        )
        if self.beam_api_base_url.rstrip("/") != expected_url:
            missing.append("BEAM_BASE_URL_ENVIRONMENT_MISMATCH")
        return tuple(missing)


@lru_cache
def get_settings() -> Settings:
    return Settings()
