"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { loadLiff } from "@/lib/line-liff";
import {
  createPaymentAttempt,
  getPaymentOptions,
  PaymentApiError,
  resolvePaymentStatus,
  type PaymentAttempt,
  type PaymentOptions,
  type ResolvedPayment,
} from "@/lib/payment-api";

type Locale = "th" | "en";
type BookingView = "UPCOMING" | "HISTORY";
type LoadState = "authenticating" | "loading" | "ready" | "error";

type CustomerBooking = {
  bookingId: string;
  status: string;
  localDate: string;
  localStartTime: string;
  timezone: string;
  serviceNamesTh: string[];
  serviceNamesEn: string[];
  pax: number;
  estimatedAmountSatang: number;
  priceIncludesVat: boolean;
  paymentStatus: string;
  paidAmountSatang: number;
};

type BookingListResponse = {
  items: CustomerBooking[];
  nextPageToken: string | null;
  detail?: string;
};

const COPY = {
  th: {
    eyebrow: "SPA 49 • LINE MEMBER",
    title: "การจองของฉัน",
    subtitle: "ดูรายการจองที่เชื่อมกับบัญชี LINE นี้",
    upcoming: "กำลังจะมาถึง",
    history: "ประวัติ",
    authenticating: "กำลังยืนยันบัญชี LINE…",
    loading: "กำลังโหลดรายการจอง…",
    error: "ไม่สามารถโหลดรายการจองได้",
    retry: "ลองอีกครั้ง",
    emptyUpcoming: "ยังไม่มีการจองที่กำลังจะมาถึง",
    emptyHistory: "ยังไม่มีประวัติการจอง",
    emptyHint: "รายการจองจะแสดงเมื่อจองผ่าน LINE นี้ หรือเชื่อมการจองด้วย Secure Status Link",
    book: "จองบริการ",
    contact: "ติดต่อร้าน",
    detail: "ดูรายละเอียด",
    reference: "เลขที่การจอง",
    service: "บริการ",
    guests: "จำนวนผู้รับบริการ",
    people: "คน",
    estimate: "ราคาประเมินรวม",
    vat: "รวม VAT แล้ว",
    loadMore: "ดูรายการเพิ่มเติม",
    loadingMore: "กำลังโหลด…",
    payment: "ชำระเงิน",
    paymentReview: "ตรวจสอบยอดชำระ",
    paymentLoading: "กำลังตรวจสอบสิทธิ์ชำระเงิน…",
    paymentUnavailable: "ยังไม่สามารถชำระรายการนี้ได้",
    serviceAmount: "ค่าบริการ (รวม VAT 7%)",
    tip: "ทิปเพิ่มเติม (ไม่บังคับ)",
    noTip: "ไม่มีทิป",
    customTip: "กรอกเอง",
    total: "ยอดชำระทั้งหมด",
    createQr: "สร้าง PromptPay QR",
    creatingQr: "กำลังสร้าง QR…",
    scanQr: "สแกน QR เพื่อชำระเงิน",
    waiting: "กำลังรอการยืนยันจาก Beam",
    paid: "ชำระเงินแล้ว",
    cashHint: "หากชำระเงินสด โปรดแจ้ง Admin ที่หน้าร้าน",
    closePayment: "ปิด"
  },
  en: {
    eyebrow: "SPA 49 • LINE MEMBER",
    title: "My bookings",
    subtitle: "Bookings securely linked to this LINE account",
    upcoming: "Upcoming",
    history: "History",
    authenticating: "Verifying your LINE account…",
    loading: "Loading your bookings…",
    error: "We could not load your bookings",
    retry: "Try again",
    emptyUpcoming: "No upcoming bookings yet",
    emptyHistory: "No booking history yet",
    emptyHint: "Bookings appear here when made with this LINE account or connected from a Secure Status Link.",
    book: "Book a treatment",
    contact: "Contact SPA 49",
    detail: "View details",
    reference: "Booking reference",
    service: "Treatment",
    guests: "Guests",
    people: "guest(s)",
    estimate: "Estimated total",
    vat: "VAT included",
    loadMore: "Load more",
    loadingMore: "Loading…",
    payment: "Pay now",
    paymentReview: "Review payment",
    paymentLoading: "Checking payment eligibility…",
    paymentUnavailable: "This booking is not currently eligible for payment",
    serviceAmount: "Service amount (VAT 7% included)",
    tip: "Add a tip (optional)",
    noTip: "No tip",
    customTip: "Custom",
    total: "Total",
    createQr: "Create PromptPay QR",
    creatingQr: "Creating QR…",
    scanQr: "Scan QR to pay",
    waiting: "Waiting for confirmation from Beam",
    paid: "Payment completed",
    cashHint: "For cash payment, ask the in-store Admin to record the receipt",
    closePayment: "Close"
  }
} as const;

const STATUS_COPY: Record<string, { th: string; en: string }> = {
  PENDING: { th: "รอร้านยืนยัน", en: "Awaiting confirmation" },
  CONFIRMED: { th: "ยืนยันแล้ว", en: "Confirmed" },
  IN_SERVICE: { th: "กำลังรับบริการ", en: "In service" },
  COMPLETED: { th: "เสร็จสิ้น", en: "Completed" },
  CANCELLED: { th: "ยกเลิก", en: "Cancelled" },
  NO_SHOW: { th: "ไม่มาตามนัด", en: "No-show" }
};

function bookingDate(booking: CustomerBooking, locale: Locale) {
  const value = new Date(`${booking.localDate}T${booking.localStartTime}:00+07:00`);
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric"
  }).format(value);
}

function price(satang: number, locale: Locale) {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0
  }).format(satang / 100);
}

async function fetchBookingPage(
  lineIdToken: string,
  view: BookingView,
  pageToken?: string | null,
  signal?: AbortSignal
) {
  const response = await fetch("/api/spa/api/v1/customer/bookings:list", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lineIdToken, view, pageSize: 20, pageToken: pageToken ?? undefined }),
    cache: "no-store",
    signal
  });
  const payload = await response.json() as BookingListResponse;
  if (!response.ok) throw new Error(payload.detail ?? "Booking list failed");
  return payload;
}

export function MyBookings() {
  const [locale, setLocale] = useState<Locale>("th");
  const [view, setView] = useState<BookingView>("UPCOMING");
  const [state, setState] = useState<LoadState>("authenticating");
  const [items, setItems] = useState<CustomerBooking[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [lineIdToken, setLineIdToken] = useState<string | null>(null);
  const [paymentBookingId, setPaymentBookingId] = useState<string | null>(null);
  const [paymentOptions, setPaymentOptions] = useState<PaymentOptions | null>(null);
  const [paymentAttempt, setPaymentAttempt] = useState<PaymentAttempt | null>(null);
  const [resolvedPayment, setResolvedPayment] = useState<ResolvedPayment | null>(null);
  const [paymentState, setPaymentState] = useState<"idle" | "loading" | "ready" | "creating" | "error">("idle");
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [tipAmountSatang, setTipAmountSatang] = useState(0);
  const paymentAttemptKey = useRef<string | null>(null);
  const copy = COPY[locale];

  useEffect(() => {
    let cancelled = false;
    async function authenticate() {
      setLineIdToken(null);
      setState("authenticating");
      try {
        const configResponse = await fetch("/api/config", { cache: "no-store" });
        const config = await configResponse.json() as { lineLiffId?: string | null };
        if (!config.lineLiffId) throw new Error("Booking LIFF is not configured");
        const liff = await loadLiff();
        await liff.init({ liffId: config.lineLiffId });
        if (!liff.isLoggedIn()) {
          liff.login({ redirectUri: window.location.href });
          return;
        }
        const token = liff.getIDToken();
        if (!token) throw new Error("LINE ID token is unavailable");
        if (!cancelled) {
          setLineIdToken(token);
          setState("loading");
        }
      } catch {
        if (!cancelled) setState("error");
      }
    }
    void authenticate();
    return () => { cancelled = true; };
  }, [reloadKey]);

  useEffect(() => {
    if (!lineIdToken) return;
    const authenticatedToken = lineIdToken;
    let cancelled = false;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    async function loadBookings() {
      try {
        const payload = await fetchBookingPage(
          authenticatedToken,
          view,
          null,
          controller.signal
        );
        if (!cancelled) {
          setItems(payload.items);
          setNextPageToken(payload.nextPageToken);
          setState("ready");
        }
      } catch {
        if (!cancelled) setState("error");
      } finally {
        window.clearTimeout(timeout);
      }
    }
    void loadBookings();
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [lineIdToken, view]);

  function selectView(nextView: BookingView) {
    if (nextView === view) return;
    setView(nextView);
    setItems([]);
    setNextPageToken(null);
    setState("loading");
  }

  async function loadMore() {
    if (!lineIdToken || !nextPageToken || loadingMore) return;
    setLoadingMore(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const payload = await fetchBookingPage(lineIdToken, view, nextPageToken, controller.signal);
      setItems((current) => [...current, ...payload.items]);
      setNextPageToken(payload.nextPageToken);
    } catch {
      setState("error");
    } finally {
      window.clearTimeout(timeout);
      setLoadingMore(false);
    }
  }

  async function openPayment(bookingId: string) {
    if (!lineIdToken) return;
    setPaymentBookingId(bookingId);
    setPaymentOptions(null);
    setPaymentAttempt(null);
    setResolvedPayment(null);
    setPaymentError(null);
    setTipAmountSatang(0);
    setPaymentState("loading");
    paymentAttemptKey.current = null;
    try {
      setPaymentOptions(await getPaymentOptions(bookingId, lineIdToken));
      setPaymentState("ready");
    } catch (error) {
      setPaymentError(error instanceof PaymentApiError ? error.code : "PAYMENT_OPTIONS_UNAVAILABLE");
      setPaymentState("error");
    }
  }

  async function payWithBeam() {
    if (!lineIdToken || !paymentBookingId || !paymentOptions?.eligible) return;
    setPaymentState("creating");
    setPaymentError(null);
    paymentAttemptKey.current ??= crypto.randomUUID();
    try {
      setPaymentAttempt(await createPaymentAttempt(
        paymentBookingId,
        lineIdToken,
        tipAmountSatang,
        paymentAttemptKey.current,
      ));
      setPaymentState("ready");
    } catch (error) {
      setPaymentError(error instanceof PaymentApiError ? error.code : "PAYMENT_ATTEMPT_UNAVAILABLE");
      setPaymentState("error");
    }
  }

  useEffect(() => {
    if (
      !paymentAttempt?.statusToken
      || resolvedPayment?.status === "PAID"
      || resolvedPayment?.status === "DUE"
      || resolvedPayment?.status === "PAYMENT_REVIEW"
    ) return;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const result = await resolvePaymentStatus(paymentAttempt.statusToken, controller.signal);
        if (controller.signal.aborted) return;
        setResolvedPayment(result);
        if (result.status === "PAID") {
          setItems((current) => current.map((booking) => booking.bookingId === result.bookingId
            ? { ...booking, paymentStatus: "PAID", paidAmountSatang: result.grossAmountSatang }
            : booking));
        } else if (result.status === "DUE" || result.status === "PAYMENT_REVIEW") {
          setPaymentAttempt(null);
          paymentAttemptKey.current = null;
          setPaymentError(result.status === "DUE" ? "PAYMENT_ATTEMPT_FAILED" : "PAYMENT_REVIEW_REQUIRED");
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setPaymentError(error instanceof PaymentApiError ? error.code : "PAYMENT_STATUS_UNAVAILABLE");
        }
      }
    };
    void poll();
    const interval = window.setInterval(() => { void poll(); }, 4_000);
    return () => { controller.abort(); window.clearInterval(interval); };
  }, [paymentAttempt, resolvedPayment?.status]);

  return <main className="my-bookings-shell">
    <header className="my-bookings-header">
      <Link href="/" className="spa-logo-link" aria-label="SPA 49 booking">
        {/* The supplied brand asset is intentionally shown as-is. */}
        <Image src="/spa49-logo.png" alt="SPA 49" width={140} height={112} priority />
      </Link>
      <div className="language-switch" aria-label="Language">
        <button type="button" aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button>
        <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
      </div>
    </header>

    <section className="my-bookings-intro" aria-labelledby="my-bookings-title">
      <p className="eyebrow">{copy.eyebrow}</p>
      <h1 id="my-bookings-title">{copy.title}</h1>
      <p>{copy.subtitle}</p>
    </section>

    <section className="my-bookings-content" aria-busy={state !== "ready"}>
      <div className="booking-tabs" role="tablist" aria-label={copy.title}>
        <button type="button" role="tab" aria-selected={view === "UPCOMING"} disabled={state === "authenticating"} onClick={() => selectView("UPCOMING")}>{copy.upcoming}</button>
        <button type="button" role="tab" aria-selected={view === "HISTORY"} disabled={state === "authenticating"} onClick={() => selectView("HISTORY")}>{copy.history}</button>
      </div>

      {(state === "authenticating" || state === "loading") && <div className="booking-list-state" role="status">
        <span className="loading-mark" aria-hidden="true" />
        <p>{state === "authenticating" ? copy.authenticating : copy.loading}</p>
      </div>}

      {state === "error" && <div className="booking-list-state booking-list-error" role="alert">
        <h2>{copy.error}</h2>
        <button type="button" className="primary-button" onClick={() => setReloadKey((value) => value + 1)}>{copy.retry}</button>
        <a href="tel:0643654949">{copy.contact} · 064-365-4949</a>
      </div>}

      {state === "ready" && items.length === 0 && <div className="booking-list-state booking-list-empty">
        <Image src="/spa49-logo.png" alt="" width={112} height={90} aria-hidden="true" />
        <h2>{view === "UPCOMING" ? copy.emptyUpcoming : copy.emptyHistory}</h2>
        <p>{copy.emptyHint}</p>
        <div className="empty-actions">
          <Link href="/" className="primary-button">{copy.book}</Link>
          <a href="tel:0643654949" className="secondary-button">{copy.contact}</a>
        </div>
      </div>}

      {state === "ready" && items.length > 0 && <div className="booking-list">
        {items.map((booking, index) => {
          const status = STATUS_COPY[booking.status]?.[locale] ?? booking.status;
          const services = (locale === "th" ? booking.serviceNamesTh : booking.serviceNamesEn).filter(Boolean);
          return <article className={`booking-list-item${view === "UPCOMING" && index === 0 ? " next-booking" : ""}`} key={booking.bookingId}>
            {view === "UPCOMING" && index === 0 && <p className="next-booking-label">{locale === "th" ? "นัดหมายถัดไป" : "Next appointment"}</p>}
            <div className="booking-item-summary">
              <div>
                <time dateTime={`${booking.localDate}T${booking.localStartTime}:00+07:00`}>{bookingDate(booking, locale)}</time>
                <strong>{booking.localStartTime} {locale === "th" ? "น." : "hrs"}</strong>
              </div>
              <span className={`booking-status status-${booking.status.toLowerCase()}`}>{status}</span>
            </div>
            <h2>{services.join(" · ") || copy.service}</h2>
            <details className="booking-detail">
              <summary>{copy.detail}</summary>
              <dl>
                <div><dt>{copy.reference}</dt><dd>{booking.bookingId}</dd></div>
                <div><dt>{copy.guests}</dt><dd>{booking.pax} {copy.people}</dd></div>
                <div><dt>{copy.estimate}</dt><dd>{price(booking.estimatedAmountSatang, locale)}<small>{copy.vat}</small></dd></div>
              </dl>
            </details>
            {booking.status === "COMPLETED" && <div className="booking-payment-action">
              {booking.paymentStatus === "PAID"
                ? <span className="booking-paid-mark">✓ {copy.paid}</span>
                : <button
                    type="button"
                    className="secondary-button"
                    aria-expanded={paymentBookingId === booking.bookingId}
                    onClick={() => { void openPayment(booking.bookingId); }}
                  >{copy.payment}</button>}
            </div>}
            {paymentBookingId === booking.bookingId && <section className="customer-payment-panel" aria-label={copy.paymentReview}>
              <div className="customer-payment-heading">
                <div><p className="eyebrow">PAYMENT</p><h3>{copy.paymentReview}</h3></div>
                <button type="button" onClick={() => setPaymentBookingId(null)}>{copy.closePayment}</button>
              </div>
              {paymentState === "loading" && <p role="status">{copy.paymentLoading}</p>}
              {paymentOptions && <>
                <div className="customer-payment-line"><span>{copy.serviceAmount}</span><strong>{price(paymentOptions.serviceAmountSatang, locale)}</strong></div>
                <fieldset disabled={!paymentOptions.eligible || Boolean(paymentAttempt)}>
                  <legend>{copy.tip}</legend>
                  <div className="customer-tip-options">
                    {paymentOptions.tipPresetsSatang.map((tip) => <button
                      type="button"
                      key={tip}
                      aria-pressed={tipAmountSatang === tip}
                      onClick={() => { setTipAmountSatang(tip); paymentAttemptKey.current = null; }}
                    >{tip === 0 ? copy.noTip : price(tip, locale)}</button>)}
                    {paymentOptions.customTipMaxSatang !== null && <label>
                      <span>{copy.customTip}</span>
                      <input
                        type="number"
                        min="0"
                        max={paymentOptions.customTipMaxSatang / 100}
                        step="1"
                        inputMode="decimal"
                        placeholder={`0–${paymentOptions.customTipMaxSatang / 100}`}
                        onChange={(event) => {
                          setTipAmountSatang(Math.round(Math.max(0, Number(event.target.value)) * 100));
                          paymentAttemptKey.current = null;
                        }}
                      />
                    </label>}
                  </div>
                </fieldset>
                <div className="customer-payment-total"><span>{copy.total}</span><strong>{price(paymentOptions.serviceAmountSatang + tipAmountSatang, locale)}</strong></div>
                {!paymentOptions.eligible && <p className="payment-message">{copy.paymentUnavailable} · {paymentOptions.reason}</p>}
                {paymentOptions.eligible && !paymentAttempt && <button
                  type="button"
                  className="primary-button payment-submit"
                  disabled={paymentState === "creating" || !paymentOptions.methods.includes("QR_PROMPT_PAY")}
                  onClick={() => { void payWithBeam(); }}
                >{paymentState === "creating" ? copy.creatingQr : copy.createQr}</button>}
                <p className="payment-cash-hint">{copy.cashHint}</p>
              </>}
              {paymentAttempt?.actionRequired === "ENCODED_IMAGE" && paymentAttempt.imageBase64 && resolvedPayment?.status !== "PAID" && <div className="beam-qr" role="status">
                <h3>{copy.scanQr}</h3>
                <Image
                  unoptimized
                  src={`data:image/png;base64,${paymentAttempt.imageBase64}`}
                  alt={copy.scanQr}
                  width={260}
                  height={260}
                />
                <p>{copy.waiting}</p>
                {paymentAttempt.expiresAt && <time dateTime={paymentAttempt.expiresAt}>{new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(paymentAttempt.expiresAt))}</time>}
              </div>}
              {paymentAttempt?.actionRequired === "REDIRECT" && paymentAttempt.redirectUrl && <a className="primary-button payment-submit" href={paymentAttempt.redirectUrl} rel="noopener noreferrer">{copy.payment}</a>}
              {resolvedPayment?.status === "PAID" && <div className="payment-success" role="status"><strong>✓ {copy.paid}</strong>{resolvedPayment.paidAt && <time dateTime={resolvedPayment.paidAt}>{new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(resolvedPayment.paidAt))}</time>}</div>}
              {paymentError && <p className="payment-error" role="alert">{paymentError}</p>}
            </section>}
          </article>;
        })}
        {nextPageToken && <button type="button" className="load-more-button" onClick={loadMore} disabled={loadingMore}>{loadingMore ? copy.loadingMore : copy.loadMore}</button>}
      </div>}

      {state === "ready" && items.length > 0 && <nav className="my-bookings-actions" aria-label={locale === "th" ? "การดำเนินการ" : "Actions"}>
        <Link href="/" className="primary-button">{copy.book}</Link>
        <a href="tel:0643654949" className="secondary-button">{copy.contact}</a>
      </nav>}
    </section>
  </main>;
}
