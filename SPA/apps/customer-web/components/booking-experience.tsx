"use client";

import { INITIAL_SERVICE_CATALOG } from "@spa/shared-types/catalog";
import type { Locale, Service, ServiceVariant } from "@spa/shared-types";
import { useEffect, useMemo, useRef, useState } from "react";
import { loadLiff } from "@/lib/line-liff";
import { ServiceArtwork } from "@/components/service-artwork";

type Step = "SERVICE" | "PARTICIPANTS" | "SCHEDULE" | "DETAILS" | "REVIEW";
type ParticipantDraft = { nickname: string; services: string[]; hasHealthInformation: boolean | null; healthDetails: string; healthConsent: boolean };
type AvailabilitySlot = { localDate: string; localStartTime: string; availableUnits: number };
type BookingWindow = { minDays: number; maxDays: number };

const steps: Step[] = ["SERVICE", "PARTICIPANTS", "SCHEDULE", "DETAILS", "REVIEW"];
const copy = {
  th: { back: "ย้อนกลับ", change: "เปลี่ยน", continue: "ดำเนินการต่อ", contact: "เบอร์โทรศัพท์ผู้ติดต่อหลัก", details: "ข้อมูลผู้รับบริการ", hasHealth: "มีข้อมูลสุขภาพที่ต้องแจ้ง", noHealth: "ไม่มีข้อมูลสุขภาพที่ต้องแจ้ง", pax: "จำนวนผู้รับบริการ", person: "ท่าน", review: "ตรวจสอบคำขอ", schedule: "เลือกวันและเวลา", submit: "ส่งคำขอจอง", total: "ราคาประเมินรวม" },
  en: { back: "Back", change: "Change", continue: "Continue", contact: "Primary contact phone", details: "Guest details", hasHealth: "I have health information to share", noHealth: "No health information to share", pax: "Number of guests", person: "guest", review: "Review request", schedule: "Choose date and time", submit: "Submit booking request", total: "Estimated total" }
};
const stepLabels: Record<Step, { th: string; en: string }> = {
  SERVICE: { th: "เลือกบริการ", en: "Choose a service" },
  PARTICIPANTS: { th: "ผู้รับบริการ", en: "Guests" },
  SCHEDULE: { th: "วันและเวลา", en: "Date and time" },
  DETAILS: { th: "ข้อมูลและสุขภาพ", en: "Details and health" },
  REVIEW: { th: "ตรวจสอบคำขอ", en: "Review request" }
};
const categoryNames = {
  SIGNATURE: { th: "แพ็กเกจพิเศษ", en: "Signature" },
  MASSAGE: { th: "นวดและสปา", en: "Massage & spa" },
  STANDALONE: { th: "บริการจองเดี่ยว", en: "Standalone" }
} as const;

const MAX_SERVICES_PER_PARTICIPANT = 3;
const defaultParticipant = (variantId = ""): ParticipantDraft => ({ nickname: "", services: variantId ? [variantId] : [], hasHealthInformation: null, healthDetails: "", healthConsent: false });

function formatBaht(amountSatang: number, locale: Locale) {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-TH", { style: "currency", currency: "THB", currencyDisplay: "narrowSymbol", maximumFractionDigits: 0 }).format(amountSatang / 100);
}

function formatDate(localDate: string, locale: Locale, options?: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Bangkok", ...options }).format(new Date(`${localDate}T12:00:00+07:00`));
}

function variantById(id: string, catalog: Service[]) {
  for (const service of catalog) {
    const variant = service.variants.find((item) => item.id === id);
    if (variant) return { service, variant };
  }
  return undefined;
}

function endTime(startTime: string, durationMinutes: number) {
  if (!startTime) return "";
  const [hours, minutes] = startTime.split(":").map(Number);
  const total = hours * 60 + minutes + durationMinutes;
  return `${String(Math.floor(total / 60) % 24).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function bangkokToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" }).format(new Date());
}

function addLocalDays(localDate: string, days: number) {
  const value = new Date(`${localDate}T12:00:00+07:00`);
  value.setUTCDate(value.getUTCDate() + days);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" }).format(value);
}

function monthStart(localDate: string) {
  return `${localDate.slice(0, 7)}-01`;
}

function addMonths(localDate: string, months: number) {
  const value = new Date(`${monthStart(localDate)}T12:00:00+07:00`);
  value.setUTCMonth(value.getUTCMonth() + months);
  return monthStart(new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" }).format(value));
}

function calendarDays(month: string) {
  const first = new Date(`${month}T12:00:00+07:00`);
  const year = first.getUTCFullYear();
  const monthIndex = first.getUTCMonth();
  const leading = first.getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  return [...Array<null>(leading).fill(null), ...Array.from({ length: daysInMonth }, (_, index) => `${month.slice(0, 8)}${String(index + 1).padStart(2, "0")}`)];
}

function formatMonth(localDate: string, locale: Locale) {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { month: "long", year: "numeric", timeZone: "Asia/Bangkok" }).format(new Date(`${localDate}T12:00:00+07:00`));
}

function Brand({ compact = false }: { compact?: boolean }) {
  return <a className="brand" href="#main-content" aria-label="SPA 49 home"><span><strong>SPA 49</strong>{!compact && <small>RELAX · RENEW · REVIVE</small>}</span></a>;
}

export function BookingExperience() {
  const [locale, setLocale] = useState<Locale>("th");
  const [step, setStep] = useState<Step>("SERVICE");
  const [participants, setParticipants] = useState<ParticipantDraft[]>([defaultParticipant()]);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [phone, setPhone] = useState("");
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [secondPersonAuthorized, setSecondPersonAuthorized] = useState(false);
  const [submittedBookingId, setSubmittedBookingId] = useState<string | null>(null);
  const [submittedStatusToken, setSubmittedStatusToken] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [availableSlots, setAvailableSlots] = useState<AvailabilitySlot[]>([]);
  const [availabilityState, setAvailabilityState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [availabilityRetry, setAvailabilityRetry] = useState(0);
  const [bookingWindow, setBookingWindow] = useState<BookingWindow>({ minDays: 1, maxDays: 30 });
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarDraftDate, setCalendarDraftDate] = useState("");
  const [calendarMonth, setCalendarMonth] = useState(monthStart(addLocalDays(bangkokToday(), 1)));
  const [scheduleConflict, setScheduleConflict] = useState(false);
  const [category, setCategory] = useState<Service["category"]>("SIGNATURE");
  const [services, setServices] = useState<Service[]>(INITIAL_SERVICE_CATALOG);
  const [catalogLive, setCatalogLive] = useState(false);
  const [lineIdToken, setLineIdToken] = useState<string | null>(null);
  const [lineState, setLineState] = useState<"loading" | "linked" | "guest" | "error">("loading");
  const [showValidation, setShowValidation] = useState(false);
  const [draftRestored, setDraftRestored] = useState(false);
  const errorSummaryRef = useRef<HTMLDivElement>(null);
  const calendarDialogRef = useRef<HTMLDialogElement>(null);
  const conflictDialogRef = useRef<HTMLDialogElement>(null);
  const idempotencyKey = useRef(crypto.randomUUID());
  const t = copy[locale];

  useEffect(() => { document.documentElement.lang = locale; }, [locale]);

  useEffect(() => {
    fetch("/api/spa/api/v1/public/branch", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error("Branch configuration unavailable");
      const payload = await response.json() as { bookingWindow?: Partial<BookingWindow> };
      const configuredMinDays = Number(payload.bookingWindow?.minDays ?? 1);
      const configuredMaxDays = Number(payload.bookingWindow?.maxDays ?? 30);
      const minDays = Number.isFinite(configuredMinDays) ? Math.max(0, configuredMinDays) : 1;
      const maxDays = Number.isFinite(configuredMaxDays) ? Math.max(minDays, configuredMaxDays) : 30;
      setBookingWindow({ minDays, maxDays });
    }).catch(() => setBookingWindow({ minDays: 1, maxDays: 30 }));
  }, []);

  useEffect(() => {
    const dialog = calendarDialogRef.current;
    if (!dialog) return;
    if (calendarOpen && !dialog.open) dialog.showModal();
    if (!calendarOpen && dialog.open) dialog.close();
  }, [calendarOpen]);

  useEffect(() => {
    const dialog = conflictDialogRef.current;
    if (!dialog) return;
    if (scheduleConflict && !dialog.open) dialog.showModal();
    if (!scheduleConflict && dialog.open) dialog.close();
  }, [scheduleConflict]);

  useEffect(() => {
    let active = true;
    fetch("/api/config", { cache: "no-store" }).then(async (response) => {
      const config = await response.json() as { lineLiffId?: string };
      if (!config.lineLiffId) throw new Error("LIFF is not configured");
      const liff = await loadLiff();
      await liff.init({ liffId: config.lineLiffId });
      if (!liff.isLoggedIn()) {
        if (liff.isInClient()) { liff.login({ redirectUri: window.location.href }); return; }
        if (active) setLineState("guest");
        return;
      }
      const token = liff.getIDToken();
      if (!token) throw new Error("LINE ID token is unavailable");
      if (active) { setLineIdToken(token); setLineState("linked"); }
    }).catch(() => active && setLineState("error"));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    fetch("/api/spa/api/v1/public/services", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error("Catalog unavailable");
      const payload = await response.json() as { items?: Array<Service & { descriptionTh?: string | null; descriptionEn?: string | null }> };
      if (!payload.items?.length) throw new Error("Catalog empty");
      setServices(payload.items.map((service, index) => {
        const fallback = INITIAL_SERVICE_CATALOG.find((item) => item.id === service.id);
        return {
          ...service,
          descriptionTh: service.descriptionTh?.trim() || fallback?.descriptionTh || "",
          descriptionEn: service.descriptionEn?.trim() || fallback?.descriptionEn || "",
          active: true,
          displayOrder: index
        };
      }));
      setCatalogLive(true);
    }).catch(() => setCatalogLive(false));
  }, []);

  useEffect(() => {
    const saved = window.sessionStorage.getItem("spa49-booking-preview");
    if (!saved) { queueMicrotask(() => setDraftRestored(true)); return; }
    try {
      const draft = JSON.parse(saved) as { participants?: Array<ParticipantDraft & { variantId?: string }>; date?: string; time?: string; phone?: string };
      queueMicrotask(() => {
        if (draft.participants?.length) setParticipants(draft.participants.slice(0, 2).map((person) => ({ ...person, services: person.services?.slice(0, MAX_SERVICES_PER_PARTICIPANT) ?? (person.variantId ? [person.variantId] : []) })));
        if (draft.date) setDate(draft.date);
        if (draft.time) setTime(draft.time);
        if (draft.phone) setPhone(draft.phone);
        setDraftRestored(true);
      });
    } catch {
      window.sessionStorage.removeItem("spa49-booking-preview");
      queueMicrotask(() => setDraftRestored(true));
    }
  }, []);

  useEffect(() => {
    if (!draftRestored || submittedBookingId) return;
    window.sessionStorage.setItem("spa49-booking-preview", JSON.stringify({ participants, date, time, phone }));
  }, [draftRestored, participants, date, time, phone, submittedBookingId]);

  useEffect(() => {
    if (step !== "SCHEDULE" || !date) return;
    let active = true;
    queueMicrotask(() => { if (active) { setAvailabilityState("loading"); setAvailableSlots([]); setTime(""); } });
    fetch("/api/spa/api/v1/public/availability/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branchId: "branch_001", dateFrom: date, dateTo: date, participants: participants.map((person) => ({ services: person.services.map((serviceVariantId) => ({ serviceVariantId })) })) })
    }).then(async (response) => {
      if (!response.ok) throw new Error("Availability unavailable");
      const payload = await response.json() as { slots?: AvailabilitySlot[] };
      if (active) { setAvailableSlots(payload.slots ?? []); setAvailabilityState("ready"); }
    }).catch(() => { if (active) { setAvailableSlots([]); setAvailabilityState("error"); } });
    return () => { active = false; };
  }, [availabilityRetry, date, participants, step]);

  const chosen = participants.map((participant) => participant.services.map((variantId) => variantById(variantId, services)).filter((item): item is NonNullable<typeof item> => Boolean(item)));
  const selectedCount = chosen.reduce((count, items, participantIndex) => count + items.filter((item) => item.variant.pricingMode !== "PER_BOOKING" || participantIndex === 0).length, 0);
  const total = useMemo(() => {
    const seenPerBooking = new Set<string>();
    return chosen.flat().reduce((sum, item) => {
        if (item.variant.pricingMode === "PER_BOOKING") {
          if (seenPerBooking.has(item.variant.id)) return sum;
          seenPerBooking.add(item.variant.id);
        }
        return sum + item.variant.priceSatang;
      }, 0);
  }, [chosen]);
  const participantDurations = chosen.map((items) => items.reduce((sum, item) => sum + item.variant.durationMinutes, 0));
  const totalDuration = Math.max(0, ...participantDurations);
  const activeIndex = steps.indexOf(step);
  const firstBookableDate = addLocalDays(bangkokToday(), bookingWindow.minDays);
  const lastBookableDate = addLocalDays(bangkokToday(), bookingWindow.maxDays);
  const timeGroups = [
    { id: "morning", th: "ช่วงเช้า", en: "Morning", slots: availableSlots.filter((slot) => Number(slot.localStartTime.slice(0, 2)) < 12) },
    { id: "afternoon", th: "ช่วงบ่าย", en: "Afternoon", slots: availableSlots.filter((slot) => { const hour = Number(slot.localStartTime.slice(0, 2)); return hour >= 12 && hour < 17; }) },
    { id: "evening", th: "ช่วงเย็น", en: "Evening", slots: availableSlots.filter((slot) => Number(slot.localStartTime.slice(0, 2)) >= 17) }
  ].filter((group) => group.slots.length > 0);
  const selectedFirst = chosen[0]?.[0];
  const hasSharedPackage = selectedFirst?.variant.pricingMode === "PER_BOOKING";

  const validationMessages = useMemo(() => {
    if (step === "SERVICE" && selectedCount === 0) return [locale === "th" ? "กรุณาเลือกบริการและระยะเวลา" : "Choose a service and duration"];
    if (step === "PARTICIPANTS" && participants.some((person) => person.services.length === 0)) return [locale === "th" ? "กรุณาเลือกบริการให้ผู้รับบริการทุกท่าน" : "Choose a service for every guest"];
    if (step === "SCHEDULE") {
      if (!date) return [locale === "th" ? "กรุณาเลือกวันที่" : "Choose a date"];
      if (!time) return [locale === "th" ? "กรุณาเลือกเวลาเริ่ม" : "Choose a start time"];
    }
    if (step === "DETAILS") {
      const messages: string[] = [];
      if (!phone.trim()) messages.push(locale === "th" ? "กรุณากรอกเบอร์โทรศัพท์" : "Enter a contact phone number");
      participants.forEach((person, index) => {
        const guest = locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`;
        if (!person.nickname.trim()) messages.push(`${guest}: ${locale === "th" ? "กรุณากรอกชื่อเล่น" : "enter a nickname"}`);
        if (person.hasHealthInformation === null) messages.push(`${guest}: ${locale === "th" ? "กรุณาตอบคำถามข้อมูลสุขภาพ" : "answer the health declaration"}`);
        if (person.hasHealthInformation && !person.healthDetails.trim()) messages.push(`${guest}: ${locale === "th" ? "กรุณาระบุรายละเอียดสุขภาพ" : "provide health details"}`);
        if (!person.healthConsent) messages.push(`${guest}: ${locale === "th" ? "กรุณาให้ความยินยอมด้านข้อมูลสุขภาพ" : "health-data consent is required"}`);
      });
      if (participants.length === 2 && !secondPersonAuthorized) messages.push(locale === "th" ? "กรุณายืนยันการได้รับอนุญาตจากผู้รับบริการคนที่สอง" : "Confirm authorization from the second guest");
      return messages;
    }
    return [];
  }, [date, locale, participants, phone, secondPersonAuthorized, selectedCount, step, time]);

  function resetSchedule() { setDate(""); setTime(""); setAvailableSlots([]); setAvailabilityState("idle"); }
  function openCalendar() {
    const initialDate = date || firstBookableDate;
    setCalendarDraftDate(initialDate);
    setCalendarMonth(monthStart(initialDate));
    setCalendarOpen(true);
  }
  function confirmCalendarDate() {
    if (!calendarDraftDate) return;
    setDate(calendarDraftDate);
    setTime("");
    setCalendarOpen(false);
    setShowValidation(false);
  }
  function selectVariant(variant: ServiceVariant) {
    setParticipants((current) => {
      if (variant.requiredPax === 2) {
        const selected = current[0]?.services[0] === variant.id;
        if (selected) return current.map((person) => ({ ...person, services: person.services.filter((item) => item !== variant.id) }));
        const first = current[0] ?? defaultParticipant();
        const second = current[1] ?? defaultParticipant();
        return [first, second].map((person) => ({ ...person, services: [variant.id, ...person.services.filter((item) => variantById(item, services)?.variant.pricingMode !== "PER_BOOKING")].slice(0, MAX_SERVICES_PER_PARTICIPANT) }));
      }
      const first = current[0] ?? defaultParticipant();
      const exists = first.services.includes(variant.id);
      const nextServices = exists ? first.services.filter((item) => item !== variant.id) : [...first.services, variant.id].slice(0, MAX_SERVICES_PER_PARTICIPANT);
      return [{ ...first, services: nextServices }, ...current.slice(1)];
    });
    resetSchedule(); setShowValidation(false);
  }
  function updateParticipant(index: number, update: Partial<ParticipantDraft>) { setParticipants((current) => current.map((person, i) => i === index ? { ...person, ...update } : person)); }
  function addParticipantService(index: number, variantId: string) {
    if (!variantId) return;
    setParticipants((current) => current.map((person, personIndex) => personIndex !== index || person.services.includes(variantId) || person.services.length >= MAX_SERVICES_PER_PARTICIPANT ? person : { ...person, services: [...person.services, variantId] }));
    resetSchedule(); setShowValidation(false);
  }
  function removeParticipantService(index: number, variantId: string) {
    const shared = variantById(variantId, services)?.variant.pricingMode === "PER_BOOKING";
    setParticipants((current) => current.map((person, personIndex) => shared || personIndex === index ? { ...person, services: person.services.filter((item) => item !== variantId) } : person));
    resetSchedule();
  }
  function moveParticipantService(index: number, serviceIndex: number, direction: -1 | 1) {
    setParticipants((current) => current.map((person, personIndex) => {
      if (personIndex !== index) return person;
      const target = serviceIndex + direction;
      const minimum = hasSharedPackage ? 1 : 0;
      if (target < minimum || target >= person.services.length) return person;
      const reordered = [...person.services];
      [reordered[serviceIndex], reordered[target]] = [reordered[target], reordered[serviceIndex]];
      return { ...person, services: reordered };
    }));
    resetSchedule();
  }
  function setPax(pax: 1 | 2) {
    if (hasSharedPackage && pax === 1) return;
    setParticipants((current) => pax === 1 ? [current[0]] : [current[0], current[1] ?? defaultParticipant()]);
    setSecondPersonAuthorized(false); resetSchedule();
  }
  function goToStep(nextStep: Step) { setStep(nextStep); setShowValidation(false); window.scrollTo({ top: 0, behavior: "smooth" }); }
  function goBack() { if (activeIndex > 0) goToStep(steps[activeIndex - 1]); }
  function continueBooking() {
    if (validationMessages.length) { setShowValidation(true); requestAnimationFrame(() => errorSummaryRef.current?.focus()); return; }
    if (activeIndex < steps.length - 1) goToStep(steps[activeIndex + 1]);
  }

  async function submitBooking() {
    if (!privacyAccepted || isSubmitting) return;
    setSubmitError(null); setIsSubmitting(true);
    try {
      const response = await fetch("/api/spa/api/v1/public/bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey.current },
        body: JSON.stringify({ branchId: "branch_001", date, time, phone, lineIdToken, participants: participants.map((person) => ({ nickname: person.nickname, services: person.services.map((serviceVariantId) => ({ serviceVariantId })), hasHealthInformation: Boolean(person.hasHealthInformation), healthDetails: person.healthDetails || null, healthConsent: person.healthConsent })) })
      });
      const payload = await response.json() as { bookingId?: string; statusToken?: string; code?: string; detail?: string };
      if (response.status === 409 && payload.code === "CAPACITY_UNAVAILABLE") {
        setTime("");
        setAvailableSlots([]);
        setStep("SCHEDULE");
        setScheduleConflict(true);
        setAvailabilityRetry((value) => value + 1);
        idempotencyKey.current = crypto.randomUUID();
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      if (!response.ok || !payload.bookingId) throw new Error(payload.detail || "Booking request failed");
      setSubmittedBookingId(payload.bookingId); setSubmittedStatusToken(payload.statusToken ?? null);
      window.sessionStorage.removeItem("spa49-booking-preview");
      window.history.replaceState({ bookingComplete: true }, "", window.location.pathname);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) { setSubmitError(error instanceof Error ? error.message : "Booking request failed"); }
    finally { setIsSubmitting(false); }
  }

  if (submittedBookingId) {
    return <main className="customer-shell result-shell" id="main-content">
      <header className="site-header"><Brand compact /></header>
      <section className="result-section" aria-labelledby="result-title">
        <span className="status-chip pending">{locale === "th" ? "รอร้านยืนยัน" : "Pending confirmation"}</span>
        <p className="eyebrow">BOOKING REQUEST RECEIVED</p>
        <h1 id="result-title">{locale === "th" ? "ส่งคำขอเรียบร้อยแล้ว" : "Your request has been sent"}</h1>
        <p className="result-lead">{locale === "th" ? "ร้านจะตรวจสอบคิวและยืนยันอีกครั้ง คำขอนี้ยังไม่ใช่การยืนยันการจอง" : "The spa will review availability and confirm your appointment. This request is not confirmed yet."}</p>
        <div className="booking-reference"><span>{locale === "th" ? "หมายเลขการจอง" : "Booking reference"}</span><strong>{submittedBookingId}</strong></div>
        <div className="result-summary">
          <div><span>{locale === "th" ? "วันและเวลา" : "Date and time"}</span><strong>{formatDate(date, locale, { weekday: "long" })} · {time}</strong></div>
          <div><span>{locale === "th" ? "ผู้รับบริการ" : "Guests"}</span><strong>{participants.length} {t.person}</strong></div>
          {chosen.map((items, participantIndex) => <div className="result-service-timeline" key={participantIndex}><span>{participants[participantIndex].nickname || (locale === "th" ? `ผู้รับบริการ ${participantIndex + 1}` : `Guest ${participantIndex + 1}`)}</span><strong>{items.map((item) => locale === "th" ? item.service.nameTh : item.service.nameEn).join(" → ")}</strong><small>{time}–{endTime(time, participantDurations[participantIndex])} · {participantDurations[participantIndex]} {locale === "th" ? "นาที" : "min"}</small></div>)}
          <div><span>{t.total}</span><strong>{formatBaht(total, locale)}</strong></div>
        </div>
        <div className="next-steps" aria-labelledby="next-steps-title"><h2 id="next-steps-title">{locale === "th" ? "ขั้นตอนถัดไป" : "What happens next"}</h2><ol><li>{locale === "th" ? "ร้านตรวจสอบห้องและเวลาว่าง" : "The spa checks room and time availability"}</li><li>{locale === "th" ? "คุณได้รับผลยืนยันผ่าน LINE หากเชื่อมบัญชีไว้" : "You receive confirmation through LINE if connected"}</li><li>{locale === "th" ? "ชำระค่าบริการที่ร้าน" : "Payment is collected at the spa"}</li></ol></div>
        {submittedStatusToken && <a className="primary-button result-action" href={`/status#id=${encodeURIComponent(submittedBookingId)}&t=${encodeURIComponent(submittedStatusToken)}`}>{locale === "th" ? "ตรวจสอบสถานะการจอง" : "Check booking status"}</a>}
        <p className="result-contact">{locale === "th" ? "ต้องการแก้ไขหรือยกเลิก กรุณาติดต่อร้านที่ 064-365-4949" : "To amend or cancel, contact the spa at 064-365-4949."}</p>
      </section>
    </main>;
  }

  return <main className={`customer-shell step-${step.toLowerCase()}`}>
    <header className="site-header"><Brand compact={step !== "SERVICE"} /><div className="language-switch" role="group" aria-label="Language"><button aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button><button aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button></div></header>
    {!catalogLive && <div className="preview-banner" role="status">{locale === "th" ? "กำลังใช้ข้อมูลบริการตัวอย่าง" : "Using the preview service catalog"}</div>}
    {step === "SERVICE" ? <section className="hero" id="main-content"><p className="eyebrow">SPA 49 · SUKHUMVIT</p><h1>{locale === "th" ? "เลือกเวลาพักของคุณ" : "Make time to feel restored"}</h1><p>{locale === "th" ? "เลือกบริการที่เหมาะกับคุณ แล้วให้เราดูแลช่วงเวลาที่เหลือ" : "Choose your treatment and let us take care of the rest."}</p></section> : <div className="booking-progress" id="main-content"><div className="progress-copy"><span>{locale === "th" ? `ขั้นตอน ${activeIndex + 1} จาก ${steps.length}` : `Step ${activeIndex + 1} of ${steps.length}`}</span><strong>{stepLabels[step][locale]}</strong></div><div className="progress-track" aria-hidden="true"><span style={{ width: `${((activeIndex + 1) / steps.length) * 100}%` }} /></div></div>}

    {showValidation && validationMessages.length > 0 && <div className="validation-summary" ref={errorSummaryRef} tabIndex={-1} role="alert"><strong>{locale === "th" ? "กรุณาตรวจสอบข้อมูลต่อไปนี้" : "Check the following details"}</strong><ul>{validationMessages.map((message) => <li key={message}>{message}</li>)}</ul></div>}

    {step === "SERVICE" && <section className="content-section service-section" aria-labelledby="services-title">
      <div className="section-heading"><div><p className="eyebrow">TREATMENT MENU</p><h2 id="services-title">{locale === "th" ? "เลือกบริการ" : "Choose treatments"}</h2></div><p>{locale === "th" ? `เพิ่มได้สูงสุด ${MAX_SERVICES_PER_PARTICIPANT} บริการต่อท่าน จัดลำดับในขั้นตอนถัดไป` : `Add up to ${MAX_SERVICES_PER_PARTICIPANT} treatments per guest and arrange them next`}</p></div>
      <div className="category-tabs" role="tablist" aria-label={locale === "th" ? "ประเภทบริการ" : "Service category"}>{(Object.keys(categoryNames) as Service["category"][]).map((key) => <button id={`category-${key}`} role="tab" aria-controls="service-category-panel" aria-selected={category === key} onClick={() => setCategory(key)} key={key}>{categoryNames[key][locale]}</button>)}</div>
      <div className="service-grid" id="service-category-panel" role="tabpanel" aria-labelledby={`category-${category}`}>{services.filter((service) => service.category === category).map((service) => <article className="service-card" key={service.id}>
        <ServiceArtwork serviceId={service.id} imageVersion={service.imageVersion} />
        <div className="service-card-body"><header><div><p className="service-th">{service.nameTh}</p><h3>{service.nameEn}</h3></div>{service.variants[0]?.requiredPax === 2 && <span className="service-badge">{locale === "th" ? "สำหรับ 2 ท่าน" : "For two"}</span>}</header>
          {(locale === "th" ? service.descriptionTh : service.descriptionEn) && <p className="service-description">{locale === "th" ? service.descriptionTh : service.descriptionEn}</p>}
          <div className="variant-list">{service.variants.map((variant) => { const isSelected = participants.some((person) => person.services.includes(variant.id)); const atLimit = !isSelected && variant.requiredPax === 1 && participants[0].services.length >= MAX_SERVICES_PER_PARTICIPANT; return <button className={isSelected ? "variant selected" : "variant"} onClick={() => selectVariant(variant)} key={variant.id} aria-pressed={isSelected} disabled={atLimit}><span className="variant-duration"><strong>{variant.durationMinutes}</strong> {locale === "th" ? "นาที" : "min"}</span><strong className="variant-price">{formatBaht(variant.priceSatang, locale)}</strong><span className="variant-action">{isSelected ? (locale === "th" ? "เพิ่มแล้ว" : "Added") : (locale === "th" ? "+ เพิ่ม" : "+ Add")}</span><span className="variant-indicator" aria-hidden="true">{isSelected && "✓"}</span></button>; })}</div>
          {service.variants[0]?.requiredPax === 2 && <p className="service-note">{locale === "th" ? "ราคาเดียวสำหรับผู้รับบริการสองท่าน" : "One price for two guests"}</p>}
        </div>
      </article>)}</div>
    </section>}

    {step === "PARTICIPANTS" && selectedFirst && <section className="content-section narrow" aria-labelledby="pax-title">
      <div className="screen-heading"><p className="eyebrow">GUESTS &amp; TREATMENTS</p><h1 id="pax-title">{t.pax}</h1><p>{locale === "th" ? "บริการของแต่ละท่านทำต่อเนื่องตามลำดับ และทุกท่านเริ่มพร้อมกัน" : "Treatments run in order for each guest, and all guests start together."}</p></div>
      <div className="pax-control" role="group" aria-label={t.pax}>{[1, 2].map((pax) => <button key={pax} aria-pressed={participants.length === pax} onClick={() => setPax(pax as 1 | 2)} disabled={hasSharedPackage && pax === 1}><strong>{pax}</strong> {locale === "en" && pax === 2 ? "guests" : t.person}</button>)}</div>
      <div className="participant-plans">{participants.map((participant, participantIndex) => <article className="participant-plan" key={participantIndex} aria-labelledby={`participant-plan-${participantIndex}`}><header><div><span>{locale === "th" ? `ผู้รับบริการ ${participantIndex + 1}` : `Guest ${participantIndex + 1}`}</span><strong id={`participant-plan-${participantIndex}`}>{participantDurations[participantIndex]} {locale === "th" ? "นาที" : "min"}</strong></div><small>{participant.services.length}/{MAX_SERVICES_PER_PARTICIPANT} {locale === "th" ? "บริการ" : "treatments"}</small></header><ol className="service-sequence">{chosen[participantIndex].map((item, serviceIndex) => { const shared = item.variant.pricingMode === "PER_BOOKING"; return <li key={item.variant.id}><span className="sequence-number">{serviceIndex + 1}</span><div><strong>{locale === "th" ? item.service.nameTh : item.service.nameEn}</strong><small>{item.variant.durationMinutes} {locale === "th" ? "นาที" : "min"} · {shared && participantIndex > 0 ? (locale === "th" ? "รวมในแพ็กเกจ" : "Included in package") : formatBaht(item.variant.priceSatang, locale)}</small></div><div className="sequence-actions"><button type="button" onClick={() => moveParticipantService(participantIndex, serviceIndex, -1)} disabled={shared || serviceIndex <= (hasSharedPackage ? 1 : 0)} aria-label={locale === "th" ? `เลื่อน ${item.service.nameTh} ขึ้น` : `Move ${item.service.nameEn} up`}>↑</button><button type="button" onClick={() => moveParticipantService(participantIndex, serviceIndex, 1)} disabled={shared || serviceIndex === participant.services.length - 1} aria-label={locale === "th" ? `เลื่อน ${item.service.nameTh} ลง` : `Move ${item.service.nameEn} down`}>↓</button><button type="button" onClick={() => removeParticipantService(participantIndex, item.variant.id)} aria-label={locale === "th" ? `ลบ ${item.service.nameTh}` : `Remove ${item.service.nameEn}`}>×</button></div></li>; })}</ol>{participant.services.length < MAX_SERVICES_PER_PARTICIPANT && <label className="add-service-select"><span>{locale === "th" ? "+ เพิ่มบริการ" : "+ Add treatment"}</span><select value="" aria-invalid={showValidation && participant.services.length === 0} onChange={(event) => addParticipantService(participantIndex, event.target.value)}><option value="">— {locale === "th" ? "เลือกบริการและระยะเวลา" : "Choose treatment and duration"} —</option>{services.flatMap((service) => service.variants.filter((variant) => variant.requiredPax === 1 && !participant.services.includes(variant.id)).map((variant) => <option value={variant.id} key={variant.id}>{locale === "th" ? service.nameTh : service.nameEn} · {variant.durationMinutes} min · {formatBaht(variant.priceSatang, locale)}</option>))}</select></label>}</article>)}</div>
      {hasSharedPackage && <div className="notice">{locale === "th" ? "แพ็กเกจคู่เป็นรายการแรกของทั้งสองท่านและคิดราคาเพียงครั้งเดียว บริการที่เพิ่มภายหลังคิดแยกต่อท่าน" : "The couple package is first for both guests and charged once. Follow-up treatments are charged per guest."}</div>}
    </section>}

    {step === "SCHEDULE" && <section className="content-section narrow" aria-labelledby="schedule-title">
      <div className="screen-heading"><p className="eyebrow">APPOINTMENT</p><h1 id="schedule-title">{t.schedule}</h1><p>{locale === "th" ? "เวลาที่แสดงผ่านการตรวจสอบความพร้อมของห้องและพื้นที่บริการแล้ว" : "Displayed times account for room and treatment-area availability."}</p></div>
      <h2 className="field-heading">{locale === "th" ? "เลือกวันที่" : "Choose a date"}</h2>
      <button className="date-picker-trigger" type="button" onClick={openCalendar} aria-haspopup="dialog"><span>{locale === "th" ? "วันที่เข้ารับบริการ" : "Appointment date"}</span><strong>{date ? formatDate(date, locale, { weekday: "long", year: "numeric" }) : (locale === "th" ? "แตะเพื่อเปิดปฏิทิน" : "Open calendar")}</strong><span className="date-picker-icon" aria-hidden="true">▾</span></button>
      <p className="helper booking-window-copy">{locale === "th" ? `จองล่วงหน้าได้ ${bookingWindow.minDays}–${bookingWindow.maxDays} วัน` : `Book ${bookingWindow.minDays}–${bookingWindow.maxDays} days in advance`}</p>
      <div className={`availability-message state-${availabilityState}`} role="status" aria-live="polite">{availabilityState === "idle" && (locale === "th" ? "เลือกวันที่เพื่อดูเวลาว่าง" : "Choose a date to see available times")}{availabilityState === "loading" && (locale === "th" ? "กำลังตรวจสอบเวลาว่าง…" : "Checking available times…")}{availabilityState === "ready" && availableSlots.length > 0 && (locale === "th" ? `พบ ${availableSlots.length} ช่วงเวลา` : `${availableSlots.length} times available`)}{availabilityState === "ready" && availableSlots.length === 0 && (locale === "th" ? "วันนี้ไม่มีเวลาว่าง กรุณาเลือกวันอื่น" : "No times are available on this date. Choose another day.")}{availabilityState === "error" && <><span>{locale === "th" ? "ตรวจสอบเวลาว่างไม่สำเร็จ" : "Available times could not be loaded"}</span><button onClick={() => setAvailabilityRetry((value) => value + 1)}>{locale === "th" ? "ลองอีกครั้ง" : "Retry"}</button></>}</div>
      {availableSlots.length > 0 && <div className="time-picker"><h2 className="field-heading">{locale === "th" ? "เลือกเวลาเริ่ม" : "Choose a start time"}</h2>{timeGroups.map((group) => <section className="time-group" aria-labelledby={`time-group-${group.id}`} key={group.id}><h3 id={`time-group-${group.id}`}>{locale === "th" ? group.th : group.en}</h3><div className="time-grid">{group.slots.map((slot) => { const selected = time === slot.localStartTime; return <button className={selected ? "time-option selected" : "time-option"} aria-pressed={selected} onClick={() => { setTime(slot.localStartTime); setShowValidation(false); }} key={slot.localStartTime}><span>{slot.localStartTime}</span><span className="time-option-indicator" aria-hidden="true">{selected && "✓"}</span></button>; })}</div></section>)}</div>}
      {time && <div className="selected-time-summary" role="status"><span>{locale === "th" ? "เวลาที่เลือก" : "Selected time"}</span><strong>{formatDate(date, locale)} · {time}</strong><div className="participant-end-times">{participantDurations.map((duration, index) => <small key={index}>{participants[index].nickname || (locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`)} · {time}–{endTime(time, duration)}</small>)}</div><small>{locale === "th" ? `การจองสิ้นสุดประมาณ ${endTime(time, totalDuration)}` : `Booking ends around ${endTime(time, totalDuration)}`}</small></div>}
      <p className="helper">{locale === "th" ? "เวลาประเทศไทย · เวลาจะถูกตรวจสอบอีกครั้งเมื่อส่งคำขอ" : "Bangkok time · Availability is checked again when you submit"}</p>
      <dialog className="calendar-dialog" ref={calendarDialogRef} onCancel={(event) => { event.preventDefault(); setCalendarOpen(false); }} onClose={() => setCalendarOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) setCalendarOpen(false); }} aria-labelledby="calendar-title"><div className="dialog-surface"><header><div><p className="eyebrow">APPOINTMENT DATE</p><h2 id="calendar-title">{locale === "th" ? "เลือกวันที่" : "Choose a date"}</h2></div><button className="dialog-close" type="button" onClick={() => setCalendarOpen(false)} aria-label={locale === "th" ? "ปิดปฏิทิน" : "Close calendar"}>×</button></header><div className="calendar-month-nav"><button type="button" onClick={() => setCalendarMonth(addMonths(calendarMonth, -1))} disabled={calendarMonth <= monthStart(firstBookableDate)} aria-label={locale === "th" ? "เดือนก่อนหน้า" : "Previous month"}>‹</button><strong>{formatMonth(calendarMonth, locale)}</strong><button type="button" onClick={() => setCalendarMonth(addMonths(calendarMonth, 1))} disabled={calendarMonth >= monthStart(lastBookableDate)} aria-label={locale === "th" ? "เดือนถัดไป" : "Next month"}>›</button></div><div className="calendar-weekdays" aria-hidden="true">{(locale === "th" ? ["อา", "จ", "อ", "พ", "พฤ", "ศ", "ส"] : ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]).map((day) => <span key={day}>{day}</span>)}</div><div className="calendar-grid">{calendarDays(calendarMonth).map((day, index) => day ? <button type="button" key={day} className={calendarDraftDate === day ? "selected" : ""} disabled={day < firstBookableDate || day > lastBookableDate} aria-pressed={calendarDraftDate === day} aria-label={formatDate(day, locale, { weekday: "long", year: "numeric" })} onClick={() => setCalendarDraftDate(day)}>{Number(day.slice(-2))}</button> : <span key={`empty-${index}`} />)}</div><footer><button className="calendar-cancel" type="button" onClick={() => setCalendarOpen(false)}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button className="primary-button" type="button" onClick={confirmCalendarDate} disabled={!calendarDraftDate}>{locale === "th" ? "ใช้วันที่นี้" : "Use this date"}</button></footer></div></dialog>
      <dialog className="conflict-dialog" ref={conflictDialogRef} onCancel={(event) => { event.preventDefault(); setScheduleConflict(false); }} onClose={() => setScheduleConflict(false)} aria-labelledby="conflict-title"><div className="dialog-surface"><span className="conflict-icon" aria-hidden="true">!</span><h2 id="conflict-title">{locale === "th" ? "ช่วงเวลานี้เพิ่งถูกจอง" : "This time was just booked"}</h2><p>{locale === "th" ? "มีลูกค้าท่านอื่นยืนยันช่วงเวลานี้ก่อน ระบบได้ตรวจสอบเวลาว่างล่าสุดให้แล้ว กรุณาเลือกเวลาใหม่" : "Another customer secured this time first. We refreshed the latest availability; please choose another time."}</p><button className="primary-button" type="button" onClick={() => setScheduleConflict(false)}>{locale === "th" ? "เลือกเวลาใหม่" : "Choose another time"}</button></div></dialog>
    </section>}

    {step === "DETAILS" && <section className="content-section narrow" aria-labelledby="details-title">
      <div className="screen-heading"><p className="eyebrow">GUEST DETAILS</p><h1 id="details-title">{t.details}</h1><p>{locale === "th" ? "ข้อมูลสุขภาพช่วยให้ร้านเตรียมบริการได้อย่างปลอดภัย" : "Health information helps the spa prepare a safe treatment."}</p></div>
      <label className="field">{t.contact}<input type="tel" inputMode="tel" autoComplete="tel" value={phone} aria-invalid={showValidation && !phone.trim()} onChange={(event) => setPhone(event.target.value)} placeholder="081 234 5678" /></label>
      {participants.map((participant, index) => <fieldset className="health-card" key={index}><legend>{locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`}</legend><label className="field">{locale === "th" ? "ชื่อเล่น" : "Nickname"}<input value={participant.nickname} aria-invalid={showValidation && !participant.nickname.trim()} onChange={(event) => updateParticipant(index, { nickname: event.target.value })} maxLength={80} /></label><div className="radio-stack" aria-label={locale === "th" ? `ข้อมูลสุขภาพผู้รับบริการ ${index + 1}` : `Health declaration for guest ${index + 1}`}><label><input type="radio" name={`health-${index}`} checked={participant.hasHealthInformation === false} onChange={() => updateParticipant(index, { hasHealthInformation: false, healthDetails: "" })} /> {t.noHealth}</label><label><input type="radio" name={`health-${index}`} checked={participant.hasHealthInformation === true} onChange={() => updateParticipant(index, { hasHealthInformation: true })} /> {t.hasHealth}</label></div>{participant.hasHealthInformation && <label className="field">{locale === "th" ? "รายละเอียดสุขภาพ อาการ โรคประจำตัว หรือการแพ้" : "Health condition, symptom, or allergy details"}<textarea value={participant.healthDetails} aria-invalid={showValidation && !participant.healthDetails.trim()} onChange={(event) => updateParticipant(index, { healthDetails: event.target.value })} maxLength={1000} /></label>}<details className="consent-disclosure"><summary>{locale === "th" ? "เหตุผลที่ต้องขอความยินยอม" : "Why this consent is required"}</summary><p>{locale === "th" ? "ข้อมูลนี้ใช้เพื่อประเมินความเหมาะสม จัดเตรียมบริการอย่างปลอดภัย และปรับปรุงประวัติสุขภาพสำหรับการรับบริการครั้งถัดไป รายละเอียดจะส่งไปยัง Registered Admin LINE Group ซึ่งจำกัดสมาชิกเฉพาะผู้ปฏิบัติงานที่ได้รับอนุญาตและมีหน้าที่รักษาความลับ" : "This information is used to assess suitability, prepare a safe treatment, and maintain the health profile for future visits. Details are sent to the registered Admin LINE Group, restricted to authorized operators bound by confidentiality obligations."}</p></details><label className="consent"><input type="checkbox" checked={participant.healthConsent} onChange={(event) => updateParticipant(index, { healthConsent: event.target.checked })} /><span>{locale === "th" ? "ฉันยินยอมโดยชัดแจ้งให้ SPA 49 เก็บรวบรวม ใช้ และปรับปรุงข้อมูลสุขภาพ อาการ โรคประจำตัว และการแพ้ที่ฉันแจ้ง เพื่อประเมินความเหมาะสมและความปลอดภัยในการให้บริการนวด/สปา จัดเตรียมบริการ และเก็บเป็นประวัติลูกค้าสำหรับการรับบริการครั้งถัดไป รวมถึงส่งรายละเอียดดังกล่าวไปยัง Registered Admin LINE Group ซึ่งจำกัดสมาชิกเฉพาะผู้ปฏิบัติงานที่ได้รับอนุญาตและมีหน้าที่รักษาความลับ ทั้งนี้ ฉันสามารถถอนความยินยอมหรือขอใช้สิทธิตามนโยบายความเป็นส่วนตัวได้" : "I explicitly consent to SPA 49 collecting, using, and updating the health information I provide for treatment suitability and safety, including sending the details to the registered Admin LINE Group restricted to authorized operators bound by confidentiality obligations, as described in the Privacy Notice."}</span></label></fieldset>)}
      {participants.length === 2 && <label className="consent consent-panel"><input type="checkbox" checked={secondPersonAuthorized} onChange={(event) => setSecondPersonAuthorized(event.target.checked)} /><span>{locale === "th" ? "ฉันยืนยันว่าได้รับอนุญาตจากผู้รับบริการคนที่สองให้กรอกและส่งข้อมูลสุขภาพ" : "I confirm the second guest authorized me to submit their health information."}</span></label>}
    </section>}

    {step === "REVIEW" && <section className="content-section narrow" aria-labelledby="review-title">
      <div className="screen-heading"><p className="eyebrow">FINAL REVIEW</p><h1 id="review-title">{t.review}</h1><p>{locale === "th" ? "ตรวจสอบข้อมูลก่อนส่งคำขอให้ร้านยืนยัน" : "Check the details before sending your request to the spa."}</p></div>
      <div className="review-card"><div className="review-timelines">{chosen.map((items, participantIndex) => { let offset = 0; return <section className="review-participant" key={participantIndex}><header><b>{participants[participantIndex].nickname || `${t.person} ${participantIndex + 1}`}</b><small>{time}–{endTime(time, participantDurations[participantIndex])}</small></header>{items.map((item) => { const startsAt = endTime(time, offset); offset += item.variant.durationMinutes; const included = item.variant.pricingMode === "PER_BOOKING" && participantIndex > 0; return <div className="review-row" key={item.variant.id}><span><b>{locale === "th" ? item.service.nameTh : item.service.nameEn}</b><small>{startsAt}–{endTime(time, offset)} · {item.variant.durationMinutes} min</small></span><strong>{included ? (locale === "th" ? "รวมแล้ว" : "Included") : formatBaht(item.variant.priceSatang, locale)}</strong></div>; })}</section>; })}</div><div className="review-row"><span>{locale === "th" ? "วันและเวลา" : "Date and time"}</span><strong>{formatDate(date, locale)} · {time}–{endTime(time, totalDuration)}</strong></div><div className="review-total"><span>{t.total}</span><strong>{formatBaht(total, locale)}</strong></div></div>
      <label className="consent consent-panel"><input type="checkbox" checked={privacyAccepted} onChange={(event) => setPrivacyAccepted(event.target.checked)} /><span>{locale === "th" ? "ฉันยืนยันว่าข้อมูลการจองและข้อมูลติดต่อถูกต้อง และรับทราบ" : "I confirm the booking and contact details are correct and acknowledge the "}<a href="/privacy" target="_blank">{locale === "th" ? "นโยบายความเป็นส่วนตัว" : "Privacy Notice"}</a>{locale === "th" ? " และ" : " and "}<a href="/terms" target="_blank">{locale === "th" ? "เงื่อนไขการจอง" : "Booking Terms"}</a></span></label>
      <div className="payment-note"><strong>{locale === "th" ? "ชำระเงินที่ร้าน" : "Pay at the spa"}</strong><span>{locale === "th" ? "คำขอยังไม่ยืนยันจนกว่าร้านจะตรวจสอบ" : "Your request remains pending until the spa confirms it."}</span></div>
      {lineState === "linked" && <p className="helper centered" role="status">{locale === "th" ? "เชื่อมกับ LINE แล้ว คุณจะได้รับข้อความเมื่อร้านยืนยัน" : "LINE is connected. You will receive confirmation updates."}</p>}{lineState === "loading" && <p className="helper centered" role="status">{locale === "th" ? "กำลังตรวจสอบการเชื่อมต่อ LINE…" : "Checking LINE connection…"}</p>}{(lineState === "guest" || lineState === "error") && <p className="helper centered">{locale === "th" ? "คุณจองแบบ Guest ได้ และเชื่อม LINE ภายหลังจากหน้าสถานะ" : "You can book as a guest and connect LINE later from the status page."}</p>}
      <button className="primary-button submit-button" disabled={!privacyAccepted || isSubmitting} onClick={submitBooking}>{isSubmitting ? (locale === "th" ? "กำลังส่งคำขอ…" : "Sending request…") : t.submit}</button>{submitError && <div className="notice notice-warning submit-error" role="alert"><span>{submitError}</span><button onClick={submitBooking}>{locale === "th" ? "ลองอีกครั้ง" : "Retry"}</button></div>}
    </section>}

    {selectedCount > 0 && <div className="mobile-action-bar" aria-live="polite"><div className="booking-total"><small>{selectedCount} {locale === "th" ? "บริการ" : "treatments"} · {participants.length} {t.person} · {totalDuration} {locale === "th" ? "นาที" : "min"}</small><strong>{formatBaht(total, locale)}</strong></div><div className="bar-actions">{activeIndex > 0 && <button className="back-button" onClick={goBack}>{t.back}</button>}{step !== "REVIEW" && <button className="primary-button" onClick={continueBooking}>{t.continue}</button>}</div></div>}
  </main>;
}
