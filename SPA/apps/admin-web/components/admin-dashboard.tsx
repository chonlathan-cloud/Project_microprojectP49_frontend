"use client";

import type { BookingStatus, Locale, PreviewBooking } from "@spa/shared-types";
import { useEffect, useMemo, useState } from "react";

import { AdminModulePage, type AdminView } from "@/components/admin-module-pages";

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

export function AdminDashboard({ idToken }: { idToken: string }) {
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
    fetch("/api/spa/api/v1/admin/bookings", {
      headers: { Authorization: `Bearer ${idToken}` },
      cache: "no-store"
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Admin booking API unavailable");
        const payload = await response.json() as { items?: PreviewBooking[] };
        setLiveBookings(payload.items ?? []);
        setBookingState("ready");
      })
      .catch(() => {
        setLiveBookings([]);
        setBookingState("error");
      });
  }, [idToken, bookingRefresh]);

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
      const response = await fetch(`/api/spa/api/v1/admin/bookings/${encodeURIComponent(booking.bookingId)}:${action}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${idToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          reason,
          expectedVersion: booking.version,
          commandId: crypto.randomUUID()
        }),
        cache: "no-store"
      });
      const payload = await response.json() as { status?: BookingStatus; version?: number; detail?: string };
      if (!response.ok || !payload.status) {
        throw new Error(payload.detail ?? "Booking transition failed");
      }
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
      const response = await fetch(`/api/spa/api/v1/admin/bookings/${encodeURIComponent(selected.bookingId)}/health`, {
        headers: { Authorization: `Bearer ${idToken}` },
        cache: "no-store"
      });
      if (!response.ok) throw new Error("Health information unavailable");
      const payload = await response.json() as { participants?: Array<{ nickname: string; details: string }> };
      setHealthDetails(payload.participants ?? []);
    } catch (caught) {
      setActionMessage({ kind: "error", text: caught instanceof Error ? caught.message : "Health information unavailable" });
    }
  }

  const bookings = liveBookings;
  const filtered = useMemo(() => bookings.filter((booking) => {
    const haystack = `${booking.bookingId} ${booking.customerName} ${booking.customerPhoneMasked}`.toLowerCase();
    return (filter === "ALL" || booking.status === filter) && haystack.includes(query.trim().toLowerCase());
  }), [bookings, filter, query]);
  const selected = bookings.find((booking) => booking.bookingId === selectedId);
  const pending = bookings.filter((booking) => booking.status === "PENDING").length;
  const unassigned = bookings.filter((booking) => booking.status === "CONFIRMED" && !booking.therapistName).length;

  const text = locale === "th" ? {
    title: "รายการจองวันนี้",
    subtitle: "ติดตามคำขอที่กัน Capacity แล้วและจัดการงานหน้าร้าน",
    search: "ค้นหา Booking ID ชื่อ หรือเบอร์โทร",
    branch: "SPA 49 • สาขาหลัก",
    pending: "รอยืนยัน",
    unassigned: "ยังไม่มอบหมายหมอนวด",
    notification: "การส่งแจ้งเตือนล้มเหลว",
    preview: connection === "checking" || bookingState === "loading"
      ? "กำลังตรวจสอบการเชื่อมต่อ SPA API และ Firestore..."
      : connection === "connected" && bookingState === "ready"
        ? `เชื่อมต่อ SPA API และ Firestore แล้ว • ข้อมูลจริง ${liveBookings.length} รายการ`
        : "โหลดข้อมูลการจองจริงไม่สำเร็จ • กรุณาเข้าสู่ระบบใหม่หรือตรวจสอบสิทธิ์",
    all: "ทั้งหมด",
    time: "เวลา",
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
    title: "Today’s bookings",
    subtitle: "Track capacity-holding requests and run front-desk operations",
    search: "Search booking ID, name, or phone",
    branch: "SPA 49 • Main branch",
    pending: "Pending review",
    unassigned: "Therapist unassigned",
    notification: "Notification failures",
    preview: connection === "checking" || bookingState === "loading"
      ? "Checking SPA API and Firestore connection..."
      : connection === "connected" && bookingState === "ready"
        ? `SPA API and Firestore connected • ${liveBookings.length} live records`
        : "Live bookings could not be loaded • Sign in again or check account permissions",
    all: "All",
    time: "Time",
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
    <div className={selected && activeView === "bookings" ? "admin-layout drawer-open" : "admin-layout"}>
      <aside className={sidebarOpen ? "sidebar open" : "sidebar"}>
        <div className="admin-brand"><span aria-hidden="true">✦</span><div><strong>SPA 49</strong><small>BRANCH OPERATIONS</small></div></div>
        <div className="branch-chip"><span className="live-dot" />{text.branch}</div>
        <nav aria-label="Main navigation">
          {navItems.map(([id, icon, th, en]) => <button className={activeView === id ? "nav-item active" : "nav-item"} aria-current={activeView === id ? "page" : undefined} onClick={() => { setActiveView(id); setSelectedId(""); setSidebarOpen(false); }} key={id}><span aria-hidden="true">{icon}</span>{locale === "th" ? th : en}</button>)}
        </nav>
        <div className="sidebar-footer">
          <div className="avatar">พ</div><div><strong>คุณภา</strong><small>ADMIN</small></div>
        </div>
      </aside>

      <div className="admin-main">
        <header className="topbar">
          <button className="menu-button" aria-label="Toggle navigation" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen((value) => !value)}>☰</button>
          <label className="global-search"><span aria-hidden="true">⌕</span><input aria-label={text.search} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={text.search} /></label>
          <div className="admin-language" role="group" aria-label="Language"><button aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button><button aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button></div>
          <button className="notification-button" aria-label="Notifications" onClick={() => { setActiveView("notifications"); setSelectedId(""); }}>♢<span>!</span></button>
        </header>

        <div className="preview-strip" role="status">{text.preview}</div>

        {activeView === "bookings" ? <main className="dashboard-content">
          <div className="page-heading"><div><p className="eyebrow">FRONT DESK • ASIA/BANGKOK</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><button className="new-booking" disabled>＋ {locale === "th" ? "เพิ่มการจอง" : "New booking"}</button></div>

          <section className="metric-grid" aria-label="Operational queue summary">
            <article className="metric warning"><span className="metric-icon">!</span><div><small>{text.pending}</small><strong>{pending}</strong><p>{locale === "th" ? "รายการนี้กัน Capacity แล้ว" : "These bookings hold capacity"}</p></div></article>
            <article className="metric info"><span className="metric-icon">♙</span><div><small>{text.unassigned}</small><strong>{unassigned}</strong><p>{locale === "th" ? "ต้องมอบหมายก่อนเริ่มบริการ" : "Assign before starting service"}</p></div></article>
            <article className="metric danger"><span className="metric-icon">↻</span><div><small>{text.notification}</small><strong>0</strong><p>{locale === "th" ? "ไม่มีรายการล้มเหลวที่ตรวจพบ" : "No detected delivery failures"}</p></div></article>
          </section>

          <section className="operations-panel" aria-labelledby="bookings-table-title">
            <div className="table-toolbar"><div><h2 id="bookings-table-title">{locale === "th" ? "คิวการจอง" : "Booking queue"}</h2><p>{filtered.length} {locale === "th" ? "รายการ" : "records"}</p></div><div className="filter-pills" role="group" aria-label="Status filter"><button aria-pressed={filter === "ALL"} onClick={() => setFilter("ALL")}>{text.all}</button><button aria-pressed={filter === "PENDING"} onClick={() => setFilter("PENDING")}>{statusLabel.PENDING[locale]}</button><button aria-pressed={filter === "CONFIRMED"} onClick={() => setFilter("CONFIRMED")}>{statusLabel.CONFIRMED[locale]}</button><button aria-pressed={filter === "IN_SERVICE"} onClick={() => setFilter("IN_SERVICE")}>{statusLabel.IN_SERVICE[locale]}</button></div></div>
            <div className="table-scroll">
              <table>
                <thead><tr><th>{text.time}</th><th>{text.customer}</th><th>{text.service}</th><th>{text.pax}</th><th>{text.therapist}</th><th>{text.status}</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {filtered.map((booking) => <tr key={booking.bookingId} className={selectedId === booking.bookingId ? "selected-row" : undefined}>
                    <td><strong className="time-cell">{formatTime(booking.startLocal)}</strong><small>{booking.bookingId}</small></td>
                    <td><strong>{booking.customerName}</strong><small>{booking.customerPhoneMasked}</small>{booking.healthAlert && <span className="health-alert">⚠ {locale === "th" ? "ตรวจสุขภาพ" : "Health review"}</span>}</td>
                    <td>{booking.serviceName}</td><td>{booking.pax}</td><td>{booking.therapistName ?? <span className="unassigned">{locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned"}</span>}</td><td><span className={`status status-${booking.status.toLowerCase()}`}>{statusLabel[booking.status][locale]}</span></td><td><button className="row-action" onClick={() => setSelectedId(booking.bookingId)} aria-label={`${text.detail} ${booking.bookingId}`}>→</button></td>
                  </tr>)}
                </tbody>
              </table>
            </div>
            {filtered.length === 0 && <div className="empty-state">{locale === "th" ? "ไม่พบรายการที่ตรงกับตัวกรอง" : "No bookings match these filters"}</div>}
          </section>
        </main> : <AdminModulePage view={activeView} locale={locale} idToken={idToken} bookings={bookings} onBookingsChanged={() => setBookingRefresh((value) => value + 1)} />}
      </div>

      {selected && <aside className="detail-drawer" aria-labelledby="detail-title"><div className="drawer-header"><div><p className="eyebrow">{selected.bookingId}</p><h2 id="detail-title">{text.detail}</h2></div><button aria-label="Close detail" onClick={() => { setSelectedId(""); setHealthDetails(null); }}>×</button></div><div className="drawer-customer"><div className="customer-avatar">{selected.customerName.slice(-1)}</div><div><strong>{selected.customerName}</strong><p>{selected.customerPhoneMasked}</p></div></div>{selected.healthAlert && <div className="drawer-health" role="alert">⚠ {text.health}<small>{locale === "th" ? "รายละเอียดไม่แสดงในรายการหรือ LINE Group" : "Details stay out of lists and the LINE group"}</small><button type="button" onClick={revealHealthDetails}>{locale === "th" ? "เปิดดูข้อมูลสุขภาพ" : "Reveal health information"}</button>{healthDetails?.map((item, index) => <p key={index}><strong>{item.nickname}</strong>: {item.details}</p>)}</div>}<dl><div><dt>{text.time}</dt><dd>{formatTime(selected.startLocal)} น.</dd></div><div><dt>{text.service}</dt><dd>{selected.serviceName}</dd></div><div><dt>{text.pax}</dt><dd>{selected.pax}</dd></div><div><dt>{text.status}</dt><dd><span className={`status status-${selected.status.toLowerCase()}`}>{statusLabel[selected.status][locale]}</span></dd></div></dl><div className="drawer-actions"><button className="confirm-button" disabled={actionState === "submitting" || bookingState !== "ready" || selected.status !== "PENDING"} onClick={() => transitionBooking("confirm")}>{actionState === "submitting" ? (locale === "th" ? "กำลังบันทึก..." : "Saving...") : text.confirm}</button><button className="cancel-button" disabled={actionState === "submitting" || bookingState !== "ready" || !["PENDING", "CONFIRMED"].includes(selected.status)} onClick={() => transitionBooking("cancel")}>{text.cancel}</button>{selected.status === "CONFIRMED" && <button className="confirm-button" disabled={!selected.therapistName} onClick={() => transitionBooking("start")}>{locale === "th" ? "เริ่มให้บริการ" : "Start service"}</button>}{selected.status === "CONFIRMED" && <button className="cancel-button" disabled={currentTime < new Date(selected.startLocal).getTime() + 15 * 60_000} onClick={() => transitionBooking("no_show")}>{locale === "th" ? "ไม่มาตามนัด" : "No show"}</button>}{selected.status === "IN_SERVICE" && <button className="confirm-button" onClick={() => transitionBooking("complete")}>{locale === "th" ? "จบบริการ" : "Complete"}</button>}</div>{selected.status === "CONFIRMED" && !selected.therapistName && <p className="api-gate">{locale === "th" ? "ต้องมอบหมายหมอนวดให้ผู้รับบริการทุกคนก่อนเริ่มบริการ" : "Assign every guest before starting service."}</p>}{actionMessage && <p className={`action-message ${actionMessage.kind}`} role="status">{actionMessage.text}</p>}<p className="api-gate">{text.apiGate}</p></aside>}
    </div>
  );
}
