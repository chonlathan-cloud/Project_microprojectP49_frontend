"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";

import { loadLiff } from "@/lib/line-liff";

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
    loadingMore: "กำลังโหลด…"
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
    loadingMore: "Loading…"
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
