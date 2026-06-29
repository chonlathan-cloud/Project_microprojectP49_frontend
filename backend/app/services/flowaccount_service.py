import json
import mimetypes
import time
import uuid
from datetime import datetime
from threading import Lock
from urllib import error, parse, request

from google.cloud import storage

from app.core.config import settings


class FlowAccountConfigurationError(Exception):
    """Raised when FlowAccount sync is disabled or missing required settings."""


class FlowAccountAPIError(Exception):
    """Raised when FlowAccount returns an unsuccessful response."""


_token_lock = Lock()
_cached_access_token: str | None = None
_cached_token_expires_at = 0.0
_SENSITIVE_RESPONSE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "secret",
    "token",
}

_SUPPORTED_PAYMENT_METHODS = {"CASH", "TRANSFER"}


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _round_money(value: object) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _safe_text(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text.lower() in {"none", "null", "undefined"}:
        text = ""
    return text or fallback


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value or fallback)
    except (TypeError, ValueError):
        return fallback


def _normalize_payment_method(payment_method: str | None = None) -> str:
    method = _safe_text(payment_method, settings.FLOWACCOUNT_DEFAULT_PAYMENT_METHOD).upper()
    if method in {"BANK_TRANSFER", "TRANSFER"}:
        return "TRANSFER"
    if method == "CASH":
        return "CASH"
    raise FlowAccountConfigurationError(
        "FlowAccount payment method must be CASH or TRANSFER."
    )


def _get_header(receipt: dict) -> dict:
    header = receipt.get("header")
    return header if isinstance(header, dict) else {}


def _get_ocr_payload(receipt: dict) -> dict:
    payload = receipt.get("OCRbyGemini")
    return payload if isinstance(payload, dict) else {}


def _get_seller_payload(receipt: dict) -> dict:
    top_level_seller = receipt.get("seller")
    if isinstance(top_level_seller, dict) and any(top_level_seller.values()):
        return top_level_seller

    ocr_seller = _get_ocr_payload(receipt).get("seller")
    if isinstance(ocr_seller, dict):
        return ocr_seller
    return {}


def _normalize_tax_id(value: object) -> str:
    digits = "".join(char for char in _safe_text(value) if char.isdigit())
    return digits if len(digits) == 13 else ""


def _contact_group_from_name(name: str) -> int:
    normalized = name.lower()
    if any(marker in normalized for marker in ("บริษัท", "จำกัด", "co.", "ltd", "limited")):
        return 3
    return 1


def _seller_contact_fields(receipt: dict, fallback_name: str) -> dict:
    seller = _get_seller_payload(receipt)
    contact_name = _safe_text(
        seller.get("legal_name") or seller.get("brand_name"),
        fallback_name,
    )
    fields = {
        "contactName": contact_name,
        "contactGroup": _contact_group_from_name(contact_name),
    }

    optional_fields = {
        "contactAddress": _safe_text(seller.get("address")),
        "contactTaxId": _normalize_tax_id(seller.get("tax_id")),
        "contactBranch": _safe_text(seller.get("branch_name")),
        "contactPerson": _safe_text(seller.get("contact_person")),
        "contactEmail": _safe_text(seller.get("email")),
        "contactNumber": _safe_text(seller.get("phone")),
    }
    for key, value in optional_fields.items():
        if value:
            fields[key] = value
    return fields


def _redact_response_json(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(sensitive in normalized_key for sensitive in _SENSITIVE_RESPONSE_KEYS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_response_json(item)
        return redacted
    if isinstance(value, list):
        return [_redact_response_json(item) for item in value]
    return value


def _sanitize_error_body(raw_body: bytes) -> str:
    text = raw_body.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
        text = json.dumps(_redact_response_json(parsed), ensure_ascii=False)
    except json.JSONDecodeError:
        pass
    if len(text) > 600:
        return f"{text[:600]}..."
    return text


def _http_error_message(method: str, path: str, exc: error.HTTPError) -> str:
    body = _sanitize_error_body(exc.read())
    message = f"FlowAccount {method} {path} failed with HTTP {exc.code}."
    if body:
        message = f"{message} Response: {body}"
    return message


def get_expense_config_missing(
    payment_method: str | None = None,
    bank_account_id: int | None = None,
) -> list[str]:
    required_int_settings = (
        ("FLOWACCOUNT_EXPENSE_SYSTEM_CODE", settings.FLOWACCOUNT_EXPENSE_SYSTEM_CODE),
        ("FLOWACCOUNT_EXPENSE_CATEGORY_ID", settings.FLOWACCOUNT_EXPENSE_CATEGORY_ID),
        ("FLOWACCOUNT_EXPENSE_CREDIT_ID", settings.FLOWACCOUNT_EXPENSE_CREDIT_ID),
        (
            "FLOWACCOUNT_EXPENSE_CREDIT_CATEGORY",
            settings.FLOWACCOUNT_EXPENSE_CREDIT_CATEGORY,
        ),
        ("FLOWACCOUNT_EXPENSE_DEBIT_ID", settings.FLOWACCOUNT_EXPENSE_DEBIT_ID),
        (
            "FLOWACCOUNT_EXPENSE_DEBIT_CATEGORY",
            settings.FLOWACCOUNT_EXPENSE_DEBIT_CATEGORY,
        ),
    )
    missing = [name for name, value in required_int_settings if int(value or 0) <= 0]
    method = _normalize_payment_method(payment_method)
    if method == "TRANSFER":
        effective_bank_account_id = bank_account_id or settings.FLOWACCOUNT_BANK_ACCOUNT_ID
        if effective_bank_account_id <= 0:
            missing.append("FLOWACCOUNT_BANK_ACCOUNT_ID")
    return missing


def ensure_expense_configured(
    payment_method: str | None = None,
    bank_account_id: int | None = None,
) -> None:
    _normalize_payment_method(payment_method)
    missing = get_expense_config_missing(payment_method, bank_account_id)
    if missing:
        raise FlowAccountConfigurationError(
            "FlowAccount expense configuration is incomplete. Set: "
            + ", ".join(missing)
        )


def is_configured() -> bool:
    return bool(settings.FLOWACCOUNT_CLIENT_ID and settings.FLOWACCOUNT_CLIENT_SECRET)


def get_status() -> dict:
    base_url = settings.FLOWACCOUNT_BASE_URL
    environment = "sandbox" if "/test" in base_url else "production"
    expense_config_missing = get_expense_config_missing()
    return {
        "enabled": settings.FLOWACCOUNT_ENABLED,
        "configured": is_configured(),
        "base_url": base_url,
        "environment": environment,
        "expense_configured": not expense_config_missing,
        "expense_config_missing": expense_config_missing,
    }


def ensure_configured() -> None:
    if not settings.FLOWACCOUNT_ENABLED:
        raise FlowAccountConfigurationError("FlowAccount sync is disabled.")
    if not is_configured():
        raise FlowAccountConfigurationError("FlowAccount is not configured.")


def _read_json_response(response) -> dict:
    body = response.read().decode("utf-8")
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise FlowAccountAPIError("FlowAccount returned an invalid JSON response.") from exc


def _request_json(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
    form_payload: dict | None = None,
) -> dict:
    url = f"{settings.FLOWACCOUNT_BASE_URL}{path}"
    request_headers = dict(headers or {})
    data: bytes | None = None

    if form_payload is not None:
        data = parse.urlencode(form_payload).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=data, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=settings.FLOWACCOUNT_TIMEOUT_SECONDS) as response:
            return _read_json_response(response)
    except error.HTTPError as exc:
        raise FlowAccountAPIError(_http_error_message(method, path, exc)) from exc
    except error.URLError as exc:
        raise FlowAccountAPIError(f"FlowAccount {method} {path} request failed.") from exc


def get_access_token() -> str:
    ensure_configured()

    global _cached_access_token, _cached_token_expires_at
    now = time.time()
    with _token_lock:
        if _cached_access_token and now < _cached_token_expires_at - 300:
            return _cached_access_token

        form = {
            "grant_type": "client_credentials",
            "scope": settings.FLOWACCOUNT_SCOPE,
            "client_id": settings.FLOWACCOUNT_CLIENT_ID,
            "client_secret": settings.FLOWACCOUNT_CLIENT_SECRET,
        }
        if settings.FLOWACCOUNT_GUID:
            form["guid"] = settings.FLOWACCOUNT_GUID

        response = _request_json("POST", "/token", form_payload=form)
        access_token = _safe_text(response.get("access_token"))
        if not access_token:
            raise FlowAccountAPIError("FlowAccount token response did not include an access token.")

        expires_in = int(response.get("expires_in") or settings.FLOWACCOUNT_TOKEN_CACHE_SECONDS)
        _cached_access_token = access_token
        _cached_token_expires_at = now + min(expires_in, settings.FLOWACCOUNT_TOKEN_CACHE_SECONDS)
        return access_token


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_access_token()}"}


def _payment_fields(
    payment_date: str,
    total: float,
    payment_method: str | None = None,
    bank_account_id: int | None = None,
    transfer_bank_id: int | None = None,
) -> dict:
    method = _normalize_payment_method(payment_method)
    if method == "TRANSFER":
        effective_bank_account_id = bank_account_id or settings.FLOWACCOUNT_BANK_ACCOUNT_ID
        if effective_bank_account_id <= 0:
            raise FlowAccountConfigurationError(
                "A FlowAccount bank account is required for transfer payment."
            )
        fields = {
            "expensePaymentStructureType": "ExpenseSimpleDocumentWithPaymentPaidTransfer",
            "paymentMethod": 5,
            "paymentDate": payment_date,
            "collected": total,
            "paymentCharge": 0,
            "bankAccountId": effective_bank_account_id,
            "paymentRemarks": "Synced from The 49",
        }
        if transfer_bank_id and transfer_bank_id > 0:
            fields["transferBankAccountId"] = transfer_bank_id
        return fields

    return {
        "expensePaymentStructureType": "ExpenseSimpleDocumentWithPaymentPaidCash",
        "paymentMethod": 1,
        "paymentDate": payment_date,
        "collected": total,
        "paymentRemarks": "Synced from The 49",
    }


def _expense_item(description: str, amount: float, category_name: str | None = None) -> dict:
    display_name = _safe_text(category_name, description)[:120]
    return {
        "systemCode": settings.FLOWACCOUNT_EXPENSE_SYSTEM_CODE,
        "categoryId": settings.FLOWACCOUNT_EXPENSE_CATEGORY_ID,
        "description": description,
        "nameLocal": display_name,
        "nameForeign": display_name,
        "creditId": settings.FLOWACCOUNT_EXPENSE_CREDIT_ID,
        "creditCategory": settings.FLOWACCOUNT_EXPENSE_CREDIT_CATEGORY,
        "creditCode": settings.FLOWACCOUNT_EXPENSE_CREDIT_CODE,
        "creditNameLocal": settings.FLOWACCOUNT_EXPENSE_CREDIT_NAME_LOCAL,
        "creditNameForeign": settings.FLOWACCOUNT_EXPENSE_CREDIT_NAME_FOREIGN,
        "debitId": settings.FLOWACCOUNT_EXPENSE_DEBIT_ID,
        "debitCategory": settings.FLOWACCOUNT_EXPENSE_DEBIT_CATEGORY,
        "debitCode": settings.FLOWACCOUNT_EXPENSE_DEBIT_CODE,
        "debitNameLocal": settings.FLOWACCOUNT_EXPENSE_DEBIT_NAME_LOCAL,
        "debitNameForeign": settings.FLOWACCOUNT_EXPENSE_DEBIT_NAME_FOREIGN,
        "quantity": 1,
        "unitName": "item",
        "pricePerUnit": amount,
        "total": amount,
    }


def build_paid_expense_payload(
    receipt: dict,
    branch: dict,
    payment_method: str | None = None,
    bank_account_id: int | None = None,
    transfer_bank_id: int | None = None,
) -> dict:
    ensure_expense_configured(payment_method, bank_account_id)

    header = _get_header(receipt)
    receipt_id = _safe_text(receipt.get("id"), "unknown")
    document_date = _safe_text(header.get("date"), datetime.utcnow().date().isoformat())
    merchant_name = _safe_text(
        header.get("merchant"),
        _safe_text(receipt.get("merchant_name"), "Receipt Vendor"),
    )
    branch_name = _safe_text(branch.get("name"), _safe_text(receipt.get("branch_id"), ""))

    items: list[dict] = []
    for item in receipt.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        amount = _round_money(item.get("amount"))
        if amount <= 0:
            continue
        description = _safe_text(item.get("description"), "Receipt item")
        items.append(_expense_item(description, amount, item.get("category_name")))

    discount_amount = 0.0
    for adjustment in receipt.get("adjustments", []) or []:
        if not isinstance(adjustment, dict):
            continue
        amount = _round_money(adjustment.get("amount"))
        if amount <= 0:
            continue
        if adjustment.get("type") == "discount":
            discount_amount += amount
        else:
            description = _safe_text(adjustment.get("label"), "Receipt adjustment")
            items.append(_expense_item(description, amount, description))

    if not items:
        fallback_total = _round_money(
            receipt.get("total_check")
            or receipt.get("total_amount")
            or header.get("total")
        )
        if fallback_total <= 0:
            raise FlowAccountConfigurationError("Receipt has no positive amount to sync.")
        items.append(_expense_item("Receipt total", fallback_total, "Receipt total"))

    subtotal = _round_money(sum(_round_money(item.get("total")) for item in items))
    discount_amount = _round_money(discount_amount)
    grand_total = _round_money(
        receipt.get("total_check")
        or receipt.get("total_amount")
        or (subtotal - discount_amount)
    )
    total_after_discount = _round_money(max(grand_total, subtotal - discount_amount))

    payload = {
        "publishedOn": document_date,
        "creditType": 3,
        "creditDays": 0,
        "dueDate": document_date,
        "projectName": branch_name,
        "reference": receipt_id,
        "isVatInclusive": False,
        "isManualVat": False,
        "expenseCategoryView": 3,
        "subTotal": subtotal,
        "discountPercentage": 0,
        "discountAmount": discount_amount,
        "totalAfterDiscount": total_after_discount,
        "isVat": False,
        "vatAmount": 0,
        "grandTotal": grand_total,
        "remarks": f"Synced from The 49 receipt {receipt_id}",
        "internalNotes": f"The49 receipt_id={receipt_id}",
        "showSignatureOrStamp": False,
        "externalDocumentId": receipt_id,
        "items": items,
        "withheldPercentage": 0,
        "withheldAmount": 0,
    }
    payload.update(_seller_contact_fields(receipt, merchant_name))
    payload.update(
        _payment_fields(
            document_date,
            grand_total,
            payment_method=payment_method,
            bank_account_id=bank_account_id,
            transfer_bank_id=transfer_bank_id,
        )
    )
    return payload


def create_paid_expense_from_receipt(
    receipt: dict,
    branch: dict,
    payment_method: str | None = None,
    bank_account_id: int | None = None,
    transfer_bank_id: int | None = None,
) -> dict:
    ensure_configured()
    payload = build_paid_expense_payload(
        receipt,
        branch,
        payment_method=payment_method,
        bank_account_id=bank_account_id,
        transfer_bank_id=transfer_bank_id,
    )
    response = _request_json(
        "POST",
        "/expenses/with-payment",
        headers=_auth_headers(),
        payload=payload,
    )
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    if not isinstance(data, dict):
        raise FlowAccountAPIError("FlowAccount paid expense response is invalid.")
    return data


def _mask_account_number(account_number: object) -> str:
    raw = _safe_text(account_number)
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) >= 4:
        return f"****{digits[-4:]}"
    return raw


def _bank_account_label(account: dict) -> str:
    bank_name = _safe_text(account.get("bankName"), "Bank")
    account_name = _safe_text(account.get("bankAccountName"), "Account")
    masked_number = _mask_account_number(account.get("bankAccountNumber"))
    parts = [bank_name, account_name]
    if masked_number:
        parts.append(masked_number)
    return " - ".join(parts)


def list_bank_accounts() -> list[dict]:
    ensure_configured()
    response = _request_json(
        "GET",
        "/bank-channel/bank-accounts",
        headers=_auth_headers(),
    )
    raw_accounts = response.get("data") if isinstance(response, dict) else []
    if not isinstance(raw_accounts, list):
        raise FlowAccountAPIError("FlowAccount bank account response is invalid.")

    accounts: list[dict] = []
    for account in raw_accounts:
        if not isinstance(account, dict):
            continue
        bank_account_id = _safe_int(account.get("bankAccountId"))
        if bank_account_id <= 0:
            continue
        accounts.append(
            {
                "bank_account_id": bank_account_id,
                "bank_id": _safe_int(account.get("bankId")),
                "bank_name": _safe_text(account.get("bankName"), "Bank"),
                "bank_account_name": _safe_text(account.get("bankAccountName"), "Account"),
                "bank_account_number_masked": _mask_account_number(
                    account.get("bankAccountNumber")
                ),
                "bank_account_type": _safe_int(account.get("bankAccountType")),
                "bank_branch": _safe_text(account.get("bankBranch")),
                "label": _bank_account_label(account),
            }
        )
    return accounts


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str] | None:
    if not gcs_uri.startswith("gs://"):
        return None
    without_scheme = gcs_uri[5:]
    if "/" not in without_scheme:
        return None
    bucket_name, blob_name = without_scheme.split("/", 1)
    if not bucket_name or not blob_name:
        return None
    return bucket_name, blob_name


def _download_receipt_file(receipt: dict) -> tuple[bytes, str, str]:
    image_url = _safe_text(receipt.get("image_url"))
    if not image_url:
        raise FlowAccountConfigurationError("Receipt image is missing.")

    if image_url.startswith("gs://"):
        parsed = _parse_gcs_uri(image_url)
        if not parsed:
            raise FlowAccountConfigurationError("Receipt image URL is invalid.")
        bucket_name, blob_name = parsed
        client = storage.Client(project=settings.GCP_PROJECT_ID)
        blob = client.bucket(bucket_name).blob(blob_name)
        content = blob.download_as_bytes()
        filename = blob_name.rsplit("/", 1)[-1] or f"receipt-{receipt.get('id', 'file')}"
        content_type = (
            blob.content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        return content, filename, content_type

    if image_url.startswith("http://") or image_url.startswith("https://"):
        req = request.Request(image_url, method="GET")
        try:
            with request.urlopen(req, timeout=settings.FLOWACCOUNT_TIMEOUT_SECONDS) as response:
                content = response.read()
                content_type = response.headers.get_content_type() or "application/octet-stream"
        except error.URLError as exc:
            raise FlowAccountAPIError("Failed to download receipt image.") from exc
        filename = image_url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "receipt"
        return content, filename, content_type

    raise FlowAccountConfigurationError("Receipt image URL is not supported.")


def attach_receipt_file(flowaccount_record_id: str, receipt: dict) -> dict:
    ensure_configured()
    content, filename, content_type = _download_receipt_file(receipt)
    boundary = f"----the49-flowaccount-{uuid.uuid4().hex}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            content,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    headers = _auth_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    url = f"{settings.FLOWACCOUNT_BASE_URL}/expenses/{flowaccount_record_id}/attachment"
    req = request.Request(url=url, data=body, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=settings.FLOWACCOUNT_TIMEOUT_SECONDS) as response:
            return _read_json_response(response)
    except error.HTTPError as exc:
        raise FlowAccountAPIError(
            _http_error_message("POST", f"/expenses/{flowaccount_record_id}/attachment", exc)
        ) from exc
    except error.URLError as exc:
        raise FlowAccountAPIError("FlowAccount attachment request failed.") from exc
