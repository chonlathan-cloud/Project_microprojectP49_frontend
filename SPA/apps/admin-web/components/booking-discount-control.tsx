"use client";

import type { User } from "firebase/auth";
import { useEffect, useMemo, useState } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { adminApi } from "@/lib/admin-api";
import type { Locale } from "@spa/shared-types";

export type BookingDiscountUpdate = {
  bookingId: string;
  bookingVersion: number;
  subtotalAmountSatang: number;
  discountAmountSatang: number;
  discountReason: string | null;
  serviceAmountSatang: number;
  tipAmountSatang: number;
  grossAmountSatang: number;
  paymentStatus: string;
  paymentVersion: number;
  settlementStale: boolean;
};

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

export function BookingDiscountControl({
  bookingId,
  bookingVersion,
  subtotalAmountSatang,
  discountAmountSatang,
  discountReason,
  disabled,
  locale,
  user,
  onEditingChange,
  onSaved,
}: {
  bookingId: string;
  bookingVersion: number;
  subtotalAmountSatang: number;
  discountAmountSatang: number;
  discountReason?: string;
  disabled: boolean;
  locale: Locale;
  user: User;
  onEditingChange: (editing: boolean) => void;
  onSaved: (result: BookingDiscountUpdate) => void;
}) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const [editing, setEditing] = useState(false);
  const [amountBaht, setAmountBaht] = useState(String(discountAmountSatang / 100));
  const [reason, setReason] = useState(discountReason ?? "");
  const [state, setState] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState("");

  useEffect(() => () => onEditingChange(false), [onEditingChange]);

  const amount = Number(amountBaht);
  const amountSatang = Number.isInteger(amount) ? amount * 100 : Number.NaN;
  const normalizedReason = reason.trim();
  const valid = Number.isFinite(amountSatang)
    && amountSatang >= 0
    && amountSatang < subtotalAmountSatang
    && normalizedReason.length > 0
    && normalizedReason.length <= 200;
  const changed = valid && (
    amountSatang !== discountAmountSatang
    || (amountSatang > 0 && normalizedReason !== (discountReason ?? "").trim())
    || (amountSatang === 0 && discountAmountSatang > 0)
  );
  const previewNet = useMemo(
    () => Number.isFinite(amountSatang) ? subtotalAmountSatang - amountSatang : subtotalAmountSatang,
    [amountSatang, subtotalAmountSatang],
  );

  function openEditor(remove = false) {
    setAmountBaht(remove ? "0" : String(discountAmountSatang / 100));
    setReason(remove ? "" : discountReason ?? "");
    setError("");
    setState("idle");
    setEditing(true);
    onEditingChange(true);
  }

  function closeEditor() {
    if (state === "saving") return;
    setEditing(false);
    setAmountBaht(String(discountAmountSatang / 100));
    setReason(discountReason ?? "");
    setError("");
    onEditingChange(false);
  }

  async function saveDiscount() {
    if (!changed || state === "saving") return;
    const removing = amountSatang === 0;
    const confirmation = await requestConfirmation({
      title: removing
        ? (locale === "th" ? "ยืนยันยกเลิกส่วนลด?" : "Remove this discount?")
        : (locale === "th" ? "ยืนยันส่วนลดก่อนชำระเงิน?" : "Confirm discount before payment?"),
      message: locale === "th"
        ? `ราคาปกติ ${baht(subtotalAmountSatang, locale)} • ส่วนลด ${baht(amountSatang, locale)} • ค่าบริการสุทธิ ${baht(previewNet, locale)} ส่วนลดนี้เป็น Promotion ของร้านและไม่ลดค่าหมอ`
        : `Regular price ${baht(subtotalAmountSatang, locale)} • discount ${baht(amountSatang, locale)} • net service ${baht(previewNet, locale)}. This shop promotion does not reduce therapist pay.`,
      confirmLabel: removing
        ? (locale === "th" ? "ยืนยันยกเลิกส่วนลด" : "Remove discount")
        : (locale === "th" ? "ยืนยันส่วนลด" : "Apply discount"),
      cancelLabel: locale === "th" ? "กลับไปตรวจ" : "Review again",
      tone: removing ? "danger" : undefined,
    });
    if (!confirmation.confirmed) return;

    setState("saving");
    setError("");
    try {
      const result = await adminApi<BookingDiscountUpdate>(
        user,
        `/bookings/${encodeURIComponent(bookingId)}/discount`,
        {
          method: "PUT",
          body: JSON.stringify({
            discountAmountSatang: amountSatang,
            discountReason: normalizedReason,
            expectedVersion: bookingVersion,
          }),
        },
      );
      onSaved(result);
      setEditing(false);
      onEditingChange(false);
      setState("idle");
      notify({
        tone: "success",
        title: removing
          ? (locale === "th" ? "ยกเลิกส่วนลดแล้ว" : "Discount removed")
          : (locale === "th" ? "บันทึกส่วนลดแล้ว" : "Discount saved"),
        message: result.settlementStale
          ? (locale === "th" ? "สรุปค่าหมอเดิมต้องตรวจและบันทึกใหม่" : "The existing settlement must be reviewed and saved again.")
          : `${bookingId} • ${baht(result.serviceAmountSatang, locale)}`,
      });
    } catch (caught) {
      setState("error");
      setError(caught instanceof Error ? caught.message : "Discount update failed");
    }
  }

  if (!editing) {
    return <div className="admin-discount-summary">
      <div>
        <span>{locale === "th" ? "ส่วนลดของร้าน" : "Shop discount"}</span>
        <strong>{discountAmountSatang > 0 ? `−${baht(discountAmountSatang, locale)}` : "—"}</strong>
        {discountReason && discountAmountSatang > 0 && <small>{discountReason}</small>}
      </div>
      {!disabled && <div className="admin-discount-actions">
        <button type="button" onClick={() => openEditor()}>{discountAmountSatang > 0 ? (locale === "th" ? "แก้ไข" : "Edit") : (locale === "th" ? "เพิ่มส่วนลด" : "Add discount")}</button>
        {discountAmountSatang > 0 && <button type="button" className="discount-remove" onClick={() => openEditor(true)}>{locale === "th" ? "ยกเลิกส่วนลด" : "Remove"}</button>}
      </div>}
    </div>;
  }

  return <div className="admin-discount-editor">
    <div className="admin-discount-editor-heading">
      <strong>{locale === "th" ? "ส่วนลดก่อนชำระเงิน" : "Discount before payment"}</strong>
      <span>{locale === "th" ? "จำนวนเงินบาทเต็ม" : "Whole THB amount"}</span>
    </div>
    <label>
      <span>{locale === "th" ? "ส่วนลด (บาท)" : "Discount (THB)"}</span>
      <input type="number" min="0" max={Math.max(0, subtotalAmountSatang / 100 - 1)} step="1" inputMode="numeric" value={amountBaht} disabled={state === "saving"} onChange={(event) => setAmountBaht(event.target.value)} />
    </label>
    <label>
      <span>{locale === "th" ? "เหตุผลหรือชื่อ Promotion" : "Reason or promotion name"}</span>
      <input list="booking-discount-reasons" maxLength={200} value={reason} disabled={state === "saving"} placeholder={locale === "th" ? "เช่น ลูกค้าประจำ" : "e.g. Loyal customer"} onChange={(event) => setReason(event.target.value)} />
      <datalist id="booking-discount-reasons">
        <option value={locale === "th" ? "ลูกค้าประจำ" : "Loyal customer"} />
        <option value={locale === "th" ? "คูปองสมัครครั้งแรก" : "First-visit coupon"} />
        <option value={locale === "th" ? "ชดเชยบริการ" : "Service recovery"} />
        <option value={locale === "th" ? "แก้ไขข้อมูลส่วนลดที่บันทึกผิด" : "Correct an incorrect discount"} />
      </datalist>
    </label>
    <div className="admin-discount-preview" aria-live="polite"><span>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service"}</span><strong>{valid ? baht(previewNet, locale) : "—"}</strong></div>
    {!valid && <p className="admin-discount-validation">{locale === "th" ? "กรอกส่วนลดเป็นจำนวนบาทเต็ม น้อยกว่าราคาปกติ และระบุเหตุผล" : "Enter a whole-THB discount below the regular price and add a reason."}</p>}
    {error && <p className="admin-discount-validation" role="alert">{error}</p>}
    <div className="admin-discount-editor-actions">
      <button type="button" disabled={state === "saving"} onClick={closeEditor}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button>
      <button type="button" className="confirm-button" disabled={!changed || state === "saving"} onClick={() => { void saveDiscount(); }}>{state === "saving" ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "บันทึกส่วนลด" : "Save discount")}</button>
    </div>
  </div>;
}
