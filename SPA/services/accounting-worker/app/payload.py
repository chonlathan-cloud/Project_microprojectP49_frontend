from decimal import Decimal
from typing import Any

from app.contracts import ExportProjection, PaymentSource
from app.settings import Settings


def satang_to_baht(value: int) -> str:
    return format(Decimal(value) / Decimal(100), ".2f")


def build_cash_invoice_payload(
    export: ExportProjection,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.ready_for_sync:
        raise ValueError(f"FlowAccount integration is not ready: {settings.readiness_errors()}")

    items: list[dict[str, Any]] = [
        {
            "productCode": line.sku,
            "name": line.name,
            "quantity": line.quantity,
            "unitPrice": satang_to_baht(line.unit_amount_satang),
            "vatRate": 7,
        }
        for line in export.service_lines
    ]
    if export.tip_amount_satang:
        items.append(
            {
                "productCode": "SPA-TIP",
                "name": f"ทิปสำหรับ Booking {export.booking_public_id}",
                "description": f"Tip for {export.booking_public_id}",
                "quantity": 1,
                "unitPrice": satang_to_baht(export.tip_amount_satang),
                "vatRate": 7,
            }
        )

    payment: dict[str, Any] = {
        "paymentMethod": 13 if export.payment_source is PaymentSource.BEAM else 1,
        "paymentDate": export.accounting_date.isoformat(),
        "amount": satang_to_baht(export.gross_amount_satang),
    }
    if export.payment_source is PaymentSource.BEAM:
        payment["otherChannelId"] = settings.other_channel_id

    payload: dict[str, Any] = {
        "publishedOn": export.accounting_date.isoformat(),
        "reference": export.external_reference,
        "externalDocumentId": export.external_document_id,
        "contactId": settings.contact_id,
        "projectName": settings.project_name,
        "isVat": True,
        "isVatInclusive": True,
        "vatRate": 7,
        "items": items,
        "payment": payment,
    }
    if settings.project_id:
        payload["projectId"] = settings.project_id
    if export.tip_amount_satang:
        payload["internalNotes"] = f"Tip for {export.booking_public_id}"
    return payload
