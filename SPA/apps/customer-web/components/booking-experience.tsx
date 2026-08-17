"use client";

import { INITIAL_SERVICE_CATALOG } from "@spa/shared-types/catalog";
import type { Locale, Service, ServiceVariant } from "@spa/shared-types";
import { useEffect, useMemo, useRef, useState } from "react";
import { loadLiff } from "@/lib/line-liff";

type Step = "SERVICE" | "PARTICIPANTS" | "SCHEDULE" | "DETAILS" | "REVIEW";

type ParticipantDraft = {
  nickname: string;
  variantId: string;
  hasHealthInformation: boolean | null;
  healthDetails: string;
  healthConsent: boolean;
};
type AvailabilitySlot = { localDate: string; localStartTime: string; availableUnits: number };

const steps: Step[] = ["SERVICE", "PARTICIPANTS", "SCHEDULE", "DETAILS", "REVIEW"];

const copy = {
  th: {
    book: "จองบริการ",
    select: "เลือก",
    selected: "เลือกแล้ว",
    continue: "ดำเนินการต่อ",
    back: "ย้อนกลับ",
    pax: "จำนวนผู้รับบริการ",
    schedule: "เลือกวันและเวลา",
    details: "ข้อมูลผู้รับบริการ",
    review: "ตรวจสอบคำขอ",
    person: "ท่าน",
    contact: "เบอร์โทรศัพท์ผู้ติดต่อหลัก",
    noHealth: "ไม่มีข้อมูลสุขภาพที่ต้องแจ้ง",
    hasHealth: "มีข้อมูลสุขภาพที่ต้องแจ้ง",
    healthDetails: "รายละเอียดสุขภาพ อาการ หรือการแพ้",
    submit: "ส่งคำขอจอง",
    total: "ราคาประเมินรวม",
    payAtStore: "ชำระเงินที่ร้าน • คำขอยังไม่ยืนยันจนกว่าร้านจะตรวจสอบ",
    preview: "ตัวอย่างระบบ • ยังไม่ได้เชื่อม API หรือ Availability จริง"
  },
  en: {
    book: "Book a treatment",
    select: "Select",
    selected: "Selected",
    continue: "Continue",
    back: "Back",
    pax: "Number of guests",
    schedule: "Choose date and time",
    details: "Guest details",
    review: "Review request",
    person: "guest",
    contact: "Primary contact phone",
    noHealth: "No health information to share",
    hasHealth: "I have health information to share",
    healthDetails: "Health condition, symptom, or allergy details",
    submit: "Submit booking request",
    total: "Estimated total",
    payAtStore: "Pay at the store • Your request is not confirmed until the store reviews it",
    preview: "Development preview • Live API and availability are not connected"
  }
};

const categoryNames = {
  SIGNATURE: { th: "แพ็กเกจพิเศษ", en: "Signature packages" },
  MASSAGE: { th: "รายการนวดและสปา", en: "Massage & spa" },
  STANDALONE: { th: "บริการจองเดี่ยว", en: "Standalone service" }
} as const;

const defaultParticipant = (variantId = ""): ParticipantDraft => ({
  nickname: "",
  variantId,
  hasHealthInformation: null,
  healthDetails: "",
  healthConsent: false
});

function formatBaht(amountSatang: number, locale: Locale) {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-TH", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0
  }).format(amountSatang / 100);
}

function variantById(id: string, catalog: Service[]) {
  for (const service of catalog) {
    const variant = service.variants.find((item) => item.id === id);
    if (variant) return { service, variant };
  }
  return undefined;
}

function getPreviewDates(locale: Locale) {
  const dates = [];
  const now = new Date();
  for (let offset = 1; offset <= 3; offset += 1) {
    const date = new Date(now);
    date.setDate(now.getDate() + offset);
    dates.push({
      value: new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" }).format(date),
      label: new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        timeZone: "Asia/Bangkok"
      }).format(date)
    });
  }
  return dates;
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
  const [availableSlots, setAvailableSlots] = useState<AvailabilitySlot[]>([]);
  const [availabilityState, setAvailabilityState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [category, setCategory] = useState<Service["category"]>("SIGNATURE");
  const [services, setServices] = useState<Service[]>(INITIAL_SERVICE_CATALOG);
  const [catalogLive, setCatalogLive] = useState(false);
  const [lineIdToken, setLineIdToken] = useState<string | null>(null);
  const [lineState, setLineState] = useState<"loading" | "linked" | "guest" | "error">("loading");
  const idempotencyKey = useRef(crypto.randomUUID());
  const t = copy[locale];

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    let active = true;
    fetch("/api/config", { cache: "no-store" })
      .then(async (response) => {
        const config = await response.json() as { lineLiffId?: string };
        if (!config.lineLiffId) throw new Error("LIFF is not configured");
        const liff = await loadLiff();
        await liff.init({ liffId: config.lineLiffId });
        if (!liff.isLoggedIn()) {
          if (liff.isInClient()) {
            liff.login({ redirectUri: window.location.href });
            return;
          }
          if (active) setLineState("guest");
          return;
        }
        const token = liff.getIDToken();
        if (!token) throw new Error("LINE ID token is unavailable");
        if (active) {
          setLineIdToken(token);
          setLineState("linked");
        }
      })
      .catch(() => active && setLineState("error"));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    fetch("/api/spa/api/v1/public/services", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Catalog unavailable");
        const payload = await response.json() as { items?: Service[] };
        if (!payload.items?.length) throw new Error("Catalog is empty");
        setServices(payload.items.map((service, index) => ({ ...service, active: true, displayOrder: index })));
        setCatalogLive(true);
      })
      .catch(() => setCatalogLive(false));
  }, []);

  useEffect(() => {
    const saved = window.sessionStorage.getItem("spa49-booking-preview");
    if (!saved) return;
    try {
      const draft = JSON.parse(saved) as {
        participants?: ParticipantDraft[];
        date?: string;
        time?: string;
        phone?: string;
      };
      queueMicrotask(() => {
        if (draft.participants?.length) setParticipants(draft.participants.slice(0, 2));
        if (draft.date) setDate(draft.date);
        if (draft.time) setTime(draft.time);
        if (draft.phone) setPhone(draft.phone);
      });
    } catch {
      window.sessionStorage.removeItem("spa49-booking-preview");
    }
  }, []);

  useEffect(() => {
    window.sessionStorage.setItem(
      "spa49-booking-preview",
      JSON.stringify({ participants, date, time, phone })
    );
  }, [participants, date, time, phone]);

  useEffect(() => {
    if (step !== "SCHEDULE" || !date) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setAvailabilityState("loading");
      setAvailableSlots([]);
    });
    fetch("/api/spa/api/v1/public/availability/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branchId: "branch_001", dateFrom: date, dateTo: date, participants: participants.map((person) => ({ serviceVariantId: person.variantId })) })
    }).then(async (response) => {
      if (!response.ok) throw new Error("Availability unavailable");
      const payload = await response.json() as { slots?: AvailabilitySlot[] };
      if (!active) return;
      setAvailableSlots(payload.slots ?? []);
      setAvailabilityState("ready");
    }).catch(() => {
      if (!active) return;
      setAvailableSlots([]);
      setAvailabilityState("error");
    });
    return () => { active = false; };
  }, [date, participants, step]);

  const chosen = participants.map((participant) => variantById(participant.variantId, services));
  const selectedCount = chosen.filter(Boolean).length;
  const total = useMemo(() => {
    const seenPerBooking = new Set<string>();
    return chosen.reduce((sum, item) => {
      if (!item) return sum;
      if (item.variant.pricingMode === "PER_BOOKING") {
        if (seenPerBooking.has(item.variant.id)) return sum;
        seenPerBooking.add(item.variant.id);
      }
      return sum + item.variant.priceSatang;
    }, 0);
  }, [chosen]);
  const totalDuration = Math.max(0, ...chosen.map((item) => item?.variant.durationMinutes ?? 0));
  const activeIndex = steps.indexOf(step);
  const previewDates = getPreviewDates(locale);

  function selectVariant(variant: ServiceVariant) {
    if (variant.requiredPax === 2) {
      setParticipants([defaultParticipant(variant.id), defaultParticipant(variant.id)]);
    } else {
      setParticipants((current) => [{ ...current[0], variantId: variant.id }]);
    }
  }

  function updateParticipant(index: number, update: Partial<ParticipantDraft>) {
    setParticipants((current) => current.map((person, i) => (i === index ? { ...person, ...update } : person)));
  }

  function setPax(pax: 1 | 2) {
    const firstSelection = variantById(participants[0]?.variantId, services);
    if (firstSelection?.variant.requiredPax === 2) return;
    setParticipants((current) =>
      pax === 1 ? [current[0]] : [current[0], current[1] ?? defaultParticipant()]
    );
  }

  function move(direction: 1 | -1) {
    const next = activeIndex + direction;
    if (next >= 0 && next < steps.length) {
      setStep(steps[next]);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  async function submitBooking() {
    setSubmitError(null);
    try {
      const response = await fetch("/api/spa/api/v1/public/bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey.current },
        body: JSON.stringify({
          branchId: "branch_001",
          date,
          time,
          phone,
          lineIdToken,
          participants: participants.map((person) => ({
            nickname: person.nickname,
            serviceVariantId: person.variantId,
            hasHealthInformation: Boolean(person.hasHealthInformation),
            healthDetails: person.healthDetails || null,
            healthConsent: person.healthConsent
          }))
        })
      });
      const payload = await response.json() as { bookingId?: string; statusToken?: string; detail?: string };
      if (!response.ok || !payload.bookingId) throw new Error(payload.detail || "Booking request failed");
      setSubmittedBookingId(payload.bookingId);
      setSubmittedStatusToken(payload.statusToken ?? null);
      window.sessionStorage.removeItem("spa49-booking-preview");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Booking request failed");
    }
  }

  const canContinue =
    (step === "SERVICE" && selectedCount > 0) ||
    (step === "PARTICIPANTS" && participants.every((person) => Boolean(person.variantId))) ||
    (step === "SCHEDULE" && Boolean(date && time)) ||
    (step === "DETAILS" &&
      Boolean(phone.trim()) &&
      participants.every(
        (person) =>
          person.nickname.trim() &&
          person.hasHealthInformation !== null &&
          (!person.hasHealthInformation || person.healthDetails.trim()) &&
          person.healthConsent
      ) &&
      (participants.length === 1 || secondPersonAuthorized)) ||
    step === "REVIEW";

  return (
    <main className="customer-shell">
      <header className="site-header">
        <a className="brand" href="#main-content" aria-label="SPA 49 home">
          <span className="brand-mark" aria-hidden="true">✦</span>
          <span><strong>SPA 49</strong><small>Relax • Renew • Revive</small></span>
        </a>
        <div className="language-switch" role="group" aria-label="Language">
          <button aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button>
          <button aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
        </div>
      </header>

      <div className="preview-banner" role="status">{catalogLive ? (locale === "th" ? "เชื่อมต่อ SPA API และข้อมูลบริการจริงแล้ว" : "Connected to the live SPA API and service catalog") : t.preview}</div>

      <section className="hero" id="main-content">
        <p className="eyebrow">BOTANICAL SANCTUARY</p>
        <h1>{t.book}</h1>
        <p>{locale === "th" ? "เลือกบริการที่เหมาะกับคุณ แล้วส่งคำขอให้ร้านตรวจสอบเวลาว่าง" : "Choose your treatment, then send a request for the store to confirm."}</p>
        <div className="botanical" aria-hidden="true">❧</div>
      </section>

      <nav className="stepper" aria-label="Booking progress">
        {steps.map((item, index) => (
          <div className={index <= activeIndex ? "step active" : "step"} key={item} aria-current={item === step ? "step" : undefined}>
            <span>{index + 1}</span>
            <small>{item.toLowerCase()}</small>
          </div>
        ))}
      </nav>

      {step === "SERVICE" && (
        <section className="content-section" aria-labelledby="services-title">
          <div className="section-heading">
            <div><p className="eyebrow">STEP 1</p><h2 id="services-title">{locale === "th" ? "เลือกบริการ" : "Choose a service"}</h2></div>
            <p>{locale === "th" ? "หนึ่งบริการและหนึ่งระยะเวลาต่อผู้รับบริการ" : "One service and duration per guest"}</p>
          </div>
          <div className="category-tabs" role="tablist" aria-label="Service category">
            {(Object.keys(categoryNames) as Service["category"][]).map((key) => (
              <button role="tab" aria-selected={category === key} onClick={() => setCategory(key)} key={key}>
                {categoryNames[key][locale]}
              </button>
            ))}
          </div>
          <div className="service-grid">
            {services.filter((service) => service.category === category).map((service) => (
              <article className="service-card" key={service.id}>
                <div>
                  <p className="service-th">{service.nameTh}</p>
                  <h3>{service.nameEn}</h3>
                </div>
                <div className="variant-list">
                  {service.variants.map((variant) => {
                    const isSelected = participants.some((person) => person.variantId === variant.id);
                    return (
                      <button className={isSelected ? "variant selected" : "variant"} onClick={() => selectVariant(variant)} key={variant.id} aria-pressed={isSelected}>
                        <span><strong>{variant.durationMinutes}</strong> min</span>
                        <b>{formatBaht(variant.priceSatang, locale)}</b>
                        <small>{isSelected ? t.selected : t.select}</small>
                      </button>
                    );
                  })}
                </div>
                {service.variants[0]?.requiredPax === 2 && <p className="service-note">{locale === "th" ? "แพ็กเกจสำหรับ 2 ท่าน คิดราคา 1 ครั้ง" : "Two guests, charged once per booking"}</p>}
              </article>
            ))}
          </div>
        </section>
      )}

      {step === "PARTICIPANTS" && (
        <section className="content-section narrow" aria-labelledby="pax-title">
          <p className="eyebrow">STEP 2</p><h2 id="pax-title">{t.pax}</h2>
          <div className="pax-control" role="group" aria-label={t.pax}>
            {[1, 2].map((pax) => (
              <button key={pax} aria-pressed={participants.length === pax} onClick={() => setPax(pax as 1 | 2)} disabled={chosen[0]?.variant.requiredPax === 2 && pax === 1}>
                <strong>{pax}</strong> {t.person}
              </button>
            ))}
          </div>
          {participants.map((participant, index) => (
            <div className="participant-service" key={index}>
              <h3>{locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`}</h3>
              <label>
                {locale === "th" ? "บริการและระยะเวลา" : "Service and duration"}
                <select value={participant.variantId} onChange={(event) => updateParticipant(index, { variantId: event.target.value })} disabled={chosen[0]?.variant.requiredPax === 2}>
                  <option value="">— {locale === "th" ? "เลือกบริการ" : "Choose"} —</option>
                  {services.filter((service) => service.variants[0]?.requiredPax === 1).flatMap((service) =>
                    service.variants.map((variant) => <option value={variant.id} key={variant.id}>{locale === "th" ? service.nameTh : service.nameEn} • {variant.durationMinutes} min • {formatBaht(variant.priceSatang, locale)}</option>)
                  )}
                </select>
              </label>
            </div>
          ))}
        </section>
      )}

      {step === "SCHEDULE" && (
        <section className="content-section narrow" aria-labelledby="schedule-title">
          <p className="eyebrow">STEP 3</p><h2 id="schedule-title">{t.schedule}</h2>
          <div className="notice" role="status">{availabilityState === "loading" ? (locale === "th" ? "กำลังตรวจสอบเวลาว่าง…" : "Checking availability…") : availabilityState === "error" ? (locale === "th" ? "ตรวจสอบเวลาว่างไม่สำเร็จ กรุณาลองใหม่" : "Availability could not be loaded. Please retry.") : availableSlots.length ? (locale === "th" ? "เวลานี้มาจาก Availability API และ capacity จริง" : "Times are provided by the live Availability API and capacity.") : (locale === "th" ? "ไม่พบเวลาว่างสำหรับวันที่เลือก" : "No available times for this date")}</div>
          <h3>{locale === "th" ? "วันที่" : "Date"}</h3>
          <div className="choice-grid date-grid">
            {previewDates.map((item) => <button aria-pressed={date === item.value} onClick={() => setDate(item.value)} key={item.value}>{item.label}</button>)}
          </div>
          <h3>{locale === "th" ? "เวลาเริ่ม" : "Start time"}</h3>
          <div className="choice-grid time-grid">
            {availableSlots.map((slot) => <button aria-pressed={time === slot.localStartTime} onClick={() => setTime(slot.localStartTime)} key={slot.localStartTime}>{slot.localStartTime}</button>)}
          </div>
          <p className="helper">Asia/Bangkok • {locale === "th" ? "ต้องจองล่วงหน้าอย่างน้อย 1 วัน" : "Minimum one-day advance booking"}</p>
        </section>
      )}

      {step === "DETAILS" && (
        <section className="content-section narrow" aria-labelledby="details-title">
          <p className="eyebrow">STEP 4</p><h2 id="details-title">{t.details}</h2>
          <label className="field">{t.contact}<input type="tel" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="081 234 5678" /></label>
          {participants.map((participant, index) => (
            <fieldset className="health-card" key={index}>
              <legend>{locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`}</legend>
              <label className="field">{locale === "th" ? "ชื่อเล่น" : "Nickname"}<input value={participant.nickname} onChange={(event) => updateParticipant(index, { nickname: event.target.value })} maxLength={80} /></label>
              <div className="radio-stack">
                <label><input type="radio" name={`health-${index}`} checked={participant.hasHealthInformation === false} onChange={() => updateParticipant(index, { hasHealthInformation: false, healthDetails: "" })} /> {t.noHealth}</label>
                <label><input type="radio" name={`health-${index}`} checked={participant.hasHealthInformation === true} onChange={() => updateParticipant(index, { hasHealthInformation: true })} /> {t.hasHealth}</label>
              </div>
              {participant.hasHealthInformation && <label className="field">{t.healthDetails}<textarea value={participant.healthDetails} onChange={(event) => updateParticipant(index, { healthDetails: event.target.value })} maxLength={1000} /></label>}
              <label className="consent"><input type="checkbox" checked={participant.healthConsent} onChange={(event) => updateParticipant(index, { healthConsent: event.target.checked })} /> <span>{locale === "th" ? "ฉันยินยอมโดยชัดแจ้งให้ SPA 49 ใช้ข้อมูลสุขภาพนี้เพื่อความปลอดภัยในการให้บริการ ตามนโยบายความเป็นส่วนตัว" : "I explicitly consent to SPA 49 using this health information for service safety, as described in the Privacy Notice."}</span></label>
            </fieldset>
          ))}
          {participants.length === 2 && <label className="consent consent-panel"><input type="checkbox" checked={secondPersonAuthorized} onChange={(event) => setSecondPersonAuthorized(event.target.checked)} /> <span>{locale === "th" ? "ฉันยืนยันว่าได้รับอนุญาตจากผู้รับบริการคนที่สองให้กรอกและส่งข้อมูลสุขภาพ" : "I confirm the second guest authorized me to submit their health information."}</span></label>}
        </section>
      )}

      {step === "REVIEW" && (
        <section className="content-section narrow" aria-labelledby="review-title">
          <p className="eyebrow">STEP 5</p><h2 id="review-title">{t.review}</h2>
          <div className="review-card">
            {chosen.map((item, index) => item && <div className="review-row" key={`${item.variant.id}-${index}`}><span><b>{participants[index].nickname || `${t.person} ${index + 1}`}</b><small>{locale === "th" ? item.service.nameTh : item.service.nameEn} • {item.variant.durationMinutes} min</small></span><strong>{item.variant.pricingMode === "PER_BOOKING" && index > 0 ? "—" : formatBaht(item.variant.priceSatang, locale)}</strong></div>)}
            <div className="review-row"><span>{locale === "th" ? "วันและเวลา" : "Date and time"}</span><strong>{date} • {time}</strong></div>
            <div className="review-total"><span>{t.total}</span><strong>{formatBaht(total, locale)}</strong></div>
          </div>
          <label className="consent consent-panel"><input type="checkbox" checked={privacyAccepted} onChange={(event) => setPrivacyAccepted(event.target.checked)} /><span>{locale === "th" ? "ฉันยืนยันว่าข้อมูลถูกต้อง และรับทราบ" : "I confirm the details are correct and acknowledge the "}<a href="/privacy" target="_blank">{locale === "th" ? "นโยบายความเป็นส่วนตัว" : "Privacy Notice"}</a>{locale === "th" ? " และ" : " and "}<a href="/terms" target="_blank">{locale === "th" ? "เงื่อนไขการจอง" : "Booking Terms"}</a></span></label>
          <p className="pay-note">{t.payAtStore}</p>
          {lineState === "linked" && <p className="helper centered" role="status">{locale === "th" ? "เชื่อมกับ LINE แล้ว คุณจะได้รับข้อความเมื่อส่งคำขอและเมื่อร้านยืนยัน" : "Connected to LINE. You will receive request and confirmation updates."}</p>}
          {lineState === "loading" && <p className="helper centered" role="status">{locale === "th" ? "กำลังตรวจสอบ LINE…" : "Checking LINE…"}</p>}
          <button className="primary-button submit-button" disabled={!privacyAccepted || Boolean(submittedBookingId)} onClick={submitBooking}>{submittedBookingId ? `${t.submit} • ${submittedBookingId}` : t.submit}</button>
          {submittedBookingId && <p className="helper centered" role="status">{locale === "th" ? "ส่งคำขอจองเข้าระบบแล้ว ร้านจะตรวจสอบและยืนยันอีกครั้ง" : "Booking request sent. The store will review and confirm it."}</p>}
          {submittedBookingId && submittedStatusToken && <a className="primary-button inline-button" href={`/status#id=${encodeURIComponent(submittedBookingId)}&t=${encodeURIComponent(submittedStatusToken)}`}>{locale === "th" ? "ตรวจสอบสถานะการจอง" : "Check booking status"}</a>}
          {submitError && <p className="helper centered" role="alert">{submitError}</p>}
        </section>
      )}

      <div className="mobile-action-bar" aria-live="polite">
        <div><small>{selectedCount} {t.person} • {totalDuration} min</small><strong>{formatBaht(total, locale)}</strong></div>
        <div className="bar-actions">
          {activeIndex > 0 && <button className="back-button" onClick={() => move(-1)}>{t.back}</button>}
          {step !== "REVIEW" && <button className="primary-button" onClick={() => move(1)} disabled={!canContinue}>{t.continue}</button>}
        </div>
      </div>
    </main>
  );
}
