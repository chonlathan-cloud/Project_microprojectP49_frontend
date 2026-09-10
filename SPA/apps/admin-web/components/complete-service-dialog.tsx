"use client";

import type { Locale, PreviewBooking } from "@spa/shared-types";
import { useEffect, useRef } from "react";

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

export function CompleteServiceDialog({ booking, locale, submitting, onClose, onConfirm }: {
  booking: PreviewBooking;
  locale: Locale;
  submitting: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const services = booking.serviceItems ?? [];

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.requestAnimationFrame(() => closeRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled])"));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => { document.removeEventListener("keydown", handleKeyDown); previousFocusRef.current?.focus(); };
  }, [onClose, submitting]);

  return <div className="modal-backdrop complete-service-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) onClose(); }}>
    <div ref={dialogRef} className="complete-service-dialog" role="dialog" aria-modal="true" aria-labelledby="complete-service-title" aria-describedby="complete-service-description">
      <div className="drawer-header start-service-header"><div><p className="eyebrow">FINAL REVIEW • {booking.bookingId}</p><h2 id="complete-service-title">{locale === "th" ? "ตรวจสอบบริการทั้งหมด" : "Review all services"}</h2><p id="complete-service-description">{locale === "th" ? "หลังยืนยันจะจบบริการและเปิดให้รับชำระเงินครั้งเดียว" : "Confirmation completes the service and enables one final payment."}</p></div><button ref={closeRef} type="button" disabled={submitting} aria-label={locale === "th" ? "ปิดหน้าต่าง" : "Close dialog"} onClick={onClose}>×</button></div>
      <div className="complete-service-body">
        <ol className="complete-service-list">{services.map((item, index) => <li key={item.lineItemId}><span>{index + 1}</span><div><strong>{locale === "th" ? item.serviceNameTh : item.serviceNameEn}</strong><small>{item.participantNames?.join(" + ") || item.participantName} • {item.durationMinutes} {locale === "th" ? "นาที" : "min"}{item.therapistName ? ` • ${item.therapistName}` : ""}</small></div><strong>{baht(item.lineTotalSatang, locale)}</strong></li>)}</ol>
        {!services.length && <div className="module-state">{locale === "th" ? "กำลังโหลดรายละเอียดบริการ…" : "Loading service details…"}</div>}
        <dl className="complete-service-totals"><div><dt>{locale === "th" ? "ราคาปกติ" : "Regular price"}</dt><dd>{baht(booking.subtotalAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ส่วนลดร้าน" : "Shop discount"}</dt><dd>−{baht(booking.discountAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ยอดรอชำระ" : "Amount due"}</dt><dd>{baht(booking.estimatedAmountSatang ?? 0, locale)}</dd></div></dl>
        <p className="complete-service-note">{locale === "th" ? "หากลูกค้าต้องการบริการต่อ ให้กด “เพิ่มบริการ” ก่อนจบบริการ" : "If the guest wants another service, add it before completing this booking."}</p>
      </div>
      <div className="start-service-actions"><button type="button" disabled={submitting} onClick={onClose}>{locale === "th" ? "กลับไปตรวจ" : "Review again"}</button><button type="button" className="confirm-button" disabled={submitting || !services.length} onClick={() => { void onConfirm(); }}>{submitting ? (locale === "th" ? "กำลังจบบริการ…" : "Completing…") : (locale === "th" ? "ยืนยันจบบริการ" : "Confirm completion")}</button></div>
    </div>
  </div>;
}
