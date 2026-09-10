import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class BankTransferAccount:
    key: str
    bank_account_id: str
    transfer_bank_account_id: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOWACCOUNT_", extra="ignore")

    environment: Literal["test", "prod"] = "test"
    sync_enabled: bool = False
    sandbox_contract_proven: bool = False
    api_base_url: str | None = None
    token_path: str = "/token"
    cash_invoice_with_payment_path: str = "/cash-invoices/with-payment"
    client_id: SecretStr | None = None
    client_secret: SecretStr | None = None
    expected_company_name: str = "Manee and Son Limited"
    project_name: str = "Spa 49"
    project_id: str | None = None
    contact_id: str | None = None
    contact_code: str = "SPA49-WALKIN"
    contact_name: str = "ลูกค้าทั่วไป - SPA 49"
    contact_path_template: str = "/contacts/{contactId}"
    other_channel_id: str | None = None
    other_channel_name: str = "Beam/UOB Gateway - SPA 49"
    sell_chart_of_account_code: str | None = None
    cash_invoice_list_path: str = "/cash-invoices"
    company_info_path: str = "/company/info"
    other_channels_path: str = "/bank-channel/other-channels"
    bank_accounts_path: str = "/bank-channel/bank-accounts"
    bank_account_id: str | None = None
    transfer_bank_id: str | None = None
    bank_accounts_json: str = "[]"
    document_url_template: str | None = None
    document_allowed_hosts: str = "flowaccount.com,*.flowaccount.com"
    admin_accounting_url: str | None = None
    request_timeout_seconds: float = 15.0
    gcp_project_id: str = "the49-487609"
    firestore_database: str | None = None
    oidc_audience: str | None = None
    allowed_invoker_emails: str = ""
    export_lease_seconds: int = 300
    nightly_batch_size: int = 100
    tasks_location: str = "asia-southeast1"
    tasks_queue: str | None = None
    worker_base_url: str | None = None
    tasks_invoker_service_account: str | None = None

    @property
    def expected_firestore_database(self) -> str:
        return "spa-test-db" if self.environment == "test" else "spa-db"

    @property
    def resolved_firestore_database(self) -> str:
        return self.firestore_database or self.expected_firestore_database

    @property
    def invoker_emails(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value.strip().lower()
                for value in self.allowed_invoker_emails.split(",")
                if value.strip()
            )
        )

    @property
    def allowed_document_hosts(self) -> tuple[str, ...]:
        return tuple(
            value.strip().lower().rstrip(".")
            for value in self.document_allowed_hosts.split(",")
            if value.strip()
        )

    def _bank_transfer_account_config(
        self,
    ) -> tuple[tuple[BankTransferAccount, ...], tuple[str, ...]]:
        try:
            raw = json.loads(self.bank_accounts_json)
        except (TypeError, json.JSONDecodeError):
            return (), ("BANK_ACCOUNTS_JSON_INVALID",)
        if not isinstance(raw, list):
            return (), ("BANK_ACCOUNTS_JSON_INVALID",)

        accounts: list[BankTransferAccount] = []
        keys: set[str] = set()
        provider_pairs: set[tuple[str, str]] = set()
        for item in raw:
            if not isinstance(item, dict):
                return (), ("BANK_ACCOUNTS_JSON_INVALID",)
            key = item.get("key")
            bank_account_id = item.get("bankAccountId")
            transfer_bank_account_id = item.get("transferBankAccountId")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (key, bank_account_id, transfer_bank_account_id)
            ):
                return (), ("BANK_ACCOUNTS_JSON_INVALID",)
            normalized_key = str(key).strip()
            normalized_account_id = str(bank_account_id).strip()
            normalized_bank_id = str(transfer_bank_account_id).strip()
            provider_pair = (normalized_account_id, normalized_bank_id)
            if (
                not normalized_account_id.isdigit()
                or int(normalized_account_id) <= 0
                or not normalized_bank_id.isdigit()
                or int(normalized_bank_id) <= 0
                or normalized_key in keys
                or provider_pair in provider_pairs
            ):
                return (), ("BANK_ACCOUNTS_JSON_INVALID",)
            keys.add(normalized_key)
            provider_pairs.add(provider_pair)
            accounts.append(
                BankTransferAccount(
                    key=normalized_key,
                    bank_account_id=normalized_account_id,
                    transfer_bank_account_id=normalized_bank_id,
                )
            )

        if accounts and (self.bank_account_id or self.transfer_bank_id):
            return (), ("BANK_TRANSFER_CONFIG_CONFLICT",)
        if not accounts and self.bank_account_id and self.transfer_bank_id:
            accounts.append(
                BankTransferAccount(
                    key="legacy-default",
                    bank_account_id=self.bank_account_id,
                    transfer_bank_account_id=self.transfer_bank_id,
                )
            )
        return tuple(accounts), ()

    @property
    def configured_bank_transfer_accounts(self) -> tuple[BankTransferAccount, ...]:
        return self._bank_transfer_account_config()[0]

    def bank_transfer_account(self, key: str | None) -> BankTransferAccount | None:
        if not key:
            return None
        return next(
            (account for account in self.configured_bank_transfer_accounts if account.key == key),
            None,
        )

    def flowaccount_readiness_errors(self) -> tuple[str, ...]:
        if not self.sync_enabled:
            return ("SYNC_DISABLED",)

        missing: list[str] = []
        required = {
            "SANDBOX_CONTRACT_NOT_PROVEN": self.sandbox_contract_proven,
            "CLIENT_ID_MISSING": self.client_id,
            "CLIENT_SECRET_MISSING": self.client_secret,
            "CONTACT_ID_MISSING": self.contact_id,
            "OTHER_CHANNEL_ID_MISSING": self.other_channel_id,
            "SELL_ACCOUNT_CODE_MISSING": self.sell_chart_of_account_code,
        }
        for code, value in required.items():
            if not value:
                missing.append(code)
        for code, value in (
            ("CONTACT_ID_INVALID", self.contact_id),
            ("OTHER_CHANNEL_ID_INVALID", self.other_channel_id),
            ("BANK_ACCOUNT_ID_INVALID", self.bank_account_id),
            ("TRANSFER_BANK_ID_INVALID", self.transfer_bank_id),
        ):
            if value and (not value.isdigit() or int(value) <= 0):
                missing.append(code)
        if bool(self.bank_account_id) != bool(self.transfer_bank_id):
            missing.append("BANK_TRANSFER_CONFIG_INCOMPLETE")
        missing.extend(self._bank_transfer_account_config()[1])
        if not self.api_base_url:
            missing.append("API_BASE_URL_MISSING")
        elif not self.api_base_url.startswith("https://"):
            missing.append("API_BASE_URL_INVALID")
        elif self.environment == "test" and self.api_base_url.rstrip("/") == (
            "https://openapi.flowaccount.com/v1"
        ):
            missing.append("TEST_USES_PRODUCTION_URL")
        elif self.environment == "prod" and self.api_base_url.rstrip("/") != (
            "https://openapi.flowaccount.com/v1"
        ):
            missing.append("PRODUCTION_API_BASE_URL_INVALID")
        return tuple(missing)

    def runtime_readiness_errors(self) -> tuple[str, ...]:
        missing = list(self.flowaccount_readiness_errors())
        if missing == ["SYNC_DISABLED"]:
            return tuple(missing)
        if self.gcp_project_id != "the49-487609":
            missing.append("GCP_PROJECT_INVALID")
        if self.resolved_firestore_database != self.expected_firestore_database:
            missing.append("FIRESTORE_DATABASE_ENVIRONMENT_MISMATCH")
        if not self.oidc_audience:
            missing.append("OIDC_AUDIENCE_MISSING")
        if not self.invoker_emails:
            missing.append("OIDC_INVOKERS_MISSING")
        if not self.tasks_queue:
            missing.append("TASKS_QUEUE_MISSING")
        if not self.worker_base_url:
            missing.append("WORKER_BASE_URL_MISSING")
        if not self.tasks_invoker_service_account:
            missing.append("TASKS_INVOKER_SERVICE_ACCOUNT_MISSING")
        if not self.admin_accounting_url:
            missing.append("ADMIN_ACCOUNTING_URL_MISSING")
        elif (
            self.environment == "prod"
            and not self.admin_accounting_url.startswith("https://")
        ) or (
            self.environment == "test"
            and not self.admin_accounting_url.startswith(
                ("https://", "http://localhost")
            )
        ):
            missing.append("ADMIN_ACCOUNTING_URL_INVALID")
        if self.export_lease_seconds < 30:
            missing.append("EXPORT_LEASE_INVALID")
        if not 1 <= self.nightly_batch_size <= 100:
            missing.append("NIGHTLY_BATCH_SIZE_INVALID")
        return tuple(missing)

    def readiness_errors(self) -> tuple[str, ...]:
        """Compatibility name for the external FlowAccount contract gate."""
        return self.flowaccount_readiness_errors()

    @property
    def ready_for_sync(self) -> bool:
        return not self.flowaccount_readiness_errors()


@lru_cache
def get_settings() -> Settings:
    return Settings()
