import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage

from app.application.cash_deposits import EvidenceAuthorization, VerifiedEvidence
from app.core.errors import CashDepositEvidenceInvalid, DependencyUnavailable
from app.core.settings import Settings


def _valid_magic(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type in {"image/heic", "image/heif"}:
        return (
            len(data) >= 12
            and data[4:8] == b"ftyp"
            and data[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
        )
    return False


class GcsCashEvidenceStore:
    def __init__(self, settings: Settings, client: storage.Client | None = None) -> None:
        self._settings = settings
        self._client = client or storage.Client(project=settings.gcp_project_id)
        self._bucket = self._client.bucket(settings.cash_evidence_bucket)

    def _signed_url(
        self,
        blob: storage.Blob,
        *,
        method: str,
        expires: timedelta,
        content_type: str | None = None,
        query_parameters: dict[str, str] | None = None,
    ) -> str:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
        return blob.generate_signed_url(
            version="v4",
            expiration=expires,
            method=method,
            content_type=content_type,
            query_parameters=query_parameters,
            service_account_email=self._settings.cash_evidence_signer_service_account,
            access_token=credentials.token,
        )

    async def authorize_upload(
        self, *, evidence_id: str, object_name: str, content_type: str
    ) -> EvidenceAuthorization:
        expires_at = datetime.now(UTC) + timedelta(
            minutes=self._settings.cash_evidence_upload_ttl_minutes
        )
        try:
            url = await asyncio.to_thread(
                self._signed_url,
                self._bucket.blob(object_name),
                method="PUT",
                expires=timedelta(minutes=self._settings.cash_evidence_upload_ttl_minutes),
                content_type=content_type,
                query_parameters={"ifGenerationMatch": "0"},
            )
        except Exception as error:
            raise DependencyUnavailable(
                "Cash evidence upload authorization is unavailable"
            ) from error
        return EvidenceAuthorization(evidence_id, url, object_name, expires_at)

    async def verify_upload(
        self,
        *,
        object_name: str,
        generation: int,
        expected_size_bytes: int,
        expected_content_type: str,
        expected_sha256: str,
    ) -> VerifiedEvidence:
        if not object_name.startswith("cash-deposits/") or generation <= 0:
            raise CashDepositEvidenceInvalid("Cash evidence object reference is invalid")

        def verify() -> VerifiedEvidence:
            blob = self._bucket.blob(object_name, generation=generation)
            blob.reload()
            if blob.size != expected_size_bytes or blob.content_type != expected_content_type:
                raise CashDepositEvidenceInvalid(
                    "Cash evidence metadata does not match authorization"
                )
            if not blob.size or blob.size > self._settings.cash_evidence_max_bytes:
                raise CashDepositEvidenceInvalid("Cash evidence size is invalid")
            data = blob.download_as_bytes(if_generation_match=generation)
            digest = hashlib.sha256(data).hexdigest()
            if digest != expected_sha256.lower() or not _valid_magic(expected_content_type, data):
                raise CashDepositEvidenceInvalid("Cash evidence content or checksum is invalid")
            if blob.md5_hash:
                actual_md5 = base64.b64encode(
                    hashlib.md5(data, usedforsecurity=False).digest()
                ).decode()
                if actual_md5 != blob.md5_hash:
                    raise CashDepositEvidenceInvalid("Cash evidence storage checksum is invalid")
            return VerifiedEvidence(generation, len(data), expected_content_type, digest)

        try:
            return await asyncio.to_thread(verify)
        except CashDepositEvidenceInvalid:
            raise
        except Exception as error:
            raise DependencyUnavailable("Cash evidence verification is unavailable") from error

    async def authorize_read(self, *, object_name: str, generation: int) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(
            minutes=self._settings.cash_evidence_read_ttl_minutes
        )
        try:
            url = await asyncio.to_thread(
                self._signed_url,
                self._bucket.blob(object_name, generation=generation),
                method="GET",
                expires=timedelta(minutes=self._settings.cash_evidence_read_ttl_minutes),
                query_parameters={"generation": str(generation)},
            )
        except Exception as error:
            raise DependencyUnavailable(
                "Cash evidence read authorization is unavailable"
            ) from error
        return url, expires_at
