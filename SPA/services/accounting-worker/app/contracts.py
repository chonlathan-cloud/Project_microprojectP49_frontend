from datetime import date
from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class PaymentSource(StrEnum):
    BEAM = "BEAM"
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"


class ServiceLineSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(gt=0)
    unit_amount_satang: int = Field(
        gt=0,
        validation_alias=AliasChoices("unit_amount_satang", "unitAmountSatang"),
    )

    @property
    def total_satang(self) -> int:
        return self.quantity * self.unit_amount_satang


class ExportProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str
    payment_id: str
    booking_public_id: str
    accounting_date: date
    external_reference: str
    external_document_id: str = Field(max_length=36)
    payment_source: PaymentSource
    currency: str
    service_amount_satang: int = Field(gt=0)
    subtotal_amount_satang: int = Field(gt=0)
    discount_amount_satang: int = Field(ge=0)
    discount_reason: str | None = None
    tip_amount_satang: int = Field(ge=0)
    gross_amount_satang: int = Field(gt=0)
    service_lines: tuple[ServiceLineSnapshot, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_amounts(self) -> "ExportProjection":
        if self.currency != "THB":
            raise ValueError("FlowAccount SPA exports require THB")
        if self.service_amount_satang + self.tip_amount_satang != self.gross_amount_satang:
            raise ValueError("Gross amount must equal service amount plus tip")
        if sum(line.total_satang for line in self.service_lines) != self.subtotal_amount_satang:
            raise ValueError("Service lines must equal service subtotal")
        if self.subtotal_amount_satang - self.discount_amount_satang != self.service_amount_satang:
            raise ValueError("Service amount must equal subtotal minus discount")
        if self.discount_amount_satang and not (self.discount_reason or "").strip():
            raise ValueError("Discount reason is required")
        if not self.discount_amount_satang and self.discount_reason is not None:
            raise ValueError("Discount reason requires a discount")
        return self
