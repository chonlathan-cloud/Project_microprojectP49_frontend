"use client";

import type { Locale } from "@spa/shared-types";
import { useEffect, useId, useRef, useState } from "react";

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

export function StartServiceDialog({
  bookingId,
  serviceName,
  therapistName,
  subtotalAmountSatang,
  discountAmountSatang,
  discountReason,
  role,
  locale,
  submitting,
  error,
  onClose,
  onConfirm,
}: {
  bookingId: string;
  serviceName: string;
  therapistName: string;
  subtotalAmountSatang: number;
  discountAmountSatang: number;
  discountReason?: string;
  role: "ADMIN" | "STAFF";
  locale: Locale;
  submitting: boolean;
  error: string;
  onClose: () => void;
  onConfirm: (discountAmountSatang?: number, discountReason?: string) => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const reasonListId = useId();
  const [amountBaht, setAmountBaht] = useState(String(discountAmountSatang / 100));
  const [reason, setReason] = useState(discountReason ?? "");

  const normalizedAmount = amountBaht.trim() || "0";
  const amount = Number(normalizedAmount);
  const amountIsWholeBaht = /^\d+$/.test(normalizedAmount) && Number.isSafeInteger(amount);
  const nextDiscountAmountSatang = amountIsWholeBaht ? amount * 100 : Number.NaN;
  const validAmount = Number.isFinite(nextDiscountAmountSatang)
    && nextDiscountAmountSatang >= 0
    && nextDiscountAmountSatang < subtotalAmountSatang;
  const removingDiscount = discountAmountSatang > 0 && nextDiscountAmountSatang === 0;
  const reasonRequired = nextDiscountAmountSatang > 0 || removingDiscount;
  const validReason = !reasonRequired || (reason.trim().length > 0 && reason.trim().length <= 200);
  const valid = role === "STAFF" || (validAmount && validReason);
  const netAmountSatang = validAmount
    ? subtotalAmountSatang - nextDiscountAmountSatang
    : subtotalAmountSatang;

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [onClose, submitting]);

  async function submit() {
    if (!valid || submitting) return;
    if (role === "STAFF") {
      await onConfirm();
      return;
    }
    await onConfirm(nextDiscountAmountSatang, reason.trim());
  }

  return <div
    className="modal-backdrop start-service-backdrop"
    onMouseDown={(event) => {
      if (event.target === event.currentTarget && !submitting) onClose();
    }}
  >
    <div ref={dialogRef} className="start-service-dialog" role="dialog" aria-modal="true" aria-labelledby="start-service-title" aria-describedby="start-service-description">
      <div className="drawer-header start-service-header">
        <div>
          <p className="eyebrow">{bookingId}</p>
          <h2 id="start-service-title">{locale === "th" ? "ตรวจสอบก่อนเริ่มให้บริการ" : "Review before starting service"}</h2>
          <p id="start-service-description">{locale === "th" ? "ตรวจหมอนวดและยอดค่าบริการให้ถูกต้องก่อนเปลี่ยนสถานะ" : "Confirm the therapist and service amount before changing status."}</p>
        </div>
        <button ref={closeButtonRef} type="button" disabled={submitting} aria-label={locale === "th" ? "ปิดหน้าต่าง" : "Close dialog"} onClick={onClose}>×</button>
      </div>

      <div className="start-service-body">
        <dl className="start-service-context">
          <div><dt>{locale === "th" ? "บริการ" : "Service"}</dt><dd>{serviceName}</dd></div>
          <div><dt>{locale === "th" ? "หมอนวด" : "Therapist"}</dt><dd>{therapistName}</dd></div>
        </dl>

        <section className="start-service-financial" aria-labelledby="start-service-financial-title">
          <div className="start-service-section-heading">
            <div><p className="eyebrow">SERVICE AMOUNT</p><h3 id="start-service-financial-title">{locale === "th" ? "ราคาและส่วนลด" : "Price & discount"}</h3></div>
            {role === "ADMIN" ? <span>{locale === "th" ? "สิทธิ์ ADMIN" : "ADMIN only"}</span> : <span>{locale === "th" ? "ดูอย่างเดียว" : "Read only"}</span>}
          </div>
          <div className="start-service-price"><span>{locale === "th" ? "ราคาปกติ รวม VAT" : "Regular price, VAT included"}</span><strong>{baht(subtotalAmountSatang, locale)}</strong></div>

          {role === "ADMIN" ? <>
            <label className="start-service-field" htmlFor="start-service-discount">
              <span>{locale === "th" ? "ส่วนลด (ไม่บังคับ)" : "Discount (optional)"}</span>
              <div className="start-service-money-input"><input id="start-service-discount" type="number" min="0" max={Math.max(0, subtotalAmountSatang / 100 - 1)} step="1" inputMode="numeric" value={amountBaht} disabled={submitting} aria-invalid={!validAmount} aria-describedby="start-service-discount-help" onChange={(event) => setAmountBaht(event.target.value)} /><span>{locale === "th" ? "บาท" : "THB"}</span></div>
              <small id="start-service-discount-help">{locale === "th" ? "จำนวนเงินบาทเต็มและต้องน้อยกว่าราคาปกติ" : "Whole THB amount below the regular price."}</small>
            </label>
            {reasonRequired && <label className="start-service-field" htmlFor="start-service-discount-reason">
              <span>{removingDiscount ? (locale === "th" ? "เหตุผลที่ยกเลิกส่วนลด" : "Reason for removing discount") : (locale === "th" ? "เหตุผลหรือชื่อ Promotion" : "Reason or promotion name")}</span>
              <input id="start-service-discount-reason" list={reasonListId} maxLength={200} value={reason} disabled={submitting} aria-invalid={!validReason} placeholder={removingDiscount ? (locale === "th" ? "เช่น แก้ไขส่วนลดที่บันทึกผิด" : "e.g. Correct an incorrect discount") : (locale === "th" ? "เช่น คูปองสมัครครั้งแรก" : "e.g. First-visit coupon")} onChange={(event) => setReason(event.target.value)} />
              <datalist id={reasonListId}>
                <option value={locale === "th" ? "คูปองสมัครครั้งแรก" : "First-visit coupon"} />
                <option value={locale === "th" ? "โปรโมชั่นหน้าร้าน" : "In-store promotion"} />
                <option value={locale === "th" ? "ลูกค้าประจำ" : "Loyal customer"} />
                <option value={locale === "th" ? "แก้ไขส่วนลดที่บันทึกผิด" : "Correct an incorrect discount"} />
              </datalist>
            </label>}
          </> : discountAmountSatang > 0 && <div className="start-service-readonly-discount"><span>{locale === "th" ? "ส่วนลดของร้าน" : "Shop discount"}</span><strong>−{baht(discountAmountSatang, locale)}</strong>{discountReason && <small>{discountReason}</small>}</div>}

          <div className="start-service-net" aria-live="polite"><span>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service"}</span><strong>{validAmount || role === "STAFF" ? baht(role === "STAFF" ? subtotalAmountSatang - discountAmountSatang : netAmountSatang, locale) : "—"}</strong></div>
          <p className="start-service-policy">{locale === "th" ? "ส่วนลดเป็น Promotion ของร้านและไม่ลดค่าหมอ ระบบจะบันทึก Audit Trail" : "Shop promotions do not reduce therapist pay. The change is recorded in the audit trail."}</p>
          {role === "ADMIN" && (!validAmount || !validReason) && <p className="start-service-validation" role="alert">{!validAmount ? (locale === "th" ? "กรอกส่วนลดเป็นจำนวนเงินบาทเต็มและน้อยกว่าราคาปกติ" : "Enter a whole-THB discount below the regular price.") : (locale === "th" ? "กรุณาระบุเหตุผลของการเปลี่ยนส่วนลด" : "Enter a reason for the discount change.")}</p>}
          {error && <p className="start-service-validation" role="alert">{error}</p>}
        </section>
      </div>

      <div className="start-service-actions">
        <button type="button" disabled={submitting} onClick={onClose}>{locale === "th" ? "กลับไปตรวจ" : "Go back"}</button>
        <button type="button" className="confirm-button" disabled={!valid || submitting} onClick={() => { void submit(); }}>{submitting ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : role === "ADMIN" ? (locale === "th" ? "บันทึกและเริ่มให้บริการ" : "Save & start service") : (locale === "th" ? "ยืนยันเริ่มให้บริการ" : "Confirm start service")}</button>
      </div>
    </div>
  </div>;
}
