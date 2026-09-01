from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.contracts import ExportProjection, PaymentSource
from app.settings import Settings


def satang_to_baht(value: int) -> str:
    return format(Decimal(value) / Decimal(100), ".2f")


def vat_inclusive_amount(value_satang: int) -> str:
    gross = Decimal(value_satang) / Decimal(100)
    vat = (gross - (gross / Decimal("1.07"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return format(vat, ".2f")


def build_cash_invoice_payload(
    export: ExportProjection,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.ready_for_sync:
        raise ValueError(f"FlowAccount integration is not ready: {settings.readiness_errors()}")

    items: list[dict[str, Any]] = [
        {
            "sku": line.sku,
            "type": 1,
            "name": line.name,
            "description": line.sku,
            "quantity": line.quantity,
            "unitName": "บริการ",
            "pricePerUnit": satang_to_baht(line.unit_amount_satang),
            "total": satang_to_baht(line.total_satang),
            "sellChartOfAccountCode": settings.sell_chart_of_account_code,
        }
        for line in export.service_lines
    ]
    if export.tip_amount_satang:
        items.append(
            {
                "sku": "SPA-TIP",
                "type": 1,
                "name": f"ทิปสำหรับ Booking {export.booking_public_id}",
                "description": f"Tip for {export.booking_public_id}",
                "quantity": 1,
                "unitName": "รายการ",
                "pricePerUnit": satang_to_baht(export.tip_amount_satang),
                "total": satang_to_baht(export.tip_amount_satang),
                "sellChartOfAccountCode": settings.sell_chart_of_account_code,
            }
        )

    payment: dict[str, Any] = {
        "paymentMethod": 13 if export.payment_source is PaymentSource.BEAM else 1,
        "paymentDate": export.accounting_date.isoformat(),
        "collected": satang_to_baht(export.gross_amount_satang),
    }
    if export.payment_source is PaymentSource.BEAM:
        payment["otherChannelId"] = int(settings.other_channel_id or "0")

    payload: dict[str, Any] = {
        "publishedOn": export.accounting_date.isoformat(),
        "dueDate": export.accounting_date.isoformat(),
        "creditType": 3,
        "creditDays": 0,
        "reference": export.external_reference,
        "externalDocumentId": export.external_document_id,
        "contactId": int(settings.contact_id or "0"),
        "contactCode": settings.contact_code,
        "contactName": settings.contact_name,
        "contactGroup": 1,
        "projectName": settings.project_name,
        "documentPaymentStructureType": (
            "SimpleDocumentWithPaymentReceivingOtherChannel"
            if export.payment_source is PaymentSource.BEAM
            else "SimpleDocumentWithPaymentReceivingCash"
        ),
        "isVat": True,
        "isVatInclusive": True,
        "isManualVat": False,
        "subTotal": satang_to_baht(
            export.subtotal_amount_satang + export.tip_amount_satang
        ),
        "discountPercentage": "0.0000",
        "discountAmount": satang_to_baht(export.discount_amount_satang),
        "totalAfterDiscount": satang_to_baht(export.gross_amount_satang),
        "vatAmount": vat_inclusive_amount(export.gross_amount_satang),
        "grandTotal": satang_to_baht(export.gross_amount_satang),
        "documentShowWithholdingTax": False,
        "documentWithholdingTaxPercentage": 0,
        "documentWithholdingTaxAmount": "0.00",
        "items": items,
        **payment,
    }
    if settings.project_id:
        payload["projectId"] = settings.project_id
    if export.tip_amount_satang:
        payload["internalNotes"] = f"Tip for {export.booking_public_id}"
    return payload
