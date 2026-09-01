"use client";

import { INITIAL_SERVICE_CATALOG, type BookingStatus, type Locale, type PreviewBooking } from "@spa/shared-types";
import type { User } from "firebase/auth";
import { useEffect, useRef, useState } from "react";

import { AdminModulePage, type AdminView } from "@/components/admin-module-pages";
import { useAdminFeedback } from "@/components/admin-feedback";
import { WalkInBookingDrawer } from "@/components/walk-in-booking-drawer";
import { adminApi } from "@/lib/admin-api";
import { countNotificationsRequiringAction } from "@/lib/notification-state";

const statusLabel: Record<BookingStatus, { th: string; en: string }> = {
  PENDING: { th: "รอยืนยัน", en: "Pending" },
  CONFIRMED: { th: "ยืนยันแล้ว", en: "Confirmed" },
  IN_SERVICE: { th: "กำลังให้บริการ", en: "In service" },
  COMPLETED: { th: "เสร็จสิ้น", en: "Completed" },
  CANCELLED: { th: "ยกเลิก", en: "Cancelled" },
  NO_SHOW: { th: "ไม่มาตามนัด", en: "No show" },
  RECORDED: { th: "บันทึกย้อนหลัง", en: "Recorded" }
};

function adminEntryLabel(booking: PreviewBooking, locale: Locale): string {
  if (booking.adminEntryMode === "HISTORICAL_RECORD") return locale === "th" ? "บันทึกย้อนหลัง" : "Historical";
  return locale === "th" ? "Admin จองให้" : "Staff assisted";
}

const navItems = [
  ["bookings", "▦", "รายการจอง", "Bookings"],
  ["calendar", "◫", "ปฏิทิน", "Calendar"],
  ["capacity", "⌁", "สล็อตและความจุ", "Capacity"],
  ["services", "◇", "บริการและราคา", "Services"],
  ["therapists", "♙", "หมอนวด", "Therapists"],
  ["campaign-operations", "◎", "ลูกค้าและแคมเปญ", "CRM & Campaigns"],
  ["notifications", "◉", "การแจ้งเตือน", "Notifications"]
] as const;

function formatTime(value: string) {
  return new Intl.DateTimeFormat("th-TH", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Bangkok"
  }).format(new Date(value));
}

function formatDate(value: string, locale: Locale) {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Bangkok"
  }).format(new Date(value));
}

function formatServiceName(booking: PreviewBooking, locale: Locale) {
  const localizedSnapshot = locale === "th" ? booking.serviceNameTh : booking.serviceNameEn;
  if (localizedSnapshot) return localizedSnapshot;
  const service = INITIAL_SERVICE_CATALOG.find((item) => booking.serviceName.includes(item.nameEn) || booking.serviceName.includes(item.nameTh));
  if (!service) return booking.serviceName;
  return locale === "th" ? service.nameTh : service.nameEn;
}

function formatBaht(satang: number, locale: Locale) {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(satang / 100);
}

type AdminPaymentOptions = {
  paymentId: string;
  status: string;
  source: "BEAM" | "CASH" | null;
  serviceAmountSatang: number;
  eligible: boolean;
  reason: string | null;
  tipPresetsSatang: number[];
  customTipMaxSatang: number | null;
  version: number;
};

type AdminBookingListResponse = {
  items?: PreviewBooking[];
  nextPageToken?: string | null;
  hasMore?: boolean;
  pageSize?: number;
  summary?: {
    pending?: number;
    unassigned?: number;
  };
};

const DEFAULT_BOOKING_PAGE_SIZE = 25;
const BOOKING_PAGE_SIZES = [25, 50, 100] as const;
const BOOKING_FILTERS = new Set<string>(["ALL", ...Object.keys(statusLabel)]);

function bookingListUrl({
  query,
  filter,
  pageSize,
  pageToken,
  pageNumber,
  previousPageTokens,
}: {
  query: string;
  filter: "ALL" | BookingStatus;
  pageSize: number;
  pageToken: string | null;
  pageNumber: number;
  previousPageTokens: Array<string | null>;
}) {
  const url = new URL(window.location.href);
  if (query) url.searchParams.set("q", query);
  else url.searchParams.delete("q");
  if (filter !== "ALL") url.searchParams.set("status", filter);
  else url.searchParams.delete("status");
  if (pageSize !== DEFAULT_BOOKING_PAGE_SIZE) url.searchParams.set("pageSize", String(pageSize));
  else url.searchParams.delete("pageSize");
  if (pageToken) url.searchParams.set("pageToken", pageToken);
  else url.searchParams.delete("pageToken");
  if (pageNumber > 1) url.searchParams.set("page", String(pageNumber));
  else url.searchParams.delete("page");
  return {
    url,
    state: { ...window.history.state, bookingPageTokens: previousPageTokens },
  };
}

export function AdminDashboard({ user }: { user: User }) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const [activeView, setActiveView] = useState<"bookings" | AdminView>("bookings");
  const [locale, setLocale] = useState<Locale>("th");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [filter, setFilter] = useState<"ALL" | BookingStatus>("ALL");
  const [paginationReady, setPaginationReady] = useState(false);
  const [pageSize, setPageSize] = useState(DEFAULT_BOOKING_PAGE_SIZE);
  const [pageToken, setPageToken] = useState<string | null>(null);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [previousPageTokens, setPreviousPageTokens] = useState<Array<string | null>>([]);
  const [bookingSummary, setBookingSummary] = useState({ pending: 0, unassigned: 0 });
  const [selectedId, setSelectedId] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [liveBookings, setLiveBookings] = useState<PreviewBooking[]>([]);
  const [bookingState, setBookingState] = useState<"loading" | "ready" | "error">("loading");
  const [actionState, setActionState] = useState<"idle" | "submitting">("idle");
  const [healthDetails, setHealthDetails] = useState<Array<{ nickname: string; details: string }> | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [bookingRefresh, setBookingRefresh] = useState(0);
  const [notificationFailures, setNotificationFailures] = useState(0);
  const [notificationFilter, setNotificationFilter] = useState<"ALL" | "ACTION_REQUIRED">("ALL");
  const [paymentOptions, setPaymentOptions] = useState<AdminPaymentOptions | null>(null);
  const [paymentLoadState, setPaymentLoadState] = useState<"idle" | "loading" | "ready" | "saving" | "error">("idle");
  const [cashTipSatang, setCashTipSatang] = useState(0);
  const [walkInOpen, setWalkInOpen] = useState(false);
  const detailDrawerRef = useRef<HTMLElement>(null);
  const closeDrawerButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  function resetPagination() {
    setPageToken(null);
    setNextPageToken(null);
    setPageNumber(1);
    setPreviousPageTokens([]);
  }

  function changeBookingFilter(nextFilter: "ALL" | BookingStatus) {
    setFilter(nextFilter);
    resetPagination();
  }

  function goToNextPage() {
    if (!nextPageToken || bookingState === "loading") return;
    const nextHistory = [...previousPageTokens, pageToken];
    const nextPage = pageNumber + 1;
    const destination = bookingListUrl({ query: debouncedQuery, filter, pageSize, pageToken: nextPageToken, pageNumber: nextPage, previousPageTokens: nextHistory });
    window.history.pushState(destination.state, "", destination.url);
    setPreviousPageTokens(nextHistory);
    setPageToken(nextPageToken);
    setNextPageToken(null);
    setPageNumber(nextPage);
    setSelectedId("");
  }

  function goToPreviousPage() {
    if (previousPageTokens.length === 0 || bookingState === "loading") return;
    window.history.back();
  }

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    const restorePagination = () => {
      const params = new URLSearchParams(window.location.search);
      const bookingId = params.get("booking") ?? "";
      const restoredQuery = params.get("q") ?? bookingId;
      const restoredFilter = params.get("status") ?? "ALL";
      const restoredPageSize = Number(params.get("pageSize") ?? DEFAULT_BOOKING_PAGE_SIZE);
      const restoredPageNumber = Math.max(1, Number(params.get("page") ?? 1) || 1);
      const restoredHistory = Array.isArray(window.history.state?.bookingPageTokens)
        ? window.history.state.bookingPageTokens.filter((token: unknown) => token === null || typeof token === "string")
        : [];
      setQuery(restoredQuery);
      setDebouncedQuery(restoredQuery.trim());
      setFilter(BOOKING_FILTERS.has(restoredFilter) ? restoredFilter as "ALL" | BookingStatus : "ALL");
      setPageSize(BOOKING_PAGE_SIZES.includes(restoredPageSize as (typeof BOOKING_PAGE_SIZES)[number]) ? restoredPageSize : DEFAULT_BOOKING_PAGE_SIZE);
      setPageToken(params.get("pageToken"));
      setNextPageToken(null);
      setPageNumber(restoredPageNumber);
      setPreviousPageTokens(restoredHistory);
      setSelectedId("");
      setPaginationReady(true);
    };
    restorePagination();
    window.addEventListener("popstate", restorePagination);
    return () => window.removeEventListener("popstate", restorePagination);
  }, []);

  useEffect(() => {
    if (!paginationReady) return;
    const timer = window.setTimeout(() => {
      const normalizedQuery = query.trim();
      if (normalizedQuery !== debouncedQuery) {
        setDebouncedQuery(normalizedQuery);
        resetPagination();
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [debouncedQuery, paginationReady, query]);

  useEffect(() => {
    if (!paginationReady || activeView !== "bookings") return;
    const destination = bookingListUrl({ query: debouncedQuery, filter, pageSize, pageToken, pageNumber, previousPageTokens });
    window.history.replaceState(destination.state, "", destination.url);
  }, [activeView, debouncedQuery, filter, pageNumber, pageSize, pageToken, paginationReady, previousPageTokens]);

  useEffect(() => {
    if (bookingState !== "ready") return;
    const bookingId = new URLSearchParams(window.location.search).get("booking");
    if (bookingId && liveBookings.some((booking) => booking.bookingId === bookingId)) {
      queueMicrotask(() => {
        setActiveView("bookings");
        setSelectedId(bookingId);
      });
    }
  }, [bookingState, liveBookings]);

  useEffect(() => {
    const update = () => setCurrentTime(Date.now());
    queueMicrotask(update);
    const timer = window.setInterval(update, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!paginationReady) return;
    let active = true;
    (async () => {
      try {
        setBookingState("loading");
        const params = new URLSearchParams();
        if (activeView === "bookings") {
          params.set("pageSize", String(pageSize));
          if (pageToken) params.set("pageToken", pageToken);
          if (filter !== "ALL") params.set("status", filter);
          if (debouncedQuery) params.set("search", debouncedQuery);
        } else {
          params.set("pageSize", "100");
        }
        const payload = await adminApi<AdminBookingListResponse>(user, `/bookings?${params.toString()}`);
        if (!active) return;
        setLiveBookings(payload.items ?? []);
        if (activeView === "bookings") {
          setNextPageToken(payload.nextPageToken ?? null);
          setBookingSummary((current) => ({
            pending: payload.summary?.pending ?? current.pending,
            unassigned: payload.summary?.unassigned ?? current.unassigned,
          }));
        }
        setBookingState("ready");
      } catch {
        if (!active) return;
        setBookingState("error");
      }
    })();
    return () => { active = false; };
  }, [activeView, bookingRefresh, debouncedQuery, filter, pageSize, pageToken, paginationReady, user]);

  useEffect(() => {
    let active = true;
    const loadNotificationCount = () => {
      adminApi<{ items?: Array<{ state?: string }> }>(user, "/notifications")
        .then((payload) => {
          if (active) setNotificationFailures(countNotificationsRequiringAction(payload.items ?? []));
        })
        .catch(() => {
          // Keep the last known count when a refresh fails instead of hiding an existing alert.
        });
    };
    loadNotificationCount();
    const timer = window.setInterval(loadNotificationCount, 30_000);
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") loadNotificationCount();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [user, bookingRefresh]);

  useEffect(() => {
    if (!selectedId || !["bookings", "calendar"].includes(activeView)) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeDrawerButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedId("");
        setHealthDetails(null);
        return;
      }
      if (event.key !== "Tab" || !detailDrawerRef.current) return;
      const focusable = Array.from(detailDrawerRef.current.querySelectorAll<HTMLElement>(
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
      previousFocusRef.current?.focus();
    };
  }, [selectedId, activeView]);

  async function transitionBooking(action: "confirm" | "cancel" | "start" | "no_show" | "complete") {
    const booking = liveBookings.find((item) => item.bookingId === selectedId);
    if (!booking || actionState === "submitting") return;

    const confirmation = action === "cancel"
      ? await requestConfirmation({
          title: booking.status === "RECORDED"
            ? (locale === "th" ? "ยกเลิกรายการย้อนหลังนี้?" : "Cancel this historical record?")
            : (locale === "th" ? "ยกเลิกการจองนี้?" : "Cancel this booking?"),
          message: booking.status === "RECORDED"
            ? (locale === "th" ? `${booking.bookingId} จะเปลี่ยนเป็นยกเลิกและไม่นับยอดทางการเงิน โดยไม่กระทบ Capacity` : `${booking.bookingId} will be cancelled and excluded from financial totals without changing capacity.`)
            : (locale === "th" ? `${booking.bookingId} จะถูกยกเลิกและคืน Capacity ให้ระบบ` : `${booking.bookingId} will be cancelled and its capacity released.`),
          confirmLabel: booking.status === "RECORDED"
            ? (locale === "th" ? "ยืนยันยกเลิกรายการ" : "Cancel record")
            : (locale === "th" ? "ยืนยันยกเลิก" : "Cancel booking"),
          cancelLabel: locale === "th" ? "กลับ" : "Go back",
          tone: "danger",
          input: {
            label: locale === "th" ? "เหตุผลในการยกเลิก" : "Cancellation reason",
            placeholder: locale === "th" ? "ระบุเหตุผลเพื่อใช้ตรวจสอบภายหลัง" : "Add a reason for the audit trail",
            required: true,
            maxLength: 300
          }
        })
      : await requestConfirmation({
          title: locale === "th" ? "ยืนยันการเปลี่ยนสถานะ?" : "Confirm status change?",
          message: locale === "th" ? `ระบบจะอัปเดตสถานะของ ${booking.bookingId}` : `The status of ${booking.bookingId} will be updated.`,
          confirmLabel: locale === "th" ? "ยืนยัน" : "Confirm",
          cancelLabel: locale === "th" ? "ยกเลิก" : "Cancel"
        });
    if (!confirmation.confirmed) return;
    const reason = action === "cancel" ? confirmation.inputValue : null;

    setActionState("submitting");
    try {
      const payload = await adminApi<{ status?: BookingStatus; version?: number; detail?: string }>(user, `/bookings/${encodeURIComponent(booking.bookingId)}:${action}`, {
        method: "POST",
        body: JSON.stringify({
          reason,
          expectedVersion: booking.version,
          commandId: crypto.randomUUID()
        })
      });
      if (!payload.status) throw new Error(payload.detail ?? "Booking transition failed");
      setLiveBookings((items) => items.map((item) => item.bookingId === booking.bookingId
        ? { ...item, status: payload.status as BookingStatus, version: payload.version ?? item.version + 1 }
        : item));
      setBookingRefresh((value) => value + 1);
      notify({
        tone: "success",
        title: action === "cancel" && booking.status === "RECORDED"
          ? (locale === "th" ? "ยกเลิกรายการย้อนหลังแล้ว" : "Historical record cancelled")
          : (locale === "th" ? "อัปเดตสถานะการจองแล้ว" : "Booking status updated"),
        message: booking.bookingId
      });
    } catch (caught) {
      notify({
        tone: "error",
        title: locale === "th" ? "อัปเดตสถานะไม่สำเร็จ" : "Status update failed",
        message: caught instanceof Error ? caught.message : "Booking transition failed"
      });
    } finally {
      setActionState("idle");
    }
  }

  async function revealHealthDetails() {
    if (!selected || !selected.healthAlert) return;
    try {
      const payload = await adminApi<{ participants?: Array<{ nickname: string; details: string }> }>(
        user,
        `/bookings/${encodeURIComponent(selected.bookingId)}/health`
      );
      setHealthDetails(payload.participants ?? []);
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "เปิดข้อมูลสุขภาพไม่สำเร็จ" : "Health information unavailable", message: caught instanceof Error ? caught.message : undefined });
    }
  }

  async function recordCashPayment() {
    if (!selected || !paymentOptions?.eligible || paymentLoadState === "saving") return;
    const grossAmount = paymentOptions.serviceAmountSatang + cashTipSatang;
    const confirmation = await requestConfirmation({
      title: locale === "th" ? "ยืนยันรับเงินสด?" : "Confirm cash receipt?",
      message: locale === "th"
        ? `${selected.bookingId} ยอด ${formatBaht(grossAmount, locale)} ระบบจะบันทึก Audit และส่งเข้าคิวบัญชี`
        : `${selected.bookingId}, ${formatBaht(grossAmount, locale)}. This creates an audit record and accounting export.`,
      confirmLabel: locale === "th" ? "ยืนยันรับเงินสด" : "Record cash",
      cancelLabel: locale === "th" ? "กลับ" : "Go back",
    });
    if (!confirmation.confirmed) return;
    setPaymentLoadState("saving");
    try {
      await adminApi(user, `/bookings/${encodeURIComponent(selected.bookingId)}/payments:record-cash`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          tipAmountSatang: cashTipSatang,
          expectedVersion: paymentOptions.version,
          confirmed: true,
        }),
      });
      setPaymentOptions((current) => current ? { ...current, status: "PAID", source: "CASH", eligible: false, reason: "NOTHING_DUE" } : current);
      setLiveBookings((current) => current.map((booking) => booking.bookingId === selected.bookingId
        ? { ...booking, paymentStatus: "PAID", paidAmountSatang: grossAmount }
        : booking));
      setPaymentLoadState("ready");
      notify({
        tone: "success",
        title: locale === "th" ? "รับเงินสดแล้ว • รอนำเข้าบัญชี" : "Cash received • awaiting deposit",
        message: `${selected.bookingId} • ${formatBaht(grossAmount, locale)}`,
      });
    } catch (caught) {
      setPaymentLoadState("error");
      notify({
        tone: "error",
        title: locale === "th" ? "บันทึกรับเงินสดไม่สำเร็จ" : "Cash receipt failed",
        message: caught instanceof Error ? caught.message : undefined,
      });
    }
  }

  const bookings = liveBookings;
  const filtered = bookings;
  const selected = bookings.find((booking) => booking.bookingId === selectedId);
  const pending = bookingSummary.pending;
  const unassigned = bookingSummary.unassigned;

  useEffect(() => {
    if (!selected || selected.status !== "COMPLETED") return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setPaymentLoadState("loading");
      setPaymentOptions(null);
      setCashTipSatang(0);
      adminApi<AdminPaymentOptions>(
        user,
        `/bookings/${encodeURIComponent(selected.bookingId)}/payment-options`,
        { method: "POST" },
      ).then((payload) => {
        if (active) {
          setPaymentOptions(payload);
          setPaymentLoadState("ready");
        }
      }).catch((caught) => {
        if (active) {
          setPaymentLoadState("error");
          notify({
            tone: "error",
            title: locale === "th" ? "โหลดข้อมูลชำระเงินไม่สำเร็จ" : "Payment details unavailable",
            message: caught instanceof Error ? caught.message : undefined,
          });
        }
      });
    });
    return () => { active = false; };
  }, [locale, notify, selected, user]);

  const text = locale === "th" ? {
    title: "คิวการจอง",
    subtitle: "เรียงจากรายการใหม่ไปเก่า เพื่อให้เห็นงานล่าสุดก่อน",
    search: "ค้นหา Booking ID ชื่อ หรือเบอร์โทร",
    branch: "SPA 49 • สาขาหลัก",
    pending: "รอยืนยัน",
    unassigned: "ยังไม่มอบหมายหมอนวด",
    notification: "การแจ้งเตือนที่ต้องตรวจสอบ",
    all: "ทั้งหมด",
    time: "วันและเวลา",
    customer: "ลูกค้า",
    service: "บริการ",
    pax: "จำนวน",
    therapist: "หมอนวด",
    status: "สถานะ",
    detail: "รายละเอียดการจอง",
    health: "มีข้อมูลสุขภาพให้ตรวจสอบในระบบ Admin",
    confirm: "ยืนยันการจอง",
    cancel: "ยกเลิก"
  } : {
    title: "Booking queue",
    subtitle: "Newest bookings first, so recent work stays visible",
    search: "Search booking ID, name, or phone",
    branch: "SPA 49 • Main branch",
    pending: "Pending review",
    unassigned: "Therapist unassigned",
    notification: "Notifications requiring review",
    all: "All",
    time: "Date and time",
    customer: "Customer",
    service: "Service",
    pax: "Pax",
    therapist: "Therapist",
    status: "Status",
    detail: "Booking detail",
    health: "Health information requires review in Admin",
    confirm: "Confirm booking",
    cancel: "Cancel"
  };

  return (
    <div className={selected && ["bookings", "calendar"].includes(activeView) ? "admin-layout drawer-open" : "admin-layout"}>
      <aside className={sidebarOpen ? "sidebar open" : "sidebar"}>
        <div className="admin-brand"><div><strong>SPA 49</strong><small>BRANCH OPERATIONS</small></div></div>
        <div className="branch-chip"><span className="live-dot" />{text.branch}</div>
        <nav aria-label="Main navigation">
          {navItems.map(([id, icon, th, en]) => {
            const label = locale === "th" ? th : en;
            const isNotifications = id === "notifications";
            const ariaLabel = isNotifications && notificationFailures > 0
              ? `${label}: ${notificationFailures} ${locale === "th" ? "รายการต้องตรวจสอบ" : "items require review"}`
              : label;
            return <button className={activeView === id ? "nav-item active" : "nav-item"} aria-current={activeView === id ? "page" : undefined} aria-label={ariaLabel} title={ariaLabel} onClick={() => { setActiveView(id); if (isNotifications) setNotificationFilter("ALL"); setSelectedId(""); setQuery(""); setSidebarOpen(false); }} key={id}><span className="nav-icon" aria-hidden="true">{icon}</span>{label}{isNotifications && notificationFailures > 0 && <span className="nav-badge" aria-hidden="true">{notificationFailures > 99 ? "99+" : notificationFailures}</span>}</button>;
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="avatar">พ</div><div><strong>คุณภา</strong><small>ADMIN</small></div>
        </div>
      </aside>

      <div className="admin-main">
        <header className="topbar">
          <button className="menu-button" aria-label="Toggle navigation" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen((value) => !value)}>☰</button>
          {activeView === "bookings" ? <label className="global-search"><span aria-hidden="true">⌕</span><input aria-label={text.search} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={text.search} /></label> : <div className="topbar-context"><span>{locale === "th" ? "พื้นที่ทำงาน" : "Workspace"}</span><strong>{locale === "th" ? navItems.find(([id]) => id === activeView)?.[2] : navItems.find(([id]) => id === activeView)?.[3]}</strong></div>}
          <div className="admin-language" role="group" aria-label="Language"><button aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button><button aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button></div>
          <button className="notification-button" aria-label={`${locale === "th" ? "การแจ้งเตือนที่ต้องตรวจสอบ" : "Notifications requiring review"}: ${notificationFailures}`} onClick={() => { setActiveView("notifications"); setNotificationFilter("ACTION_REQUIRED"); setSelectedId(""); setQuery(""); }}>
            <svg aria-hidden="true" viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></svg>
            {notificationFailures > 0 && <span className="topbar-notification-badge" aria-hidden="true">{notificationFailures > 99 ? "99+" : notificationFailures}</span>}
          </button>
        </header>

        {activeView === "bookings" ? <main className="dashboard-content">
          <div className="page-heading"><div><p className="eyebrow">FRONT DESK • ASIA/BANGKOK</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><button className="new-booking" type="button" onClick={() => { setSelectedId(""); setWalkInOpen(true); }}>{locale === "th" ? "+ สร้าง Booking" : "+ Create booking"}</button></div>

          {bookingState === "error" && <div className="module-state error" role="alert">{locale === "th" ? "โหลดรายการจองไม่สำเร็จ กรุณาลองเข้าสู่ระบบใหม่หรือตรวจสอบสิทธิ์" : "Bookings could not be loaded. Sign in again or check your permissions."}</div>}

          <section className="queue-summary" aria-label="Operational queue summary">
            <div className="queue-item warning"><span>{text.pending}</span><strong>{pending}</strong></div>
            <div className="queue-item info"><span>{text.unassigned}</span><strong>{unassigned}</strong></div>
            <button className="queue-item danger" onClick={() => { setActiveView("notifications"); setNotificationFilter("ACTION_REQUIRED"); }}><span>{text.notification}</span><strong>{notificationFailures}</strong></button>
          </section>

          <section className="operations-panel" aria-labelledby="bookings-table-title">
            <div className="table-toolbar"><div><h2 id="bookings-table-title">{locale === "th" ? "คิวการจอง" : "Booking queue"}</h2><p>{filtered.length} {locale === "th" ? `รายการในหน้านี้ • หน้า ${pageNumber} • ใหม่ไปเก่า` : `records on this page • Page ${pageNumber} • Newest first`}</p></div><div className="filter-pills" role="group" aria-label="Status filter"><button aria-pressed={filter === "ALL"} onClick={() => changeBookingFilter("ALL")}>{text.all}</button><button aria-pressed={filter === "PENDING"} onClick={() => changeBookingFilter("PENDING")}>{statusLabel.PENDING[locale]}</button><button aria-pressed={filter === "CONFIRMED"} onClick={() => changeBookingFilter("CONFIRMED")}>{statusLabel.CONFIRMED[locale]}</button><button aria-pressed={filter === "IN_SERVICE"} onClick={() => changeBookingFilter("IN_SERVICE")}>{statusLabel.IN_SERVICE[locale]}</button></div></div>
            <div className="table-scroll" aria-busy={bookingState === "loading"}>
              <table>
                <thead><tr><th>{text.time}</th><th>{text.customer}</th><th>{text.service}</th><th>{text.pax}</th><th>{text.therapist}</th><th>{text.status}</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {filtered.map((booking) => <tr key={booking.bookingId} className={selectedId === booking.bookingId ? "selected-row" : undefined}>
                    <td><strong className="date-cell">{formatDate(booking.startLocal, locale)}</strong><span className="time-cell">{formatTime(booking.startLocal)}</span><small>{booking.bookingId}</small></td>
                    <td><strong>{booking.customerName}</strong><small>{booking.customerPhoneMasked || (locale === "th" ? "ไม่มีเบอร์ติดต่อ" : "No contact phone")}</small>{booking.source === "ADMIN_WEB" && <span className="walk-in-source">{adminEntryLabel(booking, locale)}</span>}{booking.healthAlert && <span className="health-alert">⚠ {locale === "th" ? "ตรวจสุขภาพ" : "Health review"}</span>}</td>
                    <td>{formatServiceName(booking, locale)}</td><td>{booking.pax}</td><td>{booking.adminEntryMode === "HISTORICAL_RECORD" ? <span className="not-applicable">{locale === "th" ? "ไม่เกี่ยวข้อง" : "Not applicable"}</span> : booking.therapistName ?? <span className="unassigned">{locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned"}</span>}</td><td><span className={`status status-${booking.status.toLowerCase()}`}>{statusLabel[booking.status][locale]}</span></td><td><button className="row-action" onClick={() => setSelectedId(booking.bookingId)} aria-label={`${text.detail} ${booking.bookingId}`}>→</button></td>
                  </tr>)}
                </tbody>
              </table>
            </div>
            {bookingState === "ready" && filtered.length === 0 && <div className="empty-state">{locale === "th" ? "ไม่พบรายการที่ตรงกับตัวกรอง" : "No bookings match these filters"}</div>}
            <nav className="booking-pagination" aria-label={locale === "th" ? "เปลี่ยนหน้ารายการจอง" : "Booking list pagination"}>
              <p role="status" aria-live="polite">{bookingState === "loading" ? (locale === "th" ? "กำลังโหลดรายการ…" : "Loading bookings…") : (locale === "th" ? `หน้า ${pageNumber}` : `Page ${pageNumber}`)}</p>
              <label><span>{locale === "th" ? "แสดงต่อหน้า" : "Per page"}</span><select value={pageSize} disabled={bookingState === "loading"} onChange={(event) => { setPageSize(Number(event.target.value)); resetPagination(); }}>{BOOKING_PAGE_SIZES.map((size) => <option value={size} key={size}>{size}</option>)}</select></label>
              <div>
                <button type="button" disabled={previousPageTokens.length === 0 || bookingState === "loading"} onClick={goToPreviousPage}>← {locale === "th" ? "ก่อนหน้า" : "Previous"}</button>
                <button type="button" disabled={!nextPageToken || bookingState === "loading"} onClick={goToNextPage}>{locale === "th" ? "ถัดไป" : "Next"} →</button>
              </div>
            </nav>
          </section>
        </main> : <AdminModulePage view={activeView} locale={locale} user={user} bookings={bookings} notificationFilter={notificationFilter} onNotificationFilterChange={setNotificationFilter} onNotificationCountChange={setNotificationFailures} onBookingsChanged={() => setBookingRefresh((value) => value + 1)} onSelectBooking={(bookingId) => { setSelectedId(bookingId); setHealthDetails(null); }} onOpenWalkIn={() => { setSelectedId(""); setWalkInOpen(true); }} />}
      </div>

      {selected && <aside ref={detailDrawerRef} className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title">
        <div className="drawer-header"><div><p className="eyebrow">{selected.bookingId}</p><h2 id="detail-title">{text.detail}</h2></div><button ref={closeDrawerButtonRef} aria-label={locale === "th" ? "ปิดรายละเอียด" : "Close detail"} onClick={() => { setSelectedId(""); setHealthDetails(null); }}>×</button></div>
        <div className="drawer-customer"><div className="customer-avatar">{selected.customerName.slice(-1)}</div><div><strong>{selected.customerName}</strong><p>{selected.customerPhoneMasked || (locale === "th" ? "ไม่มีเบอร์ติดต่อ" : "No contact phone")}</p>{selected.source === "ADMIN_WEB" && <span className="walk-in-source">{adminEntryLabel(selected, locale)}</span>}</div></div>
        {selected.healthAlert && <div className="drawer-health" role="alert">⚠ {text.health}<small>{locale === "th" ? "รายละเอียดจะแสดงเฉพาะผู้ดูแลที่มีสิทธิ์" : "Details are restricted to authorized operators"}</small><button type="button" onClick={revealHealthDetails}>{locale === "th" ? "เปิดดูข้อมูลสุขภาพ" : "Reveal health information"}</button>{healthDetails?.map((item, index) => <p key={index}><strong>{item.nickname}</strong>: {item.details}</p>)}</div>}
        <dl>
          <div><dt>{text.time}</dt><dd>{formatDate(selected.startLocal, locale)} • {formatTime(selected.startLocal)}</dd></div>
          <div><dt>{text.service}</dt><dd>{formatServiceName(selected, locale)}</dd></div>
          {selected.adminEntryMode === "HISTORICAL_RECORD" ? <><div><dt>{locale === "th" ? "ราคาปกติ" : "Regular price"}</dt><dd>{formatBaht(selected.subtotalAmountSatang ?? 0, locale)}</dd></div>{!!selected.discountAmountSatang && <div><dt>{locale === "th" ? "ส่วนลด" : "Discount"}</dt><dd>−{formatBaht(selected.discountAmountSatang, locale)}<small>{selected.discountReason}</small></dd></div>}<div><dt>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service amount"}</dt><dd>{formatBaht(selected.estimatedAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ทิป" : "Tip"}</dt><dd>{formatBaht(selected.tipAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ยอดรับรวม" : "Gross recorded total"}</dt><dd><strong>{formatBaht(selected.grossAmountSatang ?? ((selected.estimatedAmountSatang ?? 0) + (selected.tipAmountSatang ?? 0)), locale)}</strong></dd></div></> : !!selected.discountAmountSatang && <><div><dt>{locale === "th" ? "ราคาปกติ" : "Regular price"}</dt><dd>{formatBaht(selected.subtotalAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ส่วนลด" : "Discount"}</dt><dd>−{formatBaht(selected.discountAmountSatang, locale)}<small>{selected.discountReason}</small></dd></div><div><dt>{locale === "th" ? "ยอดสุทธิ" : "Net total"}</dt><dd>{formatBaht(selected.estimatedAmountSatang ?? 0, locale)}</dd></div></>}
          <div><dt>{text.pax}</dt><dd>{selected.pax}</dd></div>
          <div><dt>{text.therapist}</dt><dd>{selected.adminEntryMode === "HISTORICAL_RECORD" ? <span className="not-applicable">{locale === "th" ? "ไม่เกี่ยวข้อง" : "Not applicable"}</span> : selected.therapistName ?? <span className="unassigned">{locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned"}</span>}</dd></div>
          <div><dt>{text.status}</dt><dd><span className={`status status-${selected.status.toLowerCase()}`}>{statusLabel[selected.status][locale]}</span></dd></div>
          {selected.status === "COMPLETED" && <div><dt>{locale === "th" ? "การชำระเงิน" : "Payment"}</dt><dd>{paymentOptions?.status === "PAID" ? (locale === "th" ? "ชำระแล้ว" : "Paid") : (locale === "th" ? "รอชำระ" : "Payment due")}</dd></div>}
        </dl>
        {selected.status === "COMPLETED" && <section className="admin-cash-panel" aria-label={locale === "th" ? "บันทึกรับเงินสด" : "Record cash payment"}>
          <div><p className="eyebrow">PAYMENT</p><h3>{locale === "th" ? "รับเงินสด" : "Cash receipt"}</h3></div>
          {paymentLoadState === "loading" && <p role="status">{locale === "th" ? "กำลังโหลดข้อมูลชำระเงิน…" : "Loading payment details…"}</p>}
          {paymentOptions && <>
            <div className="admin-payment-amount"><span>{locale === "th" ? "ค่าบริการ รวม VAT" : "Service, VAT included"}</span><strong>{formatBaht(paymentOptions.serviceAmountSatang, locale)}</strong></div>
            {paymentOptions.status !== "PAID" && <fieldset disabled={!paymentOptions.eligible || paymentLoadState === "saving"}>
              <legend>{locale === "th" ? "ทิปเพิ่มเติม" : "Add tip"}</legend>
              <div className="admin-tip-options">
                {paymentOptions.tipPresetsSatang.map((tip) => <button type="button" key={tip} aria-pressed={cashTipSatang === tip} onClick={() => setCashTipSatang(tip)}>{tip === 0 ? (locale === "th" ? "ไม่มีทิป" : "No tip") : formatBaht(tip, locale)}</button>)}
                {paymentOptions.customTipMaxSatang !== null && <label><span>{locale === "th" ? "กรอกเอง" : "Custom"}</span><input type="number" min="0" max={paymentOptions.customTipMaxSatang / 100} step="1" inputMode="decimal" onChange={(event) => setCashTipSatang(Math.round(Math.max(0, Number(event.target.value)) * 100))} /></label>}
              </div>
            </fieldset>}
            <div className="admin-payment-total"><span>{locale === "th" ? "ยอดรับเงินสด" : "Cash total"}</span><strong>{formatBaht(paymentOptions.serviceAmountSatang + cashTipSatang, locale)}</strong></div>
            {paymentOptions.status === "PAID" ? <p className="admin-payment-success">✓ {paymentOptions.source === "CASH" ? (locale === "th" ? "รับเงินสดแล้ว • รอนำเข้าบัญชี" : "Cash received • awaiting deposit") : (locale === "th" ? "ชำระผ่าน Beam แล้ว" : "Paid via Beam")}</p> : <button className="confirm-button admin-record-cash" disabled={!paymentOptions.eligible || paymentLoadState === "saving"} onClick={() => { void recordCashPayment(); }}>{paymentLoadState === "saving" ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "ยืนยันรับเงินสด" : "Record cash")}</button>}
            {!paymentOptions.eligible && paymentOptions.status !== "PAID" && <p className="api-gate">{paymentOptions.reason}</p>}
          </>}
        </section>}
        {selected.status === "PENDING" && <div className="drawer-actions"><button className="confirm-button" disabled={actionState === "submitting" || bookingState !== "ready"} onClick={() => transitionBooking("confirm")}>{actionState === "submitting" ? (locale === "th" ? "กำลังบันทึก..." : "Saving...") : text.confirm}</button><button className="cancel-button" disabled={actionState === "submitting" || bookingState !== "ready"} onClick={() => transitionBooking("cancel")}>{text.cancel}</button></div>}
        {selected.status === "CONFIRMED" && <div className="drawer-actions"><button className="confirm-button" disabled={!selected.therapistName || actionState === "submitting"} onClick={() => transitionBooking("start")}>{locale === "th" ? "เริ่มให้บริการ" : "Start service"}</button><button className="cancel-button" disabled={actionState === "submitting"} onClick={() => transitionBooking("cancel")}>{text.cancel}</button><button className="cancel-button" disabled={actionState === "submitting" || currentTime < new Date(selected.startLocal).getTime() + 15 * 60_000} onClick={() => transitionBooking("no_show")}>{locale === "th" ? "ไม่มาตามนัด" : "No show"}</button></div>}
        {selected.status === "IN_SERVICE" && <div className="drawer-actions"><button className="confirm-button" disabled={actionState === "submitting"} onClick={() => transitionBooking("complete")}>{locale === "th" ? "จบบริการ" : "Complete"}</button></div>}
        {selected.status === "RECORDED" && <div className="drawer-actions"><button className="cancel-button" disabled={actionState === "submitting" || bookingState !== "ready"} onClick={() => transitionBooking("cancel")}>{locale === "th" ? "ยกเลิกรายการย้อนหลัง" : "Cancel historical record"}</button></div>}
        {selected.status === "CONFIRMED" && !selected.therapistName && <p className="api-gate">{locale === "th" ? "ต้องมอบหมายหมอนวดให้ผู้รับบริการทุกคนก่อนเริ่มบริการ" : "Assign every guest before starting service."}</p>}
      </aside>}
      {walkInOpen && <WalkInBookingDrawer user={user} locale={locale} onClose={() => setWalkInOpen(false)} onCreated={(bookingId, status) => { setWalkInOpen(false); setBookingRefresh((value) => value + 1); setSelectedId(bookingId); notify({ tone: "success", title: status === "RECORDED" ? (locale === "th" ? "บันทึกรายการย้อนหลังแล้ว" : "Historical record saved") : (locale === "th" ? "สร้างและยืนยัน Booking แล้ว" : "Booking created and confirmed"), message: bookingId }); }} />}
    </div>
  );
}
