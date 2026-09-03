"use client";

import { INITIAL_SERVICE_CATALOG, type BookingStatus, type Locale, type PreviewBooking } from "@spa/shared-types";
import type { User } from "firebase/auth";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { AdminModulePage, type AdminView } from "@/components/admin-module-pages";
import { useAdminFeedback } from "@/components/admin-feedback";
import { AddBookingServiceDialog, type AddBookingServiceInput } from "@/components/add-booking-service-dialog";
import { BookingSettlementDialog } from "@/components/booking-settlement-dialog";
import { BookingDiscountControl, type BookingDiscountUpdate } from "@/components/booking-discount-control";
import { CompleteServiceDialog } from "@/components/complete-service-dialog";
import { StartServiceDialog } from "@/components/start-service-dialog";
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

function googleProfilePhoto(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "lh3.googleusercontent.com" ? url.href : null;
  } catch {
    return null;
  }
}

function accountInitials(displayName: string): string {
  const words = displayName.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "A";
  return words.slice(0, 2).map((word) => Array.from(word)[0]).join("").toUpperCase();
}

const navItems = [
  ["bookings", "▦", "รายการจอง", "Bookings"],
  ["dashboard", "▥", "Dashboard", "Dashboard"],
  ["insight", "◩", "Insight", "Insight"],
  ["calendar", "◫", "ปฏิทิน", "Calendar"],
  ["capacity", "⌁", "สล็อตและความจุ", "Capacity"],
  ["services", "◇", "บริการและราคา", "Services"],
  ["therapists", "♙", "หมอนวด", "Therapists"],
  ["campaign-operations", "◎", "ลูกค้าและแคมเปญ", "CRM & Campaigns"],
  ["accounting", "฿", "การชำระเงินและบัญชี", "Payments & Accounting"],
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

type TherapistOption = {
  therapistId: string;
  displayName: string;
  active: boolean;
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
const SIDEBAR_COLLAPSED_KEY = "spa-admin-sidebar-collapsed";

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

export function AdminDashboard({ user, onSignOut }: { user: User; onSignOut: () => Promise<void> }) {
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
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
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
  const [discountEditing, setDiscountEditing] = useState(false);
  const [walkInOpen, setWalkInOpen] = useState(false);
  const [adminRole, setAdminRole] = useState<"ADMIN" | "STAFF" | null>(null);
  const [settlementBookingId, setSettlementBookingId] = useState("");
  const [startServiceBookingId, setStartServiceBookingId] = useState("");
  const [startServiceError, setStartServiceError] = useState("");
  const [addServiceBookingId, setAddServiceBookingId] = useState("");
  const [addServiceError, setAddServiceError] = useState("");
  const [completeServiceBookingId, setCompleteServiceBookingId] = useState("");
  const [bookingDetail, setBookingDetail] = useState<PreviewBooking | null>(null);
  const [detailLoadState, setDetailLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [therapists, setTherapists] = useState<TherapistOption[]>([]);
  const [assignmentDraft, setAssignmentDraft] = useState<string[]>([]);
  const [assignmentState, setAssignmentState] = useState<"idle" | "saving" | "error">("idle");
  const [assignmentError, setAssignmentError] = useState("");
  const detailDialogRef = useRef<HTMLDivElement>(null);
  const closeDetailButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileSidebarCloseRef = useRef<HTMLButtonElement>(null);
  const mobileSidebarRef = useRef<HTMLElement>(null);

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

  function toggleSidebarCollapsed() {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
  }

  function openMobileSidebar() {
    setMobileSidebarOpen(true);
    window.requestAnimationFrame(() => mobileSidebarCloseRef.current?.focus());
  }

  function closeMobileSidebar(returnFocus = false) {
    setMobileSidebarOpen(false);
    if (returnFocus) window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await onSignOut();
    } catch (caught) {
      setSigningOut(false);
      notify({
        tone: "error",
        title: locale === "th" ? "ออกจากระบบไม่สำเร็จ" : "Could not sign out",
        message: caught instanceof Error ? caught.message : undefined,
      });
    }
  }

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    const savedCollapsed = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    queueMicrotask(() => setSidebarCollapsed(savedCollapsed));
  }, []);

  useEffect(() => {
    if (!mobileSidebarOpen) return;
    const previousOverflow = document.body.style.overflow;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileSidebarOpen(false);
        window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
      }
      if (event.key === "Tab") {
        const focusable = Array.from(mobileSidebarRef.current?.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])") ?? []).filter((element) => element.offsetParent !== null);
        const first = focusable[0];
        const last = focusable.at(-1);
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleEscape);
    };
  }, [mobileSidebarOpen]);

  useEffect(() => {
    let active = true;
    adminApi<{ role: "ADMIN" | "STAFF" }>(user, "/me")
      .then((payload) => { if (active) setAdminRole(payload.role); })
      .catch(() => { if (active) setAdminRole(null); });
    return () => { active = false; };
  }, [user]);

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
    if (!selectedId || !["bookings", "calendar"].includes(activeView)) {
      queueMicrotask(() => {
        setBookingDetail(null);
        setDetailLoadState("idle");
        setAssignmentDraft([]);
        setAssignmentError("");
      });
      return;
    }
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setDetailLoadState("loading");
      setAssignmentState("idle");
      setAssignmentError("");
    });
    Promise.all([
      adminApi<PreviewBooking>(user, `/bookings/${encodeURIComponent(selectedId)}`),
      adminApi<{ items: TherapistOption[] }>(user, "/therapists"),
    ]).then(([detail, roster]) => {
      if (!active) return;
      setBookingDetail(detail);
      setTherapists(roster.items.filter((item) => item.active));
      const participantAssignments = (detail.participants ?? []).map((item) => item.therapistId ?? "");
      setAssignmentDraft(
        participantAssignments.length === detail.pax
          ? participantAssignments
          : Array.from({ length: detail.pax }, (_, index) => detail.therapistIds?.[index] ?? ""),
      );
      setDetailLoadState("ready");
    }).catch((caught) => {
      if (!active) return;
      setDetailLoadState("error");
      setAssignmentError(caught instanceof Error ? caught.message : "Booking detail unavailable");
    });
    return () => { active = false; };
  }, [activeView, bookingRefresh, selectedId, user]);

  useEffect(() => {
    if (!selectedId || !["bookings", "calendar"].includes(activeView)) return;
    if (settlementBookingId) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => closeDetailButtonRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (startServiceBookingId === selectedId || addServiceBookingId === selectedId || completeServiceBookingId === selectedId) return;
      if (event.key === "Escape" && assignmentState !== "saving") {
        setSelectedId("");
        setHealthDetails(null);
        return;
      }
      if (event.key !== "Tab" || !detailDialogRef.current) return;
      const focusable = Array.from(detailDialogRef.current.querySelectorAll<HTMLElement>(
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
      document.body.style.overflow = previousOverflow;
      previousFocusRef.current?.focus();
    };
  }, [selectedId, activeView, assignmentState, settlementBookingId, startServiceBookingId, addServiceBookingId, completeServiceBookingId]);

  async function transitionBooking(action: "confirm" | "cancel" | "no_show" | "complete", alreadyConfirmed = false) {
    const listedBooking = liveBookings.find((item) => item.bookingId === selectedId);
    const booking = listedBooking && bookingDetail?.bookingId === listedBooking.bookingId
      ? { ...listedBooking, ...bookingDetail }
      : listedBooking;
    if (!booking || actionState === "submitting") return;

    const confirmation = alreadyConfirmed
      ? { confirmed: true, inputValue: "" }
      : action === "cancel"
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
      if (action === "complete") setCompleteServiceBookingId("");
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

  async function addBookingService(input: AddBookingServiceInput) {
    const listedBooking = liveBookings.find((item) => item.bookingId === addServiceBookingId);
    const booking = listedBooking && bookingDetail?.bookingId === listedBooking.bookingId
      ? { ...listedBooking, ...bookingDetail }
      : listedBooking;
    if (!booking || booking.status !== "IN_SERVICE" || actionState === "submitting") return;
    setActionState("submitting");
    setAddServiceError("");
    try {
      const payload = await adminApi<{
        version: number;
        subtotalAmountSatang: number;
        discountAmountSatang: number;
        discountReason?: string | null;
        estimatedAmountSatang: number;
        tipAmountSatang: number;
        grossAmountSatang: number;
        endAt: string;
        nextServiceStartLocal: string;
        addedService: NonNullable<PreviewBooking["serviceItems"]>[number];
      }>(user, `/bookings/${encodeURIComponent(booking.bookingId)}/services`, {
        method: "POST",
        body: JSON.stringify({
          ...input,
          expectedVersion: booking.version,
          commandId: crypto.randomUUID(),
        }),
      });
      const update = (item: PreviewBooking): PreviewBooking => ({
        ...item,
        version: payload.version,
        subtotalAmountSatang: payload.subtotalAmountSatang,
        discountAmountSatang: payload.discountAmountSatang,
        discountReason: payload.discountReason ?? undefined,
        estimatedAmountSatang: payload.estimatedAmountSatang,
        tipAmountSatang: payload.tipAmountSatang,
        grossAmountSatang: payload.grossAmountSatang,
        endAt: payload.endAt,
        nextServiceStartLocal: payload.nextServiceStartLocal,
        serviceItems: [...(item.serviceItems ?? []), payload.addedService],
      });
      setLiveBookings((items) => items.map((item) => item.bookingId === booking.bookingId ? update(item) : item));
      setBookingDetail((current) => current?.bookingId === booking.bookingId ? update(current) : current);
      setAddServiceBookingId("");
      notify({
        tone: "success",
        title: locale === "th" ? "เพิ่มบริการใน Booking แล้ว" : "Service added to booking",
        message: `${booking.bookingId} • ${formatBaht(payload.estimatedAmountSatang, locale)}`,
      });
    } catch (caught) {
      setAddServiceError(caught instanceof Error ? caught.message : "Additional service failed");
    } finally {
      setActionState("idle");
    }
  }

  async function startService(
    discountAmountSatang?: number,
    discountReason?: string,
  ) {
    const booking = liveBookings.find((item) => item.bookingId === startServiceBookingId);
    if (!booking || booking.status !== "CONFIRMED" || actionState === "submitting") return;
    setActionState("submitting");
    setStartServiceError("");
    try {
      const payload = await adminApi<{
        status?: BookingStatus;
        version?: number;
        subtotalAmountSatang?: number;
        discountAmountSatang?: number;
        discountReason?: string | null;
        estimatedAmountSatang?: number;
        tipAmountSatang?: number;
        grossAmountSatang?: number;
        detail?: string;
      }>(user, `/bookings/${encodeURIComponent(booking.bookingId)}:start`, {
        method: "POST",
        body: JSON.stringify({
          reason: null,
          expectedVersion: booking.version,
          commandId: crypto.randomUUID(),
          ...(discountAmountSatang === undefined ? {} : {
            discountAmountSatang,
            discountReason: discountReason ?? "",
          }),
        }),
      });
      if (!payload.status) throw new Error(payload.detail ?? "Booking transition failed");
      const update = (item: PreviewBooking): PreviewBooking => ({
        ...item,
        status: payload.status as BookingStatus,
        version: payload.version ?? item.version + 1,
        subtotalAmountSatang: payload.subtotalAmountSatang ?? item.subtotalAmountSatang,
        discountAmountSatang: payload.discountAmountSatang ?? item.discountAmountSatang,
        discountReason: payload.discountReason ?? undefined,
        estimatedAmountSatang: payload.estimatedAmountSatang ?? item.estimatedAmountSatang,
        tipAmountSatang: payload.tipAmountSatang ?? item.tipAmountSatang,
        grossAmountSatang: payload.grossAmountSatang ?? item.grossAmountSatang,
      });
      setLiveBookings((items) => items.map((item) => item.bookingId === booking.bookingId ? update(item) : item));
      setBookingDetail((current) => current?.bookingId === booking.bookingId ? update(current) : current);
      setStartServiceBookingId("");
      setBookingRefresh((value) => value + 1);
      notify({
        tone: "success",
        title: locale === "th" ? "เริ่มให้บริการแล้ว" : "Service started",
        message: `${booking.bookingId} • ${formatBaht(payload.estimatedAmountSatang ?? booking.estimatedAmountSatang ?? 0, locale)}`,
      });
    } catch (caught) {
      setStartServiceError(caught instanceof Error ? caught.message : "Booking transition failed");
    } finally {
      setActionState("idle");
    }
  }

  async function saveTherapistAssignment() {
    if (!selected || assignmentState === "saving") return;
    const complete = assignmentDraft.length === selected.pax && assignmentDraft.every(Boolean);
    const unique = new Set(assignmentDraft).size === assignmentDraft.length;
    if (!complete || !unique) return;
    setAssignmentState("saving");
    setAssignmentError("");
    try {
      const payload = await adminApi<{
        therapistIds: string[];
        therapistName: string;
        version: number;
      }>(user, `/bookings/${encodeURIComponent(selected.bookingId)}/assignments`, {
        method: "PUT",
        body: JSON.stringify({
          therapistIds: assignmentDraft,
          expectedVersion: selected.version,
        }),
      });
      setLiveBookings((items) => items.map((item) => item.bookingId === selected.bookingId
        ? {
            ...item,
            therapistIds: payload.therapistIds,
            therapistName: payload.therapistName,
            version: payload.version,
          }
        : item));
      setBookingDetail((current) => current?.bookingId === selected.bookingId
        ? {
            ...current,
            therapistIds: payload.therapistIds,
            therapistName: payload.therapistName,
            version: payload.version,
            participants: current.participants?.map((participant, index) => ({
              ...participant,
              therapistId: payload.therapistIds[index],
            })),
          }
        : current);
      setAssignmentState("idle");
      notify({
        tone: "success",
        title: locale === "th" ? "บันทึกการมอบหมายหมอแล้ว" : "Therapists assigned",
        message: `${selected.bookingId} • ${payload.therapistName}`,
      });
    } catch (caught) {
      setAssignmentState("error");
      setAssignmentError(caught instanceof Error ? caught.message : "Therapist assignment failed");
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
    if (!selected || !paymentOptions?.eligible || paymentLoadState === "saving" || discountEditing) return;
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
      if (adminRole === "ADMIN") setSettlementBookingId(selected.bookingId);
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

  function applyDiscountUpdate(result: BookingDiscountUpdate) {
    const update = (booking: PreviewBooking): PreviewBooking => ({
      ...booking,
      version: result.bookingVersion,
      subtotalAmountSatang: result.subtotalAmountSatang,
      discountAmountSatang: result.discountAmountSatang,
      discountReason: result.discountReason ?? undefined,
      estimatedAmountSatang: result.serviceAmountSatang,
      tipAmountSatang: result.tipAmountSatang,
      grossAmountSatang: result.grossAmountSatang,
      paymentStatus: result.paymentStatus as PreviewBooking["paymentStatus"],
      paidAmountSatang: 0,
    });
    setLiveBookings((items) => items.map((booking) => booking.bookingId === result.bookingId ? update(booking) : booking));
    setBookingDetail((current) => current?.bookingId === result.bookingId ? update(current) : current);
    setPaymentOptions((current) => current ? {
      ...current,
      status: result.paymentStatus,
      source: null,
      serviceAmountSatang: result.serviceAmountSatang,
      eligible: true,
      reason: null,
      version: result.paymentVersion,
    } : current);
    setPaymentLoadState("ready");
  }

  const bookings = liveBookings;
  const filtered = bookings;
  const selected = bookings.find((booking) => booking.bookingId === selectedId);
  const selectedWithDetail = selected && bookingDetail?.bookingId === selected.bookingId
    ? { ...selected, ...bookingDetail }
    : selected;
  const detailParticipants = bookingDetail?.bookingId === selectedId
    ? bookingDetail.participants ?? []
    : [];
  const assignmentComplete = Boolean(
    selected
    && assignmentDraft.length === selected.pax
    && assignmentDraft.every(Boolean)
    && new Set(assignmentDraft).size === assignmentDraft.length
  );
  const savedAssignments = detailParticipants.map((item) => item.therapistId ?? "");
  const assignmentChanged = assignmentDraft.some(
    (therapistId, index) => therapistId !== (savedAssignments[index] ?? ""),
  );
  const pending = bookingSummary.pending;
  const unassigned = bookingSummary.unassigned;

  useEffect(() => {
    if (!selected || selected.status !== "COMPLETED" || adminRole !== "ADMIN") return;
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
  }, [adminRole, locale, notify, selected, user]);

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

  const accountName = user.displayName?.trim() || user.email?.split("@")[0] || (locale === "th" ? "ผู้ดูแลระบบ" : "Administrator");
  const accountEmail = user.email ?? (locale === "th" ? "บัญชี Google" : "Google account");
  const profilePhoto = googleProfilePhoto(user.photoURL);
  const layoutClassName = `admin-layout${sidebarCollapsed ? " sidebar-collapsed" : ""}`;

  return (
    <div className={layoutClassName}>
      <button className={mobileSidebarOpen ? "sidebar-scrim is-visible" : "sidebar-scrim"} type="button" aria-label={locale === "th" ? "ปิดเมนู" : "Close navigation"} tabIndex={mobileSidebarOpen ? 0 : -1} onClick={() => closeMobileSidebar(true)} />
      <aside ref={mobileSidebarRef} id="admin-sidebar" className={mobileSidebarOpen ? "sidebar open" : "sidebar"} role={mobileSidebarOpen ? "dialog" : undefined} aria-modal={mobileSidebarOpen ? "true" : undefined} aria-label={locale === "th" ? "เมนูผู้ดูแล" : "Admin navigation"}>
        <div className="admin-brand">
          <div className="admin-brand-copy"><strong>SPA 49</strong><small>BRANCH OPERATIONS</small></div>
          <span className="admin-brand-compact" aria-hidden="true">49</span>
          <button className="sidebar-collapse-button" type="button" aria-label={locale === "th" ? sidebarCollapsed ? "ขยายเมนู" : "ย่อเมนู" : sidebarCollapsed ? "Expand navigation" : "Collapse navigation"} aria-expanded={!sidebarCollapsed} aria-controls="admin-sidebar" title={locale === "th" ? sidebarCollapsed ? "ขยายเมนู" : "ย่อเมนู" : sidebarCollapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleSidebarCollapsed}>
            <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
          </button>
          <button ref={mobileSidebarCloseRef} className="sidebar-mobile-close" type="button" aria-label={locale === "th" ? "ปิดเมนู" : "Close navigation"} onClick={() => closeMobileSidebar(true)}>×</button>
        </div>
        <div className="branch-chip" title={text.branch}><span className="live-dot" />{text.branch}</div>
        <nav aria-label={locale === "th" ? "เมนูหลัก" : "Main navigation"}>
          {navItems.filter(([id]) => !["dashboard", "insight"].includes(id) || adminRole === "ADMIN").map(([id, icon, th, en]) => {
            const label = locale === "th" ? th : en;
            const isNotifications = id === "notifications";
            const ariaLabel = isNotifications && notificationFailures > 0
              ? `${label}: ${notificationFailures} ${locale === "th" ? "รายการต้องตรวจสอบ" : "items require review"}`
              : label;
            return <button className={activeView === id ? "nav-item active" : "nav-item"} aria-current={activeView === id ? "page" : undefined} aria-label={ariaLabel} title={ariaLabel} onClick={() => { setActiveView(id); if (isNotifications) setNotificationFilter("ALL"); setSelectedId(""); setQuery(""); closeMobileSidebar(); }} key={id}><span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-label">{label}</span>{isNotifications && notificationFailures > 0 && <span className="nav-badge" aria-hidden="true">{notificationFailures > 99 ? "99+" : notificationFailures}</span>}</button>;
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-account">
            <div className="avatar" aria-hidden="true">{profilePhoto ? <Image src={profilePhoto} alt="" width={38} height={38} referrerPolicy="no-referrer" /> : <span>{accountInitials(accountName)}</span>}</div>
            <div className="sidebar-account-copy"><strong title={accountName}>{accountName}</strong><small title={accountEmail}>{accountEmail}</small><span>{adminRole ?? "—"}</span></div>
          </div>
          <button className="sidebar-signout" type="button" disabled={signingOut} aria-label={locale === "th" ? "ออกจากระบบ" : "Sign out"} title={locale === "th" ? "ออกจากระบบ" : "Sign out"} onClick={() => { void handleSignOut(); }}>
            <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/></svg>
            <span>{signingOut ? (locale === "th" ? "กำลังออก…" : "Signing out…") : (locale === "th" ? "ออกจากระบบ" : "Sign out")}</span>
          </button>
        </div>
      </aside>

      <div className="admin-main">
        <header className="topbar">
          <button ref={mobileMenuButtonRef} className="menu-button" type="button" aria-label={locale === "th" ? "เปิดเมนู" : "Open navigation"} aria-expanded={mobileSidebarOpen} aria-controls="admin-sidebar" onClick={openMobileSidebar}>☰</button>
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

      {selected && !settlementBookingId && <div className="modal-backdrop booking-detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && assignmentState !== "saving") { setSelectedId(""); setHealthDetails(null); } }}>
        <div ref={detailDialogRef} className="booking-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="detail-title" aria-describedby="detail-description">
          <div className="drawer-header booking-detail-header">
            <div><p className="eyebrow">{selected.bookingId}</p><h2 id="detail-title">{text.detail}</h2><p id="detail-description">{formatDate(selected.startLocal, locale)} • {formatTime(selected.startLocal)}</p></div>
            <div className="booking-detail-header-actions"><span className={`status status-${selected.status.toLowerCase()}`}>{statusLabel[selected.status][locale]}</span><button ref={closeDetailButtonRef} type="button" disabled={assignmentState === "saving"} aria-label={locale === "th" ? "ปิดรายละเอียด" : "Close detail"} onClick={() => { setSelectedId(""); setHealthDetails(null); }}>×</button></div>
          </div>
          <div className="booking-detail-content">
            <section className="booking-detail-primary" aria-label={locale === "th" ? "ข้อมูลการจอง" : "Booking information"}>
              <div className="drawer-customer"><div className="customer-avatar">{selected.customerName.slice(-1)}</div><div><strong>{selected.customerName}</strong><p>{selected.customerPhoneMasked || (locale === "th" ? "ไม่มีเบอร์ติดต่อ" : "No contact phone")}</p>{selected.source === "ADMIN_WEB" && <span className="walk-in-source">{adminEntryLabel(selected, locale)}</span>}</div></div>
              {selected.healthAlert && <div className="drawer-health" role="alert">⚠ {text.health}<small>{locale === "th" ? "รายละเอียดจะแสดงเฉพาะผู้ดูแลที่มีสิทธิ์" : "Details are restricted to authorized operators"}</small><button type="button" onClick={revealHealthDetails}>{locale === "th" ? "เปิดดูข้อมูลสุขภาพ" : "Reveal health information"}</button>{healthDetails?.map((item, index) => <p key={index}><strong>{item.nickname}</strong>: {item.details}</p>)}</div>}
              <dl className="booking-detail-summary">
                <div><dt>{text.time}</dt><dd>{formatDate(selected.startLocal, locale)} • {formatTime(selected.startLocal)}</dd></div>
                <div><dt>{text.service}</dt><dd>{formatServiceName(selected, locale)}</dd></div>
                {selected.adminEntryMode === "HISTORICAL_RECORD" ? <><div><dt>{locale === "th" ? "ราคาปกติ" : "Regular price"}</dt><dd>{formatBaht(selected.subtotalAmountSatang ?? 0, locale)}</dd></div>{!!selected.discountAmountSatang && <div><dt>{locale === "th" ? "ส่วนลด" : "Discount"}</dt><dd>−{formatBaht(selected.discountAmountSatang, locale)}<small>{selected.discountReason}</small></dd></div>}<div><dt>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service amount"}</dt><dd>{formatBaht(selected.estimatedAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ทิป" : "Tip"}</dt><dd>{formatBaht(selected.tipAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ยอดรับรวม" : "Gross recorded total"}</dt><dd><strong>{formatBaht(selected.grossAmountSatang ?? ((selected.estimatedAmountSatang ?? 0) + (selected.tipAmountSatang ?? 0)), locale)}</strong></dd></div></> : !!selected.discountAmountSatang && <><div><dt>{locale === "th" ? "ราคาปกติ" : "Regular price"}</dt><dd>{formatBaht(selected.subtotalAmountSatang ?? 0, locale)}</dd></div><div><dt>{locale === "th" ? "ส่วนลด" : "Discount"}</dt><dd>−{formatBaht(selected.discountAmountSatang, locale)}<small>{selected.discountReason}</small></dd></div><div><dt>{locale === "th" ? "ยอดสุทธิ" : "Net total"}</dt><dd>{formatBaht(selected.estimatedAmountSatang ?? 0, locale)}</dd></div></>}
                <div><dt>{text.pax}</dt><dd>{selected.pax}</dd></div>
                <div><dt>{text.therapist}</dt><dd>{selected.adminEntryMode === "HISTORICAL_RECORD" ? <span className="not-applicable">{locale === "th" ? "ระบุในสรุปรายได้" : "Set in settlement"}</span> : selected.therapistName ?? <span className="unassigned">{locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned"}</span>}</dd></div>
                {selected.status === "COMPLETED" && <div><dt>{locale === "th" ? "การชำระเงิน" : "Payment"}</dt><dd>{paymentOptions?.status === "PAID" ? (locale === "th" ? "ชำระแล้ว" : "Paid") : (locale === "th" ? "รอชำระ" : "Payment due")}</dd></div>}
              </dl>
              {!!selectedWithDetail?.serviceItems?.length && <section className="booking-service-timeline" aria-labelledby="booking-services-title"><div className="booking-operation-heading"><div><p className="eyebrow">SERVICES</p><h3 id="booking-services-title">{locale === "th" ? "บริการทั้งหมดใน Booking" : "All booking services"}</h3></div><span>{selectedWithDetail.serviceItems.length} {locale === "th" ? "รายการ" : "items"}</span></div><ol>{selectedWithDetail.serviceItems.map((item, index) => <li key={item.lineItemId}><span>{index + 1}</span><div><strong>{locale === "th" ? item.serviceNameTh : item.serviceNameEn}</strong><small>{item.participantName} • {item.durationMinutes} {locale === "th" ? "นาที" : "min"}{item.therapistName ? ` • ${item.therapistName}` : ""}</small>{item.source === "ADMIN_ADD_ON" && <em>{locale === "th" ? "เพิ่มระหว่างให้บริการ" : "Added during service"}</em>}</div><strong>{formatBaht(item.lineTotalSatang, locale)}</strong></li>)}</ol></section>}
            </section>
            <aside className="booking-detail-operations" aria-label={locale === "th" ? "การดำเนินการ" : "Booking actions"}>
              {detailLoadState === "loading" && <div className="module-state" role="status">{locale === "th" ? "กำลังโหลดข้อมูลผู้รับบริการ…" : "Loading guest details…"}</div>}
              {detailLoadState === "error" && <div className="drawer-feedback error" role="alert">{assignmentError}</div>}
              {selected.status === "CONFIRMED" && <section className="booking-assignment" aria-labelledby="booking-assignment-title">
                <div className="booking-operation-heading"><div><p className="eyebrow">THERAPIST ASSIGNMENT</p><h3 id="booking-assignment-title">{locale === "th" ? "มอบหมายหมอ" : "Assign therapists"}</h3></div><span>{selected.pax} {locale === "th" ? "ผู้รับบริการ" : "guests"}</span></div>
                <div className="booking-assignment-list">{detailParticipants.map((participant, index) => <label key={participant.participantId}><span><strong>{participant.nickname}</strong><small>{locale === "th" ? participant.serviceNameTh : participant.serviceNameEn}{participant.durationMinutes ? ` • ${participant.durationMinutes} ${locale === "th" ? "นาที" : "min"}` : ""}</small></span><select value={assignmentDraft[index] ?? ""} disabled={assignmentState === "saving"} onChange={(event) => setAssignmentDraft((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))}><option value="">— {locale === "th" ? "เลือกหมอ" : "Select therapist"} —</option>{therapists.map((therapist) => <option value={therapist.therapistId} disabled={assignmentDraft.some((value, itemIndex) => itemIndex !== index && value === therapist.therapistId)} key={therapist.therapistId}>{therapist.displayName}</option>)}</select></label>)}</div>
                {!therapists.length && detailLoadState === "ready" && <p className="assignment-inline-warning" role="alert">{locale === "th" ? "ยังไม่มีหมอที่เปิดใช้งาน กรุณาเพิ่มในหน้าหมอนวด" : "No active therapists. Add one from the Therapists page."}</p>}
                {assignmentError && detailLoadState !== "error" && <p className="assignment-inline-warning" role="alert">{assignmentError}</p>}
                <button type="button" className="primary-compact-button assignment-save" disabled={!assignmentComplete || !assignmentChanged || assignmentState === "saving"} onClick={() => { void saveTherapistAssignment(); }}>{assignmentState === "saving" ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : assignmentChanged ? (locale === "th" ? "บันทึกการมอบหมาย" : "Save assignment") : (locale === "th" ? "มอบหมายแล้ว" : "Assigned")}</button>
              </section>}
              {selected.adminEntryMode === "HISTORICAL_RECORD" && <div className="historical-assignment-note"><strong>{locale === "th" ? "ผู้ให้บริการย้อนหลัง" : "Historical therapist"}</strong><p>{locale === "th" ? "ระบุหมอ ค่าหมอ และส่วนแบ่งทิปในสรุปรายได้ เพื่อให้ข้อมูลเข้า Insight อย่างถูกต้อง" : "Set therapist, pay, and tip share in settlement so Insight remains accurate."}</p></div>}
              {adminRole === "ADMIN" && selected.status === "COMPLETED" && <section className="admin-cash-panel" aria-label={locale === "th" ? "ส่วนลดและการรับชำระเงิน" : "Discount and payment"}>
                <div><p className="eyebrow">PAYMENT</p><h3>{locale === "th" ? "ส่วนลดและชำระเงิน" : "Discount & payment"}</h3></div>
                {paymentLoadState === "loading" && <p role="status">{locale === "th" ? "กำลังโหลดข้อมูลชำระเงิน…" : "Loading payment details…"}</p>}
                {paymentOptions && <>
                  <div className="admin-payment-amount"><span>{locale === "th" ? "ราคาปกติ รวม VAT" : "Regular price, VAT included"}</span><strong>{formatBaht(selected.subtotalAmountSatang ?? paymentOptions.serviceAmountSatang, locale)}</strong></div>
                  <BookingDiscountControl
                    key={`${selected.bookingId}-${selected.version}`}
                    bookingId={selected.bookingId}
                    bookingVersion={selected.version}
                    subtotalAmountSatang={selected.subtotalAmountSatang ?? paymentOptions.serviceAmountSatang}
                    discountAmountSatang={selected.discountAmountSatang ?? 0}
                    discountReason={selected.discountReason}
                    disabled={paymentOptions.status === "PAID" || !paymentOptions.eligible || paymentLoadState === "saving"}
                    locale={locale}
                    user={user}
                    onEditingChange={setDiscountEditing}
                    onSaved={applyDiscountUpdate}
                  />
                  <div className="admin-payment-net"><span>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service"}</span><strong>{formatBaht(paymentOptions.serviceAmountSatang, locale)}</strong></div>
                  {paymentOptions.status !== "PAID" && <fieldset disabled={!paymentOptions.eligible || paymentLoadState === "saving" || discountEditing}><legend>{locale === "th" ? "ทิปเพิ่มเติม" : "Add tip"}</legend><div className="admin-tip-options">{paymentOptions.tipPresetsSatang.map((tip) => <button type="button" key={tip} aria-pressed={cashTipSatang === tip} onClick={() => setCashTipSatang(tip)}>{tip === 0 ? (locale === "th" ? "ไม่มีทิป" : "No tip") : formatBaht(tip, locale)}</button>)}{paymentOptions.customTipMaxSatang !== null && <label><span>{locale === "th" ? "กรอกเอง" : "Custom"}</span><input type="number" min="0" max={paymentOptions.customTipMaxSatang / 100} step="1" inputMode="numeric" onChange={(event) => setCashTipSatang(Math.round(Math.max(0, Number(event.target.value)) * 100))} /></label>}</div></fieldset>}
                  <div className="admin-payment-total"><span>{locale === "th" ? "ยอดรับเงินสด" : "Cash total"}</span><strong>{formatBaht(paymentOptions.serviceAmountSatang + cashTipSatang, locale)}</strong></div>
                  {discountEditing && <p className="admin-payment-edit-note" role="status">{locale === "th" ? "บันทึกหรือยกเลิกการแก้ไขส่วนลดก่อนรับชำระเงิน" : "Save or cancel the discount edit before recording payment."}</p>}
                  {paymentOptions.status === "PAID" ? <p className="admin-payment-success">✓ {paymentOptions.source === "CASH" ? (locale === "th" ? "รับเงินสดแล้ว • รอนำเข้าบัญชี" : "Cash received • awaiting deposit") : (locale === "th" ? "ชำระผ่าน Beam แล้ว" : "Paid via Beam")}</p> : <button className="confirm-button admin-record-cash" disabled={!paymentOptions.eligible || paymentLoadState === "saving" || discountEditing} onClick={() => { void recordCashPayment(); }}>{paymentLoadState === "saving" ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "ยืนยันรับเงินสด" : "Record cash")}</button>}
                  {!paymentOptions.eligible && paymentOptions.status !== "PAID" && <p className="api-gate">{paymentOptions.reason}</p>}
                </>}
              </section>}
              {adminRole === "ADMIN" && ["COMPLETED", "RECORDED"].includes(selected.status) && <section className="booking-settlement-entry" aria-label={locale === "th" ? "สรุปรายได้และค่าหมอ" : "Service settlement"}><div><p className="eyebrow">SERVICE SETTLEMENT</p><h3>{locale === "th" ? "ค่าหมอ ทิป และส่วนร้าน" : "Therapist pay, tips & shop share"}</h3><p>{locale === "th" ? "ส่วนลดไม่ลดค่าหมอ และแก้ไขได้โดยมี Audit Trail" : "Promotions do not reduce therapist pay; revisions remain audited."}</p></div><button type="button" className="primary-compact-button" onClick={() => setSettlementBookingId(selected.bookingId)}>{locale === "th" ? "เปิดสรุปรายได้" : "Open settlement"}</button></section>}
            </aside>
          </div>
          <div className="booking-detail-footer">
            <p>{selected.status === "CONFIRMED" && !selected.therapistName ? (locale === "th" ? "มอบหมายหมอให้ครบก่อนเริ่มบริการ" : "Assign every guest before starting service") : ""}</p>
            <div className="drawer-actions">
              {selected.status === "PENDING" && <><button className="cancel-button" disabled={actionState === "submitting" || bookingState !== "ready"} onClick={() => transitionBooking("cancel")}>{text.cancel}</button><button className="confirm-button" disabled={actionState === "submitting" || bookingState !== "ready"} onClick={() => transitionBooking("confirm")}>{actionState === "submitting" ? (locale === "th" ? "กำลังบันทึก..." : "Saving...") : text.confirm}</button></>}
              {selected.status === "CONFIRMED" && <><button className="cancel-button" disabled={actionState === "submitting"} onClick={() => transitionBooking("cancel")}>{text.cancel}</button><button className="cancel-button" disabled={actionState === "submitting" || currentTime < new Date(selected.startLocal).getTime() + 15 * 60_000} onClick={() => transitionBooking("no_show")}>{locale === "th" ? "ไม่มาตามนัด" : "No show"}</button><button className="confirm-button" disabled={!selected.therapistName || !adminRole || actionState === "submitting"} onClick={() => { setStartServiceError(""); setStartServiceBookingId(selected.bookingId); }}>{locale === "th" ? "เริ่มให้บริการ" : "Start service"}</button></>}
              {selected.status === "IN_SERVICE" && <><button className="add-service-button" disabled={actionState === "submitting" || detailLoadState !== "ready"} onClick={() => { setAddServiceError(""); setAddServiceBookingId(selected.bookingId); }}>+ {locale === "th" ? "เพิ่มบริการ" : "Add service"}</button><button className="confirm-button" disabled={actionState === "submitting" || detailLoadState !== "ready"} onClick={() => setCompleteServiceBookingId(selected.bookingId)}>{locale === "th" ? "ตรวจสอบและจบบริการ" : "Review & complete"}</button></>}
              {selected.status === "RECORDED" && <button className="cancel-button" disabled={actionState === "submitting" || bookingState !== "ready"} onClick={() => transitionBooking("cancel")}>{locale === "th" ? "ยกเลิกรายการย้อนหลัง" : "Cancel historical record"}</button>}
            </div>
          </div>
        </div>
      </div>}
      {selected && startServiceBookingId === selected.bookingId && adminRole && <StartServiceDialog
        bookingId={selected.bookingId}
        serviceName={formatServiceName(selected, locale)}
        therapistName={selected.therapistName ?? "—"}
        subtotalAmountSatang={selected.subtotalAmountSatang ?? ((selected.estimatedAmountSatang ?? 0) + (selected.discountAmountSatang ?? 0))}
        discountAmountSatang={selected.discountAmountSatang ?? 0}
        discountReason={selected.discountReason}
        role={adminRole}
        locale={locale}
        submitting={actionState === "submitting"}
        error={startServiceError}
        onClose={() => { if (actionState !== "submitting") { setStartServiceBookingId(""); setStartServiceError(""); } }}
        onConfirm={startService}
      />}
      {selectedWithDetail && addServiceBookingId === selectedWithDetail.bookingId && adminRole && <AddBookingServiceDialog
        booking={selectedWithDetail}
        role={adminRole}
        locale={locale}
        user={user}
        therapists={therapists}
        submitting={actionState === "submitting"}
        error={addServiceError}
        onClose={() => { if (actionState !== "submitting") { setAddServiceBookingId(""); setAddServiceError(""); } }}
        onConfirm={addBookingService}
      />}
      {selectedWithDetail && completeServiceBookingId === selectedWithDetail.bookingId && <CompleteServiceDialog
        booking={selectedWithDetail}
        locale={locale}
        submitting={actionState === "submitting"}
        onClose={() => { if (actionState !== "submitting") setCompleteServiceBookingId(""); }}
        onConfirm={() => transitionBooking("complete", true)}
      />}
      {walkInOpen && <WalkInBookingDrawer user={user} locale={locale} onClose={() => setWalkInOpen(false)} onCreated={(bookingId, status) => { setWalkInOpen(false); setBookingRefresh((value) => value + 1); setSelectedId(bookingId); if (status === "RECORDED" && adminRole === "ADMIN") setSettlementBookingId(bookingId); notify({ tone: "success", title: status === "RECORDED" ? (locale === "th" ? "บันทึกรายการย้อนหลังแล้ว" : "Historical record saved") : (locale === "th" ? "สร้างและยืนยัน Booking แล้ว" : "Booking created and confirmed"), message: bookingId }); }} />}
      {settlementBookingId && <BookingSettlementDialog bookingId={settlementBookingId} locale={locale} user={user} onClose={() => setSettlementBookingId("")} onSaved={() => setBookingRefresh((value) => value + 1)} />}
    </div>
  );
}
