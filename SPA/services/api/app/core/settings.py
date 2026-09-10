import re
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.types import BeamPaymentMethod

_BEAM_REDIRECT_HOST_PATTERN = re.compile(
    r"^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]"
    r"(?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_BEAM_REDIRECT_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]{1,31}$")
_FORBIDDEN_BEAM_REDIRECT_SCHEMES = {
    "about",
    "blob",
    "data",
    "file",
    "http",
    "https",
    "javascript",
    "vbscript",
}
_REQUIRED_BEAM_REDIRECT_SCHEMES = {
    BeamPaymentMethod.SCB_EASY: "scbeasy",
    BeamPaymentMethod.KRUNGSRI_APP: "krungsri-kma",
    BeamPaymentMethod.BANGKOK_BANK_APP: "bualuangmbanking",
}


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
    max_services_per_participant: int = 3
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
    beam_payment_methods: str = "QR_PROMPT_PAY"
    beam_redirect_allowed_hosts: str = (
        "beamcheckout.com,*.beamcheckout.com,beamcheckout.co,*.beamcheckout.co"
    )
    beam_redirect_allowed_schemes: str = (
        "SCB_EASY=scbeasy,KRUNGSRI_APP=krungsri-kma,BANGKOK_BANK_APP=bualuangmbanking"
    )
    beam_production_mobile_banking_confirmed: bool = False
    beam_production_webhook_registered: bool = False
    tip_custom_max_satang: int | None = None
    accounting_sync_enabled: bool = False
    accounting_worker_url: str | None = None
    accounting_worker_oidc_audience: str | None = None
    accounting_tasks_location: str = "asia-southeast1"
    accounting_tasks_queue: str | None = None
    accounting_tasks_invoker_service_account: str | None = None
    flowaccount_document_allowed_hosts: str = "flowaccount.com,*.flowaccount.com"
    cash_deposit_enabled: bool = False
    cash_deposit_provider_contract_confirmed: bool = False
    cash_evidence_bucket: str = ""
    cash_evidence_signer_service_account: str = ""
    cash_evidence_max_bytes: int = 10 * 1024 * 1024
    cash_evidence_upload_ttl_minutes: int = 10
    cash_evidence_read_ttl_minutes: int = 5
    cash_deposit_qr_expiry_minutes: int = 30
    cash_deposit_return_url: str | None = None

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

    @property
    def configured_beam_payment_methods(self) -> tuple[BeamPaymentMethod, ...]:
        methods: list[BeamPaymentMethod] = []
        for value in self.beam_payment_methods.split(","):
            normalized = value.strip().upper()
            if not normalized:
                continue
            try:
                method = BeamPaymentMethod(normalized)
            except ValueError:
                continue
            if method not in methods:
                methods.append(method)
        return tuple(methods)

    @property
    def configured_beam_redirect_allowed_hosts(self) -> tuple[str, ...]:
        hosts: list[str] = []
        for value in self.beam_redirect_allowed_hosts.split(","):
            normalized = value.strip().lower().rstrip(".")
            if normalized and normalized not in hosts:
                hosts.append(normalized)
        return tuple(hosts)

    @property
    def configured_flowaccount_document_hosts(self) -> tuple[str, ...]:
        return tuple(
            value.strip().lower().rstrip(".")
            for value in self.flowaccount_document_allowed_hosts.split(",")
            if value.strip()
        )

    def accounting_readiness_errors(self) -> tuple[str, ...]:
        if not self.accounting_sync_enabled:
            return ("ACCOUNTING_SYNC_DISABLED",)
        missing: list[str] = []
        for code, value in (
            ("ACCOUNTING_WORKER_URL_MISSING", self.accounting_worker_url),
            ("ACCOUNTING_WORKER_AUDIENCE_MISSING", self.accounting_worker_oidc_audience),
            ("ACCOUNTING_TASKS_QUEUE_MISSING", self.accounting_tasks_queue),
            (
                "ACCOUNTING_TASKS_INVOKER_MISSING",
                self.accounting_tasks_invoker_service_account,
            ),
        ):
            if not value:
                missing.append(code)
        if self.accounting_worker_url and not self.accounting_worker_url.startswith("https://"):
            missing.append("ACCOUNTING_WORKER_URL_INVALID")
        return tuple(missing)

    def cash_deposit_readiness_errors(self) -> tuple[str, ...]:
        if not self.cash_deposit_enabled:
            return ("CASH_DEPOSIT_DISABLED",)
        missing: list[str] = []
        if self.beam_readiness_errors():
            missing.append("CASH_DEPOSIT_BEAM_NOT_READY")
        for code, value in (
            ("CASH_EVIDENCE_BUCKET_MISSING", self.cash_evidence_bucket),
            (
                "CASH_EVIDENCE_SIGNER_SERVICE_ACCOUNT_MISSING",
                self.cash_evidence_signer_service_account,
            ),
            ("CASH_DEPOSIT_RETURN_URL_MISSING", self.cash_deposit_return_url),
        ):
            if not value:
                missing.append(code)
        return_url = urlparse(self.cash_deposit_return_url or "")
        if (
            return_url.scheme not in {"http", "https"}
            or not return_url.hostname
            or return_url.username is not None
            or return_url.password is not None
            or return_url.fragment
        ):
            missing.append("CASH_DEPOSIT_RETURN_URL_INVALID")
        if (
            self.deployment_environment == "prod"
            and not self.cash_deposit_provider_contract_confirmed
        ):
            missing.append("CASH_DEPOSIT_PROVIDER_CONTRACT_NOT_CONFIRMED")
        return tuple(missing)

    @property
    def configured_beam_redirect_allowed_schemes(
        self,
    ) -> dict[BeamPaymentMethod, tuple[str, ...]]:
        schemes: dict[BeamPaymentMethod, list[str]] = {}
        for value in self.beam_redirect_allowed_schemes.split(","):
            entry = value.strip()
            if not entry or "=" not in entry:
                continue
            raw_method, raw_scheme = entry.split("=", 1)
            try:
                method = BeamPaymentMethod(raw_method.strip().upper())
            except ValueError:
                continue
            scheme = raw_scheme.strip().lower()
            if (
                method is BeamPaymentMethod.QR_PROMPT_PAY
                or _BEAM_REDIRECT_SCHEME_PATTERN.fullmatch(scheme) is None
                or scheme in _FORBIDDEN_BEAM_REDIRECT_SCHEMES
            ):
                continue
            method_schemes = schemes.setdefault(method, [])
            if scheme not in method_schemes:
                method_schemes.append(scheme)
        return {method: tuple(values) for method, values in schemes.items()}

    def _beam_redirect_schemes_are_valid(self) -> bool:
        for value in self.beam_redirect_allowed_schemes.split(","):
            entry = value.strip()
            if not entry:
                continue
            if "=" not in entry:
                return False
            raw_method, raw_scheme = entry.split("=", 1)
            try:
                method = BeamPaymentMethod(raw_method.strip().upper())
            except ValueError:
                return False
            scheme = raw_scheme.strip().lower()
            if (
                method is BeamPaymentMethod.QR_PROMPT_PAY
                or _BEAM_REDIRECT_SCHEME_PATTERN.fullmatch(scheme) is None
                or scheme in _FORBIDDEN_BEAM_REDIRECT_SCHEMES
            ):
                return False
        return True

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
        raw_methods = {
            value.strip().upper() for value in self.beam_payment_methods.split(",") if value.strip()
        }
        supported_methods = {method.value for method in BeamPaymentMethod}
        if raw_methods - supported_methods:
            missing.append("BEAM_PAYMENT_METHODS_INVALID")
        if not self.configured_beam_payment_methods:
            missing.append("BEAM_PAYMENT_METHODS_EMPTY")
        redirect_hosts = self.configured_beam_redirect_allowed_hosts
        if not redirect_hosts:
            missing.append("BEAM_REDIRECT_ALLOWED_HOSTS_EMPTY")
        elif any(_BEAM_REDIRECT_HOST_PATTERN.fullmatch(host) is None for host in redirect_hosts):
            missing.append("BEAM_REDIRECT_ALLOWED_HOSTS_INVALID")
        if not self._beam_redirect_schemes_are_valid():
            missing.append("BEAM_REDIRECT_ALLOWED_SCHEMES_INVALID")
        return_url = urlparse(self.beam_return_url or "")
        return_hostname = (return_url.hostname or "").lower().rstrip(".")
        if (
            not return_hostname
            or return_url.scheme not in {"http", "https"}
            or (return_url.scheme == "http" and return_hostname not in {"localhost", "127.0.0.1"})
            or return_url.username is not None
            or return_url.password is not None
            or return_url.path.rstrip("/") != "/payment/result"
            or return_url.params
            or return_url.query
            or return_url.fragment
        ):
            missing.append("BEAM_RETURN_URL_INVALID")
        configured_schemes = self.configured_beam_redirect_allowed_schemes
        for method, required_scheme in _REQUIRED_BEAM_REDIRECT_SCHEMES.items():
            if (
                method in self.configured_beam_payment_methods
                and required_scheme not in configured_schemes.get(method, ())
            ):
                missing.append(f"BEAM_REDIRECT_SCHEME_MISSING_{method.value}")
        if self.deployment_environment == "prod":
            if (
                return_url.scheme != "https"
                or not return_url.hostname
                or "-test" in return_url.hostname
            ):
                missing.append("BEAM_PRODUCTION_RETURN_URL_INVALID")
            mobile_methods = {
                method
                for method in self.configured_beam_payment_methods
                if method is not BeamPaymentMethod.QR_PROMPT_PAY
            }
            if mobile_methods and not self.beam_production_mobile_banking_confirmed:
                missing.append("BEAM_PRODUCTION_MOBILE_BANKING_NOT_CONFIRMED")
            if not self.beam_production_webhook_registered:
                missing.append("BEAM_PRODUCTION_WEBHOOK_NOT_CONFIRMED")
        return tuple(missing)


@lru_cache
def get_settings() -> Settings:
    return Settings()
