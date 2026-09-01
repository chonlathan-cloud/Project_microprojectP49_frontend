"use client";

import { INITIAL_SERVICE_CATALOG, type Locale, type Service, type ServiceVariant } from "@spa/shared-types";
import type { User } from "firebase/auth";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { adminApi } from "@/lib/admin-api";

type ParticipantDraft = {
  nickname: string;
  variantId: string;
  hasHealthInformation: boolean | null;
  healthDetails: string;
  healthConsent: boolean;
};

type AvailabilitySlot = {
  localDate: string;
  localStartTime: string;
  availableUnits: number;
};

type AvailabilityState = "idle" | "loading" | "ready" | "error";

const blankParticipant = (variantId = ""): ParticipantDraft => ({
  nickname: "",
  variantId,
  hasHealthInformation: null,
  healthDetails: "",
  healthConsent: false,
});

function bangkokDate(date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Bangkok",
  }).format(date);
}

function currentBangkokBucket(date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Bangkok",
  }).formatToParts(date);
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? 0);
  return `${String(hour).padStart(2, "0")}:${String(Math.floor(minute / 15) * 15).padStart(2, "0")}`;
}

function formatBaht(amountSatang: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(amountSatang / 100);
}

function findVariant(services: Service[], variantId: string): { service: Service; variant: ServiceVariant } | null {
  for (const service of services) {
    const variant = service.variants.find((item) => item.id === variantId);
    if (variant) return { service, variant };
  }
  return null;
}

export function WalkInBookingDrawer({
  user,
  locale,
  onClose,
  onCreated,
}: {
  user: User;
  locale: Locale;
  onClose: () => void;
  onCreated: (bookingId: string) => void;
}) {
  const [services, setServices] = useState<Service[]>([]);
  const [catalogState, setCatalogState] = useState<"loading" | "live" | "preview">("loading");
  const [participants, setParticipants] = useState<ParticipantDraft[]>([blankParticipant()]);
  const [contactMode, setContactMode] = useState<"PHONE" | "NONE">("PHONE");
  const [phone, setPhone] = useState("");
  const [date] = useState(() => bangkokDate());
  const [time, setTime] = useState("");
  const [slots, setSlots] = useState<AvailabilitySlot[]>([]);
  const [availabilityState, setAvailabilityState] = useState<AvailabilityState>("idle");
  const [availabilityRetry, setAvailabilityRetry] = useState(0);
  const [consentCaptureMethod, setConsentCaptureMethod] = useState<"VERBAL" | "PAPER">("VERBAL");
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const idempotencyKey = useRef(crypto.randomUUID());

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(drawerRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]'
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
      previousFocus?.focus();
    };
  }, [onClose]);

  useEffect(() => {
    let active = true;
    fetch("/api/spa/api/v1/public/services", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Catalog unavailable");
        return response.json() as Promise<{ items?: Service[] }>;
      })
      .then((payload) => {
        if (!active) return;
        setServices((payload.items ?? []).filter((service) => service.active));
        setCatalogState("live");
      })
      .catch(() => {
        if (!active) return;
        setServices(INITIAL_SERVICE_CATALOG.filter((service) => service.active));
        setCatalogState("preview");
      });
    return () => { active = false; };
  }, []);

  const selections = useMemo(
    () => participants.map((participant) => findVariant(services, participant.variantId)),
    [participants, services]
  );
  const variantIds = participants.map((participant) => participant.variantId).join("|");
  const availabilityParticipants = useMemo(
    () => variantIds.split("|").filter(Boolean).map((serviceVariantId) => ({ serviceVariantId })),
    [variantIds]
  );
  const allVariantsSelected = selections.every(Boolean);

  useEffect(() => {
    if (!allVariantsSelected || !participants.length) return;
    const controller = new AbortController();
    let active = true;
    queueMicrotask(() => { if (active) setAvailabilityState("loading"); });
    fetch("/api/spa/api/v1/public/availability/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        branchId: "branch_001",
        dateFrom: date,
        dateTo: date,
        participants: availabilityParticipants,
      }),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Availability unavailable");
        return response.json() as Promise<{ slots?: AvailabilitySlot[] }>;
      })
      .then((payload) => {
        const currentBucket = currentBangkokBucket();
        const available = (payload.slots ?? []).filter(
          (slot) => slot.localDate === date && slot.localStartTime >= currentBucket
        );
        if (!active) return;
        setSlots(available);
        setTime((current) => available.some((slot) => slot.localStartTime === current) ? current : "");
        setAvailabilityState("ready");
      })
      .catch((error) => {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setSlots([]);
        setAvailabilityState("error");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [allVariantsSelected, availabilityParticipants, availabilityRetry, date, participants.length]);

  const total = selections.reduce((amount, selection, index) => {
    if (!selection) return amount;
    if (selection.variant.pricingMode === "PER_BOOKING" && index > 0) return amount;
    return amount + selection.variant.priceSatang;
  }, 0);
  const duration = Math.max(0, ...selections.map((selection) => selection?.variant.durationMinutes ?? 0));

  const validationMessages = useMemo(() => {
    const messages: string[] = [];
    if (!allVariantsSelected) messages.push(locale === "th" ? "เลือกบริการให้ผู้รับบริการทุกท่าน" : "Choose a service for every guest");
    if (!time) messages.push(locale === "th" ? "เลือกเวลา Walk-in ที่ยังว่าง" : "Choose an available Walk-in time");
    if (contactMode === "PHONE" && !phone.trim()) messages.push(locale === "th" ? "กรอกเบอร์ติดต่อ หรือเลือกไม่มีเบอร์ติดต่อ" : "Enter a phone or choose no contact phone");
    participants.forEach((participant, index) => {
      const guest = locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`;
      if (!participant.nickname.trim()) messages.push(`${guest}: ${locale === "th" ? "กรอกชื่อเล่น" : "enter a nickname"}`);
      if (participant.hasHealthInformation === null) messages.push(`${guest}: ${locale === "th" ? "ตอบคำถามข้อมูลสุขภาพ" : "answer the health declaration"}`);
      if (participant.hasHealthInformation && !participant.healthDetails.trim()) messages.push(`${guest}: ${locale === "th" ? "ระบุรายละเอียดสุขภาพ" : "provide health details"}`);
      if (!participant.healthConsent) messages.push(`${guest}: ${locale === "th" ? "บันทึกความยินยอมของลูกค้า" : "record the customer's consent"}`);
    });
    if (!privacyAcknowledged) messages.push(locale === "th" ? "ยืนยันว่าลูกค้ารับทราบ Privacy Notice และเงื่อนไขแล้ว" : "Confirm the customer acknowledged the Privacy Notice and terms");
    return messages;
  }, [allVariantsSelected, contactMode, locale, participants, phone, privacyAcknowledged, time]);

  function updateParticipant(index: number, update: Partial<ParticipantDraft>) {
    setParticipants((current) => current.map((participant, itemIndex) => itemIndex === index ? { ...participant, ...update } : participant));
    setShowValidation(false);
  }

  function setPax(pax: 1 | 2) {
    const firstSelection = findVariant(services, participants[0].variantId);
    if (firstSelection?.variant.requiredPax === 2) return;
    setParticipants((current) => pax === 1 ? [current[0]] : [current[0], current[1] ?? blankParticipant()]);
    setSlots([]);
    setAvailabilityState("idle");
    setTime("");
    setShowValidation(false);
  }

  function selectVariant(index: number, variantId: string) {
    const selection = findVariant(services, variantId);
    if (index === 0 && selection?.variant.requiredPax === 2) {
      setParticipants((current) => [
        { ...(current[0] ?? blankParticipant()), variantId },
        { ...(current[1] ?? blankParticipant()), variantId },
      ]);
    } else {
      updateParticipant(index, { variantId });
    }
    setSlots([]);
    setAvailabilityState("idle");
    setTime("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (validationMessages.length || submitting) {
      setShowValidation(true);
      requestAnimationFrame(() => errorRef.current?.focus());
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    try {
      const payload = await adminApi<{ bookingId: string }>(user, "/bookings", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey.current },
        body: JSON.stringify({
          bookingMode: "WALK_IN",
          branchId: "branch_001",
          date,
          time,
          phone: contactMode === "PHONE" ? phone.trim() : null,
          consentCaptureMethod,
          bookingPrivacyAcknowledged: privacyAcknowledged,
          participants: participants.map((participant) => ({
            nickname: participant.nickname.trim(),
            serviceVariantId: participant.variantId,
            hasHealthInformation: Boolean(participant.hasHealthInformation),
            healthDetails: participant.healthDetails.trim() || null,
            healthConsent: participant.healthConsent,
          })),
        }),
      });
      onCreated(payload.bookingId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Walk-in booking failed";
      setSubmitError(message);
      if (/capacity|available|slot/i.test(message)) {
        setTime("");
        setAvailabilityRetry((value) => value + 1);
        idempotencyKey.current = crypto.randomUUID();
      }
    } finally {
      setSubmitting(false);
    }
  }

  const optionLabel = (service: Service, variant: ServiceVariant) => `${locale === "th" ? service.nameTh : service.nameEn} · ${variant.durationMinutes} ${locale === "th" ? "นาที" : "min"} · ${formatBaht(variant.priceSatang, locale)}`;

  return <div className="drawer-scrim walk-in-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside ref={drawerRef} className="walk-in-drawer" role="dialog" aria-modal="true" aria-labelledby="walk-in-title">
      <div className="walk-in-header"><div><p className="eyebrow">FRONT DESK • WALK-IN</p><h2 id="walk-in-title">{locale === "th" ? "จองลูกค้า Walk-in" : "Create Walk-in booking"}</h2><p>{locale === "th" ? "สร้างและยืนยันรายการสำหรับลูกค้าที่อยู่หน้าร้าน" : "Create and confirm a booking for a guest at the front desk."}</p></div><button ref={closeButtonRef} type="button" onClick={onClose} aria-label={locale === "th" ? "ปิดฟอร์ม Walk-in" : "Close Walk-in form"}>×</button></div>
      <form className="walk-in-form" onSubmit={submit} noValidate>
        <div className="walk-in-scroll">
          {showValidation && validationMessages.length > 0 && <div ref={errorRef} tabIndex={-1} className="walk-in-errors" role="alert"><strong>{locale === "th" ? "กรุณาตรวจสอบข้อมูล" : "Check the booking details"}</strong><ul>{validationMessages.map((message) => <li key={message}>{message}</li>)}</ul></div>}
          {catalogState === "preview" && <div className="walk-in-notice warning" role="status">{locale === "th" ? "กำลังใช้รายการบริการสำรอง ระบบจะตรวจสอบข้อมูลจริงอีกครั้งเมื่อบันทึก" : "Using the fallback catalog. Live data will be checked again on save."}</div>}

          <section className="walk-in-section" aria-labelledby="walk-in-service-heading"><div className="walk-in-section-title"><span>1</span><div><h3 id="walk-in-service-heading">{locale === "th" ? "บริการและเวลา" : "Service and time"}</h3><p>{locale === "th" ? "Walk-in ใช้เฉพาะ Slot วันนี้และตรวจ Capacity แบบ Real-time" : "Walk-ins use today's live capacity only."}</p></div></div>
            <div className="walk-in-pax" role="group" aria-label={locale === "th" ? "จำนวนผู้รับบริการ" : "Number of guests"}>{([1, 2] as const).map((pax) => <button type="button" key={pax} aria-pressed={participants.length === pax} disabled={findVariant(services, participants[0].variantId)?.variant.requiredPax === 2 && pax === 1} onClick={() => setPax(pax)}>{pax} {locale === "th" ? "ท่าน" : pax === 1 ? "guest" : "guests"}</button>)}</div>
            {participants.map((participant, index) => <label className="walk-in-field" key={`service-${index}`}><span>{locale === "th" ? `บริการผู้รับบริการ ${index + 1}` : `Service for guest ${index + 1}`}</span><select value={participant.variantId} disabled={catalogState === "loading" || (index === 1 && findVariant(services, participants[0].variantId)?.variant.requiredPax === 2)} onChange={(event) => selectVariant(index, event.target.value)} aria-invalid={showValidation && !participant.variantId}><option value="">— {catalogState === "loading" ? (locale === "th" ? "กำลังโหลดบริการ" : "Loading services") : (locale === "th" ? "เลือกบริการ" : "Choose a service")} —</option>{services.filter((service) => index === 0 || service.variants.every((variant) => variant.requiredPax === 1)).flatMap((service) => service.variants.map((variant) => <option key={variant.id} value={variant.id}>{optionLabel(service, variant)}</option>))}</select></label>)}
            <div className="walk-in-date"><span>{locale === "th" ? "วันที่" : "Date"}</span><strong>{new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { dateStyle: "full", timeZone: "Asia/Bangkok" }).format(new Date())}</strong></div>
            <div className="walk-in-availability" role="status" aria-live="polite">{availabilityState === "idle" && (locale === "th" ? "เลือกบริการเพื่อดูเวลาว่าง" : "Choose services to see available times")}{availabilityState === "loading" && (locale === "th" ? "กำลังตรวจ Capacity…" : "Checking capacity…")}{availabilityState === "ready" && `${locale === "th" ? "พบ" : "Found"} ${slots.length} ${locale === "th" ? "ช่วงเวลาว่าง" : "available times"}`}{availabilityState === "error" && <><span>{locale === "th" ? "โหลดเวลาว่างไม่สำเร็จ" : "Availability could not be loaded"}</span><button type="button" onClick={() => setAvailabilityRetry((value) => value + 1)}>{locale === "th" ? "ลองใหม่" : "Retry"}</button></>}</div>
            {slots.length > 0 && <div className="walk-in-time-grid" role="group" aria-label={locale === "th" ? "เวลาเริ่ม" : "Start time"}>{slots.map((slot) => <button type="button" key={slot.localStartTime} aria-pressed={time === slot.localStartTime} onClick={() => { setTime(slot.localStartTime); setShowValidation(false); }}>{slot.localStartTime}</button>)}</div>}
          </section>

          <section className="walk-in-section" aria-labelledby="walk-in-contact-heading"><div className="walk-in-section-title"><span>2</span><div><h3 id="walk-in-contact-heading">{locale === "th" ? "ผู้รับบริการและการติดต่อ" : "Guests and contact"}</h3><p>{locale === "th" ? "ไม่ใช้เบอร์ร้านหรือเบอร์สมมติแทนลูกค้า" : "Never substitute the spa's number or a fabricated phone."}</p></div></div>
            <fieldset className="walk-in-choice"><legend>{locale === "th" ? "ช่องทางติดต่อ" : "Contact availability"}</legend><label><input type="radio" name="contact-mode" checked={contactMode === "PHONE"} onChange={() => setContactMode("PHONE")} /> {locale === "th" ? "มีเบอร์ติดต่อ" : "Contact phone available"}</label><label><input type="radio" name="contact-mode" checked={contactMode === "NONE"} onChange={() => { setContactMode("NONE"); setPhone(""); }} /> {locale === "th" ? "ไม่มีเบอร์ติดต่อ" : "No contact phone"}</label></fieldset>
            {contactMode === "PHONE" ? <label className="walk-in-field"><span>{locale === "th" ? "เบอร์โทรศัพท์" : "Phone number"}</span><input type="tel" inputMode="tel" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="081 234 5678" aria-invalid={showValidation && !phone.trim()} /></label> : <div className="walk-in-notice warning">{locale === "th" ? "หลังลูกค้าออกจากร้าน ระบบจะไม่สามารถส่งการแจ้งเตือนหรือติดต่อกลับได้" : "The spa cannot send updates or contact this guest after they leave."}</div>}
            {participants.map((participant, index) => <label className="walk-in-field" key={`nickname-${index}`}><span>{locale === "th" ? `ชื่อเล่นผู้รับบริการ ${index + 1}` : `Guest ${index + 1} nickname`}</span><input value={participant.nickname} maxLength={80} onChange={(event) => updateParticipant(index, { nickname: event.target.value })} aria-invalid={showValidation && !participant.nickname.trim()} /></label>)}
          </section>

          <section className="walk-in-section" aria-labelledby="walk-in-health-heading"><div className="walk-in-section-title"><span>3</span><div><h3 id="walk-in-health-heading">{locale === "th" ? "ข้อมูลสุขภาพและความยินยอม" : "Health and consent"}</h3><p>{locale === "th" ? "พนักงานบันทึกคำตอบของลูกค้า ไม่ได้ให้ความยินยอมแทนลูกค้า" : "Staff records the guest's answer and does not consent on their behalf."}</p></div></div>
            <fieldset className="walk-in-choice consent-method"><legend>{locale === "th" ? "วิธีรับหลักฐาน" : "Evidence method"}</legend><label><input type="radio" name="consent-method" checked={consentCaptureMethod === "VERBAL"} onChange={() => setConsentCaptureMethod("VERBAL")} /> {locale === "th" ? "ลูกค้ายืนยันด้วยวาจา" : "Verbal acknowledgement"}</label><label><input type="radio" name="consent-method" checked={consentCaptureMethod === "PAPER"} onChange={() => setConsentCaptureMethod("PAPER")} /> {locale === "th" ? "เอกสารกระดาษ" : "Paper form"}</label></fieldset>
            {participants.map((participant, index) => <fieldset className="walk-in-health" key={`health-${index}`}><legend>{locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`}</legend><div className="walk-in-choice compact"><label><input type="radio" name={`health-${index}`} checked={participant.hasHealthInformation === false} onChange={() => updateParticipant(index, { hasHealthInformation: false, healthDetails: "" })} /> {locale === "th" ? "ไม่มีข้อมูลสุขภาพที่ต้องแจ้ง" : "No health information to declare"}</label><label><input type="radio" name={`health-${index}`} checked={participant.hasHealthInformation === true} onChange={() => updateParticipant(index, { hasHealthInformation: true })} /> {locale === "th" ? "มีข้อมูลสุขภาพที่ต้องแจ้ง" : "Has health information to declare"}</label></div>{participant.hasHealthInformation && <label className="walk-in-field"><span>{locale === "th" ? "รายละเอียดอาการ โรคประจำตัว หรือการแพ้" : "Condition, symptom, or allergy details"}</span><textarea value={participant.healthDetails} maxLength={1000} onChange={(event) => updateParticipant(index, { healthDetails: event.target.value })} aria-invalid={showValidation && !participant.healthDetails.trim()} /></label>}<label className="walk-in-consent"><input type="checkbox" checked={participant.healthConsent} onChange={(event) => updateParticipant(index, { healthConsent: event.target.checked })} /><span>{locale === "th" ? "ลูกค้ายินยอมให้บันทึกและใช้ข้อมูลสุขภาพเพื่อความปลอดภัยในการให้บริการ รวมถึงเปิดเผยต่อ Registered Admin LINE Group ตาม Privacy Notice" : "The guest consents to health-data use for treatment safety and disclosure to the registered Admin LINE Group as described in the Privacy Notice."}</span></label></fieldset>)}
            <label className="walk-in-consent privacy"><input type="checkbox" checked={privacyAcknowledged} onChange={(event) => setPrivacyAcknowledged(event.target.checked)} /><span>{locale === "th" ? "ฉันได้แจ้ง Privacy Notice และเงื่อนไขการจองให้ลูกค้ารับทราบ และบันทึกคำตอบตามที่ลูกค้าแจ้ง" : "I presented the Privacy Notice and booking terms and recorded the guest's responses accurately."}</span></label>
          </section>

          <section className="walk-in-review" aria-labelledby="walk-in-review-heading"><div><p className="eyebrow">FINAL REVIEW</p><h3 id="walk-in-review-heading">{locale === "th" ? "ตรวจสอบก่อนสร้างและยืนยัน" : "Review before creating and confirming"}</h3></div><dl><div><dt>{locale === "th" ? "วันและเวลา" : "Date and time"}</dt><dd>{date} · {time || "—"}</dd></div><div><dt>{locale === "th" ? "ผู้รับบริการ" : "Guests"}</dt><dd>{participants.length} · {duration} {locale === "th" ? "นาที" : "min"}</dd></div><div><dt>{locale === "th" ? "ช่องทางติดต่อ" : "Contact"}</dt><dd>{contactMode === "PHONE" ? (phone || "—") : (locale === "th" ? "ไม่มีเบอร์ติดต่อ" : "No contact phone")}</dd></div><div><dt>{locale === "th" ? "สถานะหลังบันทึก" : "Status after save"}</dt><dd><span className="status status-confirmed">{locale === "th" ? "ยืนยันแล้ว" : "Confirmed"}</span></dd></div></dl><div className="walk-in-total"><span>{locale === "th" ? "ราคาประเมินรวม VAT" : "Estimated total, VAT included"}</span><strong>{formatBaht(total, locale)}</strong></div></section>
          {submitError && <div className="walk-in-errors submit" role="alert"><strong>{locale === "th" ? "สร้าง Booking ไม่สำเร็จ" : "Walk-in booking failed"}</strong><p>{submitError}</p></div>}
        </div>
        <div className="walk-in-actions"><button type="button" onClick={onClose}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button className="confirm-button" type="submit" disabled={submitting}>{submitting ? (locale === "th" ? "กำลังตรวจ Capacity และบันทึก…" : "Checking capacity and saving…") : (locale === "th" ? "สร้างและยืนยัน Booking" : "Create and confirm booking")}</button></div>
      </form>
    </aside>
  </div>;
}
