"use client";

import type { BookingStatus, Locale } from "@spa/shared-types";
import { useEffect, useMemo, useState } from "react";

import { PREVIEW_BOOKINGS } from "@/lib/preview-data";

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

export function AdminDashboard() {
  const [locale, setLocale] = useState<Locale>("th");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"ALL" | BookingStatus>("ALL");
  const [selectedId, setSelectedId] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const filtered = useMemo(() => PREVIEW_BOOKINGS.filter((booking) => {
    const haystack = `${booking.bookingId} ${booking.customerName} ${booking.customerPhoneMasked}`.toLowerCase();
    return (filter === "ALL" || booking.status === filter) && haystack.includes(query.trim().toLowerCase());
  }), [filter, query]);
  const selected = PREVIEW_BOOKINGS.find((booking) => booking.bookingId === selectedId);
  const pending = PREVIEW_BOOKINGS.filter((booking) => booking.status === "PENDING").length;
  const unassigned = PREVIEW_BOOKINGS.filter((booking) => booking.status === "CONFIRMED" && !booking.therapistName).length;

  const text = locale === "th" ? {
    title: "รายการจองวันนี้",
    subtitle: "ติดตามคำขอที่กัน Capacity แล้วและจัดการงานหน้าร้าน",
    search: "ค้นหา Booking ID ชื่อ หรือเบอร์โทร",
    branch: "SPA 49 • สาขาหลัก",
    pending: "รอยืนยัน",
    unassigned: "ยังไม่มอบหมายหมอนวด",
    notification: "การส่งแจ้งเตือนล้มเหลว",
    preview: "ข้อมูลตัวอย่าง • ยังไม่เชื่อม Firebase หรือ SPA API",
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
    apiGate: "การเปลี่ยนสถานะจะเปิดใช้หลังเชื่อม Firebase Auth และ API"
  } : {
    title: "Today’s bookings",
    subtitle: "Track capacity-holding requests and run front-desk operations",
    search: "Search booking ID, name, or phone",
    branch: "SPA 49 • Main branch",
    pending: "Pending review",
    unassigned: "Therapist unassigned",
    notification: "Notification failures",
    preview: "Preview data • Firebase and the SPA API are not connected",
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
    apiGate: "Status actions will be enabled after Firebase Auth and the API are connected"
  };

  return (
    <div className={selected ? "admin-layout drawer-open" : "admin-layout"}>
      <aside className={sidebarOpen ? "sidebar open" : "sidebar"}>
        <div className="admin-brand"><span aria-hidden="true">✦</span><div><strong>SPA 49</strong><small>BRANCH OPERATIONS</small></div></div>
        <div className="branch-chip"><span className="live-dot" />{text.branch}</div>
        <nav aria-label="Main navigation">
          {navItems.map(([id, icon, th, en], index) => <button className={index === 0 ? "nav-item active" : "nav-item"} key={id}><span aria-hidden="true">{icon}</span>{locale === "th" ? th : en}</button>)}
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
          <button className="notification-button" aria-label="Notifications">♢<span>1</span></button>
        </header>

        <div className="preview-strip" role="status">{text.preview}</div>

        <main className="dashboard-content">
          <div className="page-heading"><div><p className="eyebrow">FRONT DESK • ASIA/BANGKOK</p><h1>{text.title}</h1><p>{text.subtitle}</p></div><button className="new-booking" disabled>＋ {locale === "th" ? "เพิ่มการจอง" : "New booking"}</button></div>

          <section className="metric-grid" aria-label="Operational queue summary">
            <article className="metric warning"><span className="metric-icon">!</span><div><small>{text.pending}</small><strong>{pending}</strong><p>{locale === "th" ? "รายการนี้กัน Capacity แล้ว" : "These bookings hold capacity"}</p></div></article>
            <article className="metric info"><span className="metric-icon">♙</span><div><small>{text.unassigned}</small><strong>{unassigned}</strong><p>{locale === "th" ? "ต้องมอบหมายก่อนเริ่มบริการ" : "Assign before starting service"}</p></div></article>
            <article className="metric danger"><span className="metric-icon">↻</span><div><small>{text.notification}</small><strong>1</strong><p>{locale === "th" ? "ต้องติดตามลูกค้าทางโทรศัพท์" : "Phone follow-up required"}</p></div></article>
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
        </main>
      </div>

      {selected && <aside className="detail-drawer" aria-labelledby="detail-title"><div className="drawer-header"><div><p className="eyebrow">{selected.bookingId}</p><h2 id="detail-title">{text.detail}</h2></div><button aria-label="Close detail" onClick={() => setSelectedId("")}>×</button></div><div className="drawer-customer"><div className="customer-avatar">{selected.customerName.slice(-1)}</div><div><strong>{selected.customerName}</strong><p>{selected.customerPhoneMasked}</p></div></div>{selected.healthAlert && <div className="drawer-health" role="alert">⚠ {text.health}<small>{locale === "th" ? "รายละเอียดไม่แสดงในรายการหรือ LINE Group" : "Details stay out of lists and the LINE group"}</small></div>}<dl><div><dt>{text.time}</dt><dd>{formatTime(selected.startLocal)} น.</dd></div><div><dt>{text.service}</dt><dd>{selected.serviceName}</dd></div><div><dt>{text.pax}</dt><dd>{selected.pax}</dd></div><div><dt>{text.status}</dt><dd><span className={`status status-${selected.status.toLowerCase()}`}>{statusLabel[selected.status][locale]}</span></dd></div></dl><div className="drawer-actions"><button className="confirm-button" disabled>{text.confirm}</button><button className="cancel-button" disabled>{text.cancel}</button></div><p className="api-gate">{text.apiGate}</p></aside>}
    </div>
  );
}
