"use client";

import type { Locale, PreviewBooking } from "@spa/shared-types";
import type { User } from "firebase/auth";
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";

import { adminApi } from "@/lib/admin-api";

type Therapist = { therapistId: string; displayName: string; active: boolean };
type Variant = {
  variantId: string;
  durationMinutes: number;
  priceSatang: number;
  active: boolean;
  pricingMode?: "PER_PARTICIPANT" | "PER_BOOKING";
  requiredPax?: number;
};
type Service = {
  serviceId: string;
  nameTh: string;
  nameEn: string;
  active: boolean;
  variants: Variant[];
};

export type AddBookingServiceInput = {
  participantId: string;
  serviceVariantId: string;
  therapistId: string;
  date: string;
  time: string;
  discountAmountSatang?: number;
  discountReason?: string;
};

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

function bangkokFields(value: string): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (type: "year" | "month" | "day" | "hour" | "minute") => parts.find((item) => item.type === type)?.value ?? "";
  return { date: `${part("year")}-${part("month")}-${part("day")}`, time: `${part("hour")}:${part("minute")}` };
}

export function AddBookingServiceDialog({
  booking,
  role,
  locale,
  user,
  therapists,
  submitting,
  error,
  onClose,
  onConfirm,
}: {
  booking: PreviewBooking;
  role: "ADMIN" | "STAFF";
  locale: Locale;
  user: User;
  therapists: Therapist[];
  submitting: boolean;
  error: string;
  onClose: () => void;
  onConfirm: (input: AddBookingServiceInput) => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const reasonListId = useId();
  const initialSchedule = bangkokFields(booking.nextServiceStartLocal ?? booking.endAt ?? booking.startLocal);
  const [services, setServices] = useState<Service[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [participantId, setParticipantId] = useState(booking.participants?.[0]?.participantId ?? "");
  const [variantId, setVariantId] = useState("");
  const [therapistId, setTherapistId] = useState("");
  const [date, setDate] = useState(initialSchedule.date);
  const [time, setTime] = useState(initialSchedule.time);
  const [discountBaht, setDiscountBaht] = useState(String((booking.discountAmountSatang ?? 0) / 100));
  const [discountReason, setDiscountReason] = useState(booking.discountReason ?? "");

  const options = useMemo(() => services.flatMap((service) => service.variants
    .filter((variant) => variant.active && variant.pricingMode !== "PER_BOOKING" && variant.requiredPax !== 2)
    .map((variant) => ({ ...variant, serviceNameTh: service.nameTh, serviceNameEn: service.nameEn }))), [services]);
  const selectedVariant = options.find((item) => item.variantId === variantId);
  const newSubtotal = (booking.subtotalAmountSatang ?? 0) + (selectedVariant?.priceSatang ?? 0);
  const normalizedDiscount = discountBaht.trim() || "0";
  const discountNumber = Number(normalizedDiscount);
  const discountSatang = /^\d+$/.test(normalizedDiscount) && Number.isSafeInteger(discountNumber)
    ? discountNumber * 100
    : Number.NaN;
  const discountValid = Number.isFinite(discountSatang) && discountSatang >= 0 && discountSatang < newSubtotal;
  const removingDiscount = (booking.discountAmountSatang ?? 0) > 0 && discountSatang === 0;
  const discountChanged = discountSatang !== (booking.discountAmountSatang ?? 0)
    || (discountSatang > 0 && discountReason.trim() !== (booking.discountReason ?? ""));
  const reasonRequired = discountChanged && (discountSatang > 0 || removingDiscount);
  const reasonValid = !reasonRequired || (discountReason.trim().length > 0 && discountReason.trim().length <= 200);
  const valid = Boolean(participantId && variantId && therapistId && date && time && selectedVariant)
    && (role === "STAFF" || (discountValid && reasonValid));

  useEffect(() => {
    let active = true;
    adminApi<{ items: Service[] }>(user, "/services")
      .then((payload) => {
        if (!active) return;
        const next = payload.items.filter((service) => service.active);
        setServices(next);
        const first = next.flatMap((service) => service.variants)
          .find((variant) => variant.active && variant.pricingMode !== "PER_BOOKING" && variant.requiredPax !== 2);
        setVariantId(first?.variantId ?? "");
        setLoadState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setLoadError(caught instanceof Error ? caught.message : "Service catalog unavailable");
        setLoadState("error");
      });
    return () => { active = false; };
  }, [user]);

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.requestAnimationFrame(() => closeRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), select:not([disabled])",
      ));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => { document.removeEventListener("keydown", handleKeyDown); previousFocusRef.current?.focus(); };
  }, [onClose, submitting]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || submitting) return;
    await onConfirm({
      participantId,
      serviceVariantId: variantId,
      therapistId,
      date,
      time,
      ...(role === "ADMIN" ? { discountAmountSatang: discountSatang, discountReason: discountReason.trim() } : {}),
    });
  }

  return <div className="modal-backdrop add-service-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) onClose(); }}>
    <div ref={dialogRef} className="add-service-dialog" role="dialog" aria-modal="true" aria-labelledby="add-service-title" aria-describedby="add-service-description">
      <div className="drawer-header start-service-header"><div><p className="eyebrow">ADD SERVICE • {booking.bookingId}</p><h2 id="add-service-title">{locale === "th" ? "เพิ่มบริการใน Booking เดิม" : "Add service to this booking"}</h2><p id="add-service-description">{locale === "th" ? "เพิ่มได้หลายครั้ง และรวมยอดเพื่อชำระครั้งเดียวหลังจบบริการ" : "Add multiple services and collect one payment after completion."}</p></div><button ref={closeRef} type="button" disabled={submitting} aria-label={locale === "th" ? "ปิดหน้าต่าง" : "Close dialog"} onClick={onClose}>×</button></div>
      <form onSubmit={submit}>
        <div className="add-service-body">
          {loadState === "loading" && <div className="module-state" role="status">{locale === "th" ? "กำลังโหลดบริการ…" : "Loading services…"}</div>}
          {(loadError || error) && <p className="start-service-validation" role="alert">{loadError || error}</p>}
          <div className="add-service-grid">
            <label><span>{locale === "th" ? "ผู้รับบริการ" : "Guest"}</span><select value={participantId} disabled={submitting} onChange={(event) => setParticipantId(event.target.value)}>{booking.participants?.map((item) => <option value={item.participantId} key={item.participantId}>{item.nickname}</option>)}</select></label>
            <label><span>{locale === "th" ? "บริการและระยะเวลา" : "Service & duration"}</span><select value={variantId} disabled={submitting || loadState !== "ready"} onChange={(event) => setVariantId(event.target.value)}>{services.filter((service) => service.active).map((service) => <optgroup label={locale === "th" ? service.nameTh : service.nameEn} key={service.serviceId}>{service.variants.filter((variant) => variant.active && variant.pricingMode !== "PER_BOOKING" && variant.requiredPax !== 2).map((variant) => <option value={variant.variantId} key={variant.variantId}>{variant.durationMinutes} {locale === "th" ? "นาที" : "min"} • {baht(variant.priceSatang, locale)}</option>)}</optgroup>)}</select></label>
            <label><span>{locale === "th" ? "หมอนวดสำหรับบริการนี้" : "Therapist for this service"}</span><select value={therapistId} disabled={submitting} onChange={(event) => setTherapistId(event.target.value)}><option value="">— {locale === "th" ? "เลือกหมอ" : "Select therapist"} —</option>{therapists.filter((item) => item.active).map((item) => <option value={item.therapistId} key={item.therapistId}>{item.displayName}</option>)}</select></label>
            <div className="add-service-schedule"><label><span>{locale === "th" ? "วันที่เริ่ม" : "Start date"}</span><input type="date" value={date} disabled={submitting} onChange={(event) => setDate(event.target.value)} /></label><label><span>{locale === "th" ? "เวลาเริ่ม" : "Start time"}</span><input type="time" step="900" value={time} disabled={submitting} onChange={(event) => setTime(event.target.value)} /></label></div>
          </div>
          <section className="add-service-financial" aria-labelledby="add-service-financial-title"><div className="start-service-section-heading"><div><p className="eyebrow">UPDATED TOTAL</p><h3 id="add-service-financial-title">{locale === "th" ? "ยอดรวมและส่วนลด" : "Updated total & discount"}</h3></div><span>{role === "ADMIN" ? "ADMIN" : (locale === "th" ? "ดูอย่างเดียว" : "Read only")}</span></div>
            <dl><div><dt>{locale === "th" ? "ยอดเดิม" : "Current subtotal"}</dt><dd>{baht(booking.subtotalAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "บริการที่เพิ่ม" : "Added service"}</dt><dd>{selectedVariant ? baht(selectedVariant.priceSatang, locale) : "—"}</dd></div><div><dt>{locale === "th" ? "ราคาปกติใหม่" : "New subtotal"}</dt><dd>{selectedVariant ? baht(newSubtotal, locale) : "—"}</dd></div></dl>
            {role === "ADMIN" ? <div className="add-service-discount"><label><span>{locale === "th" ? "ส่วนลดรวมของ Booking (บาท)" : "Booking discount (THB)"}</span><input type="number" min="0" step="1" inputMode="numeric" value={discountBaht} disabled={submitting} aria-invalid={!discountValid} onChange={(event) => setDiscountBaht(event.target.value)} /></label>{(discountSatang > 0 || removingDiscount) && <label><span>{removingDiscount ? (locale === "th" ? "เหตุผลที่ยกเลิกส่วนลด" : "Reason for removing discount") : (locale === "th" ? "เหตุผลหรือชื่อ Promotion" : "Reason or promotion name")}</span><input list={reasonListId} maxLength={200} value={discountReason} disabled={submitting} aria-invalid={!reasonValid} onChange={(event) => setDiscountReason(event.target.value)} /><datalist id={reasonListId}><option value={locale === "th" ? "คูปองสมัครครั้งแรก" : "First-visit coupon"} /><option value={locale === "th" ? "โปรโมชั่นหน้าร้าน" : "In-store promotion"} /><option value={locale === "th" ? "ลูกค้าประจำ" : "Loyal customer"} /><option value={locale === "th" ? "แก้ไขส่วนลดที่บันทึกผิด" : "Correct an incorrect discount"} /></datalist></label>}</div> : <p className="start-service-readonly-discount">{locale === "th" ? "ส่วนลดเดิมของร้าน" : "Existing shop discount"} <strong>−{baht(booking.discountAmountSatang ?? 0, locale)}</strong></p>}
            <div className="start-service-net"><span>{locale === "th" ? "ค่าบริการสุทธิใหม่" : "New net service total"}</span><strong>{selectedVariant && (role === "STAFF" || discountValid) ? baht(newSubtotal - (role === "ADMIN" ? discountSatang : booking.discountAmountSatang ?? 0), locale) : "—"}</strong></div>
            <p className="start-service-policy">{locale === "th" ? "ส่วนลดเป็นของทั้ง Booking และไม่ลดค่าหมอ การเปลี่ยนแปลงถูกบันทึกใน Audit Trail" : "The discount applies to the booking and does not reduce therapist pay. Changes are audited."}</p>
          </section>
        </div>
        <div className="start-service-actions"><button type="button" disabled={submitting} onClick={onClose}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button type="submit" className="confirm-button" disabled={!valid || submitting || loadState !== "ready"}>{submitting ? (locale === "th" ? "กำลังเพิ่ม…" : "Adding…") : (locale === "th" ? "เพิ่มบริการและอัปเดตยอด" : "Add service & update total")}</button></div>
      </form>
    </div>
  </div>;
}
