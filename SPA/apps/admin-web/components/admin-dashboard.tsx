"use client";

import { INITIAL_SERVICE_CATALOG, type BookingStatus, type Locale, type PreviewBooking } from "@spa/shared-types";
import type { User } from "firebase/auth";
import { useEffect, useMemo, useRef, useState } from "react";

import { AdminModulePage, type AdminView } from "@/components/admin-module-pages";
import { adminApi } from "@/lib/admin-api";
import { countNotificationsRequiringAction } from "@/lib/notification-state";

const statusLabel: Record<BookingStatus, { th: string; en: string }> = {
  PENDING: { th: "รอยืนยัน", en: "Pending" },
  CONFIRMED: { th: "ยืนยันแล้ว", en: "Confirmed" },
  IN_SERVICE: { th: "กำลังให้บริการ", en: "In service" },
  COMPLETED: { th: "เสร็จสิ้น", en: "Completed" },
  CANCELLED: { th: "ยกเลิก", en: "Cancelled" },
  NO_SHOW: { th: "ไม่มาตามนัด", en: "No show" }
};

const navItems = [
  ["bookings", "▦", "รายการจอง", "Bookings"],
  ["calendar", "◫", "ปฏิทิน", "Calendar"],
  ["capacity", "⌁", "สล็อตและความจุ", "Capacity"],
  ["services", "◇", "บริการและราคา", "Services"],
  ["therapists", "♙", "หมอนวด", "Therapists"],
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

export function AdminDashboard({ user }: { user: User }) {
  const [activeView, setActiveView] = useState<"bookings" | AdminView>("bookings");
  const [locale, setLocale] = useState<Locale>("th");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"ALL" | BookingStatus>("ALL");
  const [selectedId, setSelectedId] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [connection, setConnection] = useState<"checking" | "connected" | "unavailable">("checking");
  const [liveBookings, setLiveBookings] = useState<PreviewBooking[]>([]);
  const [bookingState, setBookingState] = useState<"loading" | "ready" | "error">("loading");
  const [actionState, setActionState] = useState<"idle" | "submitting">("idle");
  const [actionMessage, setActionMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [healthDetails, setHealthDetails] = useState<Array<{ nickname: string; details: string }> | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [bookingRefresh, setBookingRefresh] = useState(0);
  const [notificationFailures, setNotificationFailures] = useState(0);
  const [notificationFilter, setNotificationFilter] = useState<"ALL" | "ACTION_REQUIRED">("ALL");
  const detailDrawerRef = useRef<HTMLElement>(null);
  const closeDrawerButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    if (bookingState !== "ready") return;
    const bookingId = new URLSearchParams(window.location.search).get("booking");
    if (bookingId && liveBookings.some((booking) => booking.bookingId === bookingId)) {
      queueMicrotask(() => {
        setActiveView("bookings");
        setSelectedId(bookingId);
        setQuery(bookingId);
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
    let active = true;
    fetch("/api/spa/health/ready", { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json() as { status?: string; dependencies?: { firestore?: { status?: string } } };
        if (!active) return;
        setConnection(payload.status === "ready" && payload.dependencies?.firestore?.status === "ready" ? "connected" : "unavailable");
      })
      .catch(() => {
        if (active) setConnection("unavailable");
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const payload = await adminApi<{ items?: PreviewBooking[] }>(user, "/bookings");
        if (!active) return;
        setLiveBookings(payload.items ?? []);
        setBookingState("ready");
      } catch {
        if (!active) return;
        setLiveBookings([]);
        setBookingState("error");
      }
    })();
    return () => { active = false; };
  }, [user, bookingRefresh]);

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

    let reason: string | null = null;
    if (action !== "cancel") {
      const accepted = window.confirm(locale === "th"
        ? `ยืนยันการเปลี่ยนสถานะ ${booking.bookingId} ใช่หรือไม่?`
        : `Confirm the status change for ${booking.bookingId}?`);
      if (!accepted) return;
    } else {
      reason = window.prompt(locale === "th"
        ? `กรุณาระบุเหตุผลในการยกเลิก ${booking.bookingId}`
        : `Enter a cancellation reason for ${booking.bookingId}`)?.trim() ?? null;
      if (!reason) return;
      const accepted = window.confirm(locale === "th"
        ? `ยืนยันการยกเลิก ${booking.bookingId}? การดำเนินการนี้จะคืน Capacity`
        : `Cancel ${booking.bookingId}? This will release its capacity.`);
      if (!accepted) return;
    }

    setActionState("submitting");
    setActionMessage(null);
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
      setActionMessage({
        kind: "success",
        text: locale === "th" ? "อัปเดตสถานะการจองเรียบร้อยแล้ว" : "Booking status updated successfully."
      });
    } catch (caught) {
      setActionMessage({
        kind: "error",
        text: caught instanceof Error ? caught.message : "Booking transition failed"
      });
    } finally {
      setActionState("idle");
    }
  }

  async function revealHealthDetails() {
    if (!selected || !selected.healthAlert) return;
    setActionMessage(null);
    try {
      const payload = await adminApi<{ participants?: Array<{ nickname: string; details: string }> }>(
        user,
        `/bookings/${encodeURIComponent(selected.bookingId)}/health`
      );
      setHealthDetails(payload.participants ?? []);
    } catch (caught) {
      setActionMessage({ kind: "error", text: caught instanceof Error ? caught.message : "Health information unavailable" });
    }
  }

  const bookings = liveBookings;
  const filtered = useMemo(() => [...bookings.filter((booking) => {
    const haystack = `${booking.bookingId} ${booking.customerName} ${booking.customerPhoneMasked}`.toLowerCase();
    return (filter === "ALL" || booking.status === filter) && haystack.includes(query.trim().toLowerCase());
  })].sort((a, b) => new Date(a.startLocal).getTime() - new Date(b.startLocal).getTime()), [bookings, filter, query]);
  const selected = bookings.find((booking) => booking.bookingId === selectedId);
  const pending = bookings.filter((booking) => booking.status === "PENDING").length;
  const unassigned = bookings.filter((booking) => booking.status === "CONFIRMED" && !booking.therapistName).length;

  const text = locale === "th" ? {
    title: "คิวการจอง",
    subtitle: "เรียงตามวันและเวลา เพื่อจัดการงานหน้าร้านได้อย่างถูกต้อง",
    search: "ค้นหา Booking ID ชื่อ หรือเบอร์โทร",
    branch: "SPA 49 • สาขาหลัก",
    pending: "รอยืนยัน",
    unassigned: "ยังไม่มอบหมายหมอนวด",
    notification: "การแจ้งเตือนที่ต้องตรวจสอบ",
    preview: connection === "checking" || bookingState === "loading"
      ? "กำลังตรวจสอบการเชื่อมต่อ SPA API และ Firestore..."
      : connection === "connected" && bookingState === "ready"
        ? `เชื่อมต่อ SPA API และ Firestore แล้ว • ข้อมูลจริง ${liveBookings.length} รายการ`
        : "โหลดข้อมูลการจองจริงไม่สำเร็จ • กรุณาเข้าสู่ระบบใหม่หรือตรวจสอบสิทธิ์",
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
    cancel: "ยกเลิก",
    apiGate: bookingState === "ready" ? "การเปลี่ยนสถานะเชื่อมต่อ Firebase Auth และ API แล้ว" : "การเปลี่ยนสถานะจะเปิดใช้หลังโหลดข้อมูลจริงสำเร็จ"
  } : {
    title: "Booking queue",
    subtitle: "Sorted by date and time for accurate front-desk operations",
    search: "Search booking ID, name, or phone",
    branch: "SPA 49 • Main branch",
    pending: "Pending review",
    unassigned: "Therapist unassigned",
    notification: "Notifications requiring review",
    preview: connection === "checking" || bookingState === "loading"
      ? "Checking SPA API and Firestore connection..."
      : connection === "connected" && bookingState === "ready"
        ? `SPA API and Firestore connected • ${liveBookings.length} live records`
        : "Live bookings could not be loaded • Sign in again or check account permissions",
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
    cancel: "Cancel",
    apiGate: bookingState === "ready" ? "Status actions are connected to Firebase Auth and the API" : "Status actions will be enabled after live data loads"
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

        <div className="preview-strip" role="status">{text.preview}</div>

        {activeView === "bookings" ? <main className="dashboard-content">
          <div className="page-heading"><div><p className="eyebrow">FRONT DESK • ASIA/BANGKOK</p><h1>{text.title}</h1><p>{text.subtitle}</p></div></div>

          <section className="queue-summary" aria-label="Operational queue summary">
            <div className="queue-item warning"><span>{text.pending}</span><strong>{pending}</strong></div>
            <div className="queue-item info"><span>{text.unassigned}</span><strong>{unassigned}</strong></div>
            <button className="queue-item danger" onClick={() => { setActiveView("notifications"); setNotificationFilter("ACTION_REQUIRED"); }}><span>{text.notification}</span><strong>{notificationFailures}</strong></button>
          </section>

          <section className="operations-panel" aria-labelledby="bookings-table-title">
            <div className="table-toolbar"><div><h2 id="bookings-table-title">{locale === "th" ? "คิวการจอง" : "Booking queue"}</h2><p>{filtered.length} {locale === "th" ? "รายการ" : "records"}</p></div><div className="filter-pills" role="group" aria-label="Status filter"><button aria-pressed={filter === "ALL"} onClick={() => setFilter("ALL")}>{text.all}</button><button aria-pressed={filter === "PENDING"} onClick={() => setFilter("PENDING")}>{statusLabel.PENDING[locale]}</button><button aria-pressed={filter === "CONFIRMED"} onClick={() => setFilter("CONFIRMED")}>{statusLabel.CONFIRMED[locale]}</button><button aria-pressed={filter === "IN_SERVICE"} onClick={() => setFilter("IN_SERVICE")}>{statusLabel.IN_SERVICE[locale]}</button></div></div>
            <div className="table-scroll">
              <table>
                <thead><tr><th>{text.time}</th><th>{text.customer}</th><th>{text.service}</th><th>{text.pax}</th><th>{text.therapist}</th><th>{text.status}</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {filtered.map((booking) => <tr key={booking.bookingId} className={selectedId === booking.bookingId ? "selected-row" : undefined}>
                    <td><strong className="date-cell">{formatDate(booking.startLocal, locale)}</strong><span className="time-cell">{formatTime(booking.startLocal)}</span><small>{booking.bookingId}</small></td>
                    <td><strong>{booking.customerName}</strong><small>{booking.customerPhoneMasked}</small>{booking.healthAlert && <span className="health-alert">⚠ {locale === "th" ? "ตรวจสุขภาพ" : "Health review"}</span>}</td>
                    <td>{formatServiceName(booking, locale)}</td><td>{booking.pax}</td><td>{booking.therapistName ?? <span className="unassigned">{locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned"}</span>}</td><td><span className={`status status-${booking.status.toLowerCase()}`}>{statusLabel[booking.status][locale]}</span></td><td><button className="row-action" onClick={() => setSelectedId(booking.bookingId)} aria-label={`${text.detail} ${booking.bookingId}`}>→</button></td>
                  </tr>)}
                </tbody>
              </table>
            </div>
            {filtered.length === 0 && <div className="empty-state">{locale === "th" ? "ไม่พบรายการที่ตรงกับตัวกรอง" : "No bookings match these filters"}</div>}
          </section>
        </main> : <AdminModulePage view={activeView} locale={locale} user={user} bookings={bookings} notificationFilter={notificationFilter} onNotificationFilterChange={setNotificationFilter} onNotificationCountChange={setNotificationFailures} onBookingsChanged={() => setBookingRefresh((value) => value + 1)} onSelectBooking={(bookingId) => { setSelectedId(bookingId); setHealthDetails(null); }} />}
      </div>

      {selected && <aside ref={detailDrawerRef} className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title"><div className="drawer-header"><div><p className="eyebrow">{selected.bookingId}</p><h2 id="detail-title">{text.detail}</h2></div><button ref={closeDrawerButtonRef} aria-label={locale === "th" ? "ปิดรายละเอียด" : "Close detail"} onClick={() => { setSelectedId(""); setHealthDetails(null); }}>×</button></div><div className="drawer-customer"><div className="customer-avatar">{selected.customerName.slice(-1)}</div><div><strong>{selected.customerName}</strong><p>{selected.customerPhoneMasked}</p></div></div>{selected.healthAlert && <div className="drawer-health" role="alert">⚠ {text.health}<small>{locale === "th" ? "รายละเอียดไม่แสดงในรายการหรือ LINE Group" : "Details stay out of lists and the LINE group"}</small><button type="button" onClick={revealHealthDetails}>{locale === "th" ? "เปิดดูข้อมูลสุขภาพ" : "Reveal health information"}</button>{healthDetails?.map((item, index) => <p key={index}><strong>{item.nickname}</strong>: {item.details}</p>)}</div>}<dl><div><dt>{text.time}</dt><dd>{formatDate(selected.startLocal, locale)} • {formatTime(selected.startLocal)}</dd></div><div><dt>{text.service}</dt><dd>{formatServiceName(selected, locale)}</dd></div><div><dt>{text.pax}</dt><dd>{selected.pax}</dd></div><div><dt>{text.therapist}</dt><dd>{selected.therapistName ?? <span className="unassigned">{locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned"}</span>}</dd></div><div><dt>{text.status}</dt><dd><span className={`status status-${selected.status.toLowerCase()}`}>{statusLabel[selected.status][locale]}</span></dd></div></dl><div className="drawer-actions"><button className="confirm-button" disabled={actionState === "submitting" || bookingState !== "ready" || selected.status !== "PENDING"} onClick={() => transitionBooking("confirm")}>{actionState === "submitting" ? (locale === "th" ? "กำลังบันทึก..." : "Saving...") : text.confirm}</button><button className="cancel-button" disabled={actionState === "submitting" || bookingState !== "ready" || !["PENDING", "CONFIRMED"].includes(selected.status)} onClick={() => transitionBooking("cancel")}>{text.cancel}</button>{selected.status === "CONFIRMED" && <button className="confirm-button" disabled={!selected.therapistName} onClick={() => transitionBooking("start")}>{locale === "th" ? "เริ่มให้บริการ" : "Start service"}</button>}{selected.status === "CONFIRMED" && <button className="cancel-button" disabled={currentTime < new Date(selected.startLocal).getTime() + 15 * 60_000} onClick={() => transitionBooking("no_show")}>{locale === "th" ? "ไม่มาตามนัด" : "No show"}</button>}{selected.status === "IN_SERVICE" && <button className="confirm-button" onClick={() => transitionBooking("complete")}>{locale === "th" ? "จบบริการ" : "Complete"}</button>}</div>{selected.status === "CONFIRMED" && !selected.therapistName && <p className="api-gate">{locale === "th" ? "ต้องมอบหมายหมอนวดให้ผู้รับบริการทุกคนก่อนเริ่มบริการ" : "Assign every guest before starting service."}</p>}{actionMessage && <p className={`action-message ${actionMessage.kind}`} role="status">{actionMessage.text}</p>}<p className="api-gate">{text.apiGate}</p></aside>}
    </div>
  );
}
