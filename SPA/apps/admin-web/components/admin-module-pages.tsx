"use client";

import type { Locale, PreviewBooking } from "@spa/shared-types";
import { useEffect, useMemo, useState } from "react";

export type AdminView = "calendar" | "capacity" | "services" | "therapists" | "notifications";

type Resource = { resourceId: string; name: string; active: boolean; version: number };
type Closure = { closureId: string; localDate: string; reason: string };
type Variant = { variantId: string; durationMinutes: number; priceSatang: number; active: boolean };
type Service = { serviceId: string; nameTh: string; nameEn: string; active: boolean; version?: number; variants: Variant[] };
type Therapist = { therapistId: string; displayName: string; active: boolean };
type NotificationEvent = { eventId: string; publicBookingId?: string; eventType: string; state: string; attemptCount?: number; lastErrorCode?: string; createdAt?: string };

async function api<T>(path: string, idToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/spa/api/v1/admin${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${idToken}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers
    }
  });
  const payload = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(payload?.detail ?? "Admin API request failed");
  return payload as T;
}

function PageState({ loading, error, empty, locale }: { loading: boolean; error: string; empty: boolean; locale: Locale }) {
  if (loading) return <div className="module-state" role="status">{locale === "th" ? "กำลังโหลดข้อมูลจริง…" : "Loading live data…"}</div>;
  if (error) return <div className="module-state error" role="alert">{error}</div>;
  if (empty) return <div className="module-state">{locale === "th" ? "ยังไม่มีข้อมูล" : "No records yet"}</div>;
  return null;
}

export function AdminModulePage({ view, locale, idToken, bookings, onBookingsChanged }: {
  view: AdminView;
  locale: Locale;
  idToken: string;
  bookings: PreviewBooking[];
  onBookingsChanged: () => void;
}) {
  if (view === "calendar") return <CalendarPage locale={locale} bookings={bookings} />;
  if (view === "capacity") return <CapacityPage locale={locale} idToken={idToken} />;
  if (view === "services") return <ServicesPage locale={locale} idToken={idToken} />;
  if (view === "therapists") return <TherapistsPage locale={locale} idToken={idToken} bookings={bookings} onBookingsChanged={onBookingsChanged} />;
  return <NotificationsPage locale={locale} idToken={idToken} />;
}

function ModuleHeading({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  return <div className="module-heading"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{subtitle}</p></div>;
}

function bangkokDate(value: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Bangkok"
  }).format(new Date(value));
}

function bangkokHour(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit", hour12: false, timeZone: "Asia/Bangkok"
  }).format(new Date(value)).slice(0, 2);
}

function CalendarPage({ locale, bookings }: { locale: Locale; bookings: PreviewBooking[] }) {
  const firstDate = bookings[0] ? bangkokDate(bookings[0].startLocal) : new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" }).format(new Date());
  const [date, setDate] = useState(firstDate);
  const dayBookings = useMemo(() => bookings.filter((item) => bangkokDate(item.startLocal) === date), [bookings, date]);
  return <main className="dashboard-content">
    <ModuleHeading eyebrow="BOOKING CALENDAR • ASIA/BANGKOK" title={locale === "th" ? "ปฏิทินการจอง" : "Booking calendar"} subtitle={locale === "th" ? "ดูตารางการให้บริการตามวันและเวลา" : "Review the daily service schedule"} />
    <section className="module-panel"><div className="module-toolbar"><label>{locale === "th" ? "วันที่" : "Date"}<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><strong>{dayBookings.length} {locale === "th" ? "รายการ" : "bookings"}</strong></div>
      <div className="calendar-grid">{Array.from({ length: 13 }, (_, index) => `${String(index + 10).padStart(2, "0")}:00`).map((time) => {
        const items = dayBookings.filter((item) => bangkokHour(item.startLocal) === time.slice(0, 2));
        return <div className="calendar-row" key={time}><time>{time}</time><div>{items.length ? items.map((item) => <article key={item.bookingId}><strong>{item.customerName}</strong><span>{item.serviceName} • {item.pax} pax</span><small>{item.bookingId} • {item.status}</small></article>) : <span className="calendar-empty">—</span>}</div></div>;
      })}</div>
    </section>
  </main>;
}

function CapacityPage({ locale, idToken }: { locale: Locale; idToken: string }) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [closures, setClosures] = useState<Closure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const load = async () => {
    setLoading(true); setError("");
    try {
      const [resourceData, closureData] = await Promise.all([api<{ items: Resource[] }>("/resources", idToken), api<{ items: Closure[] }>("/closures", idToken)]);
      setResources(resourceData.items); setClosures(closureData.items);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Capacity unavailable"); }
    finally { setLoading(false); }
  };
  // Each module remounts when selected; defer the initial remote sync until after render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [idToken]);
  const toggle = async (item: Resource) => {
    try { await api(`/resources/${item.resourceId}`, idToken, { method: "PATCH", body: JSON.stringify({ active: !item.active, expectedVersion: item.version }) }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Resource update failed"); }
  };
  const createClosure = async () => {
    if (!date || !reason.trim()) return;
    try { await api("/closures", idToken, { method: "POST", body: JSON.stringify({ branchId: "branch_001", localDate: date, reason: reason.trim() }) }); setDate(""); setReason(""); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Closure update failed"); }
  };
  const removeClosure = async (id: string) => { try { await api(`/closures/${id}`, idToken, { method: "DELETE" }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Closure removal failed"); } };
  return <main className="dashboard-content"><ModuleHeading eyebrow="RESOURCE CONTROL" title={locale === "th" ? "สล็อตและความจุ" : "Slots and capacity"} subtitle={locale === "th" ? "เปิดหรือปิดเตียง และกำหนดวันปิดพิเศษ" : "Control beds and special closures"} />
    <PageState loading={loading} error={error} empty={false} locale={locale} />
    {!loading && <><section className="module-panel"><div className="panel-title"><h2>{locale === "th" ? "เตียงให้บริการ" : "Treatment beds"}</h2><strong>{resources.filter((item) => item.active).length}/{resources.length} {locale === "th" ? "เปิดใช้งาน" : "active"}</strong></div><div className="resource-grid">{resources.map((item) => <article key={item.resourceId}><div><strong>{item.name}</strong><small>{item.resourceId}</small></div><button className={item.active ? "toggle active" : "toggle"} aria-pressed={item.active} onClick={() => toggle(item)}>{item.active ? (locale === "th" ? "เปิด" : "Active") : (locale === "th" ? "ปิด" : "Inactive")}</button></article>)}</div></section>
    <section className="module-panel"><div className="panel-title"><h2>{locale === "th" ? "วันปิดพิเศษ" : "Special closures"}</h2></div><div className="inline-form"><label>{locale === "th" ? "วันที่" : "Date"}<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>{locale === "th" ? "เหตุผล" : "Reason"}<input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={300} /></label><button onClick={createClosure} disabled={!date || !reason.trim()}>{locale === "th" ? "เพิ่มวันปิด" : "Add closure"}</button></div><div className="record-list">{closures.map((item) => <article key={item.closureId}><div><strong>{item.localDate}</strong><span>{item.reason}</span></div><button className="danger-link" onClick={() => removeClosure(item.closureId)}>{locale === "th" ? "ลบ" : "Remove"}</button></article>)}</div></section></>}
  </main>;
}

function ServicesPage({ locale, idToken }: { locale: Locale; idToken: string }) {
  const [items, setItems] = useState<Service[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const load = async () => { setLoading(true); setError(""); try { setItems((await api<{ items: Service[] }>("/services", idToken)).items); } catch (caught) { setError(caught instanceof Error ? caught.message : "Services unavailable"); } finally { setLoading(false); } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [idToken]);
  const toggleService = async (service: Service) => { try { await api(`/services/${service.serviceId}`, idToken, { method: "PATCH", body: JSON.stringify({ active: !service.active, expectedVersion: service.version ?? 1 }) }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Service update failed"); } };
  const editPrice = async (service: Service, variant: Variant) => { const baht = window.prompt(locale === "th" ? "ราคาใหม่ (บาท รวม VAT)" : "New VAT-inclusive price (THB)", String(variant.priceSatang / 100)); if (baht === null) return; const value = Number(baht); if (!Number.isFinite(value) || value < 0) { setError(locale === "th" ? "ราคาไม่ถูกต้อง" : "Invalid price"); return; } try { await api(`/services/${service.serviceId}/variants/${variant.variantId}`, idToken, { method: "PATCH", body: JSON.stringify({ priceSatang: Math.round(value * 100), expectedVersion: service.version ?? 1 }) }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Price update failed"); } };
  return <main className="dashboard-content"><ModuleHeading eyebrow="SERVICE CATALOG" title={locale === "th" ? "บริการและราคา" : "Services and prices"} subtitle={locale === "th" ? "ราคาที่แสดงรวม VAT แล้ว การแก้มีผลกับ Booking ใหม่" : "Prices include VAT; changes apply to new bookings"} /><PageState loading={loading} error={error} empty={!items.length} locale={locale} />
    <div className="service-admin-grid">{items.map((service) => <article className="module-panel" key={service.serviceId}><div className="panel-title"><div><h2>{locale === "th" ? service.nameTh : service.nameEn}</h2><small>{service.serviceId}</small></div><button className={service.active ? "toggle active" : "toggle"} onClick={() => toggleService(service)}>{service.active ? (locale === "th" ? "เปิดขาย" : "Active") : (locale === "th" ? "ปิดขาย" : "Inactive")}</button></div><div className="record-list">{service.variants.map((variant) => <article key={variant.variantId}><div><strong>{variant.durationMinutes} min</strong><span>{new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-US", { style: "currency", currency: "THB" }).format(variant.priceSatang / 100)}</span></div><button onClick={() => editPrice(service, variant)}>{locale === "th" ? "แก้ราคา" : "Edit price"}</button></article>)}</div></article>)}</div>
  </main>;
}

function TherapistsPage({ locale, idToken, bookings, onBookingsChanged }: { locale: Locale; idToken: string; bookings: PreviewBooking[]; onBookingsChanged: () => void }) {
  const [items, setItems] = useState<Therapist[]>([]); const [name, setName] = useState(""); const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [selected, setSelected] = useState<Record<string, string>>({});
  const load = async () => { setLoading(true); try { setItems((await api<{ items: Therapist[] }>("/therapists", idToken)).items); } catch (caught) { setError(caught instanceof Error ? caught.message : "Therapists unavailable"); } finally { setLoading(false); } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [idToken]);
  const add = async () => { if (!name.trim()) return; try { await api("/therapists", idToken, { method: "POST", body: JSON.stringify({ branchId: "branch_001", displayName: name.trim() }) }); setName(""); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Therapist creation failed"); } };
  const assign = async (booking: PreviewBooking) => { const therapistId = selected[booking.bookingId]; if (!therapistId) return; try { await api(`/bookings/${booking.bookingId}:assign`, idToken, { method: "POST", body: JSON.stringify({ therapistIds: Array.from({ length: booking.pax }, () => therapistId), expectedVersion: booking.version }) }); onBookingsChanged(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Assignment failed"); } };
  const unassigned = bookings.filter((item) => item.status === "CONFIRMED" && !item.therapistName);
  return <main className="dashboard-content"><ModuleHeading eyebrow="THERAPIST ROSTER" title={locale === "th" ? "หมอนวดและการมอบหมาย" : "Therapists and assignment"} subtitle={locale === "th" ? "ต้องมอบหมายครบก่อนเริ่มให้บริการ" : "Every guest must be assigned before service starts"} /><PageState loading={loading} error={error} empty={false} locale={locale} />
    <section className="module-panel"><div className="panel-title"><h2>{locale === "th" ? "รายชื่อหมอนวด" : "Roster"}</h2><strong>{items.filter((item) => item.active).length} {locale === "th" ? "คนพร้อมใช้งาน" : "active"}</strong></div><div className="inline-form"><label>{locale === "th" ? "ชื่อแสดง" : "Display name"}<input value={name} onChange={(event) => setName(event.target.value)} maxLength={100} /></label><button onClick={add} disabled={!name.trim()}>{locale === "th" ? "เพิ่มหมอนวด" : "Add therapist"}</button></div><div className="resource-grid">{items.map((item) => <article key={item.therapistId}><div><strong>{item.displayName}</strong><small>{item.therapistId}</small></div><span className="state-chip success">{item.active ? (locale === "th" ? "พร้อม" : "Active") : (locale === "th" ? "ปิด" : "Inactive")}</span></article>)}</div></section>
    <section className="module-panel"><div className="panel-title"><h2>{locale === "th" ? "รายการรอมอบหมาย" : "Unassigned bookings"}</h2><strong>{unassigned.length}</strong></div><div className="record-list">{unassigned.map((booking) => <article key={booking.bookingId}><div><strong>{booking.bookingId} • {booking.customerName}</strong><span>{booking.serviceName} • {booking.pax} pax</span></div><div className="row-form"><select aria-label={`${locale === "th" ? "เลือกหมอนวด" : "Select therapist"} ${booking.bookingId}`} value={selected[booking.bookingId] ?? ""} onChange={(event) => setSelected((value) => ({ ...value, [booking.bookingId]: event.target.value }))}><option value="">— {locale === "th" ? "เลือก" : "Select"} —</option>{items.filter((item) => item.active).map((item) => <option value={item.therapistId} key={item.therapistId}>{item.displayName}</option>)}</select><button disabled={!selected[booking.bookingId]} onClick={() => assign(booking)}>{locale === "th" ? "มอบหมาย" : "Assign"}</button></div></article>)}</div>{!unassigned.length && <div className="module-state">{locale === "th" ? "ไม่มีรายการรอมอบหมาย" : "No unassigned bookings"}</div>}</section>
  </main>;
}

function NotificationsPage({ locale, idToken }: { locale: Locale; idToken: string }) {
  const [items, setItems] = useState<NotificationEvent[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const load = async () => { setLoading(true); setError(""); try { setItems((await api<{ items: NotificationEvent[] }>("/notifications", idToken)).items); } catch (caught) { setError(caught instanceof Error ? caught.message : "Notifications unavailable"); } finally { setLoading(false); } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [idToken]);
  const retry = async (id: string) => { try { await api(`/notifications/${id}:retry`, idToken, { method: "POST" }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Retry failed"); } };
  return <main className="dashboard-content"><ModuleHeading eyebrow="DELIVERY OPERATIONS" title={locale === "th" ? "การแจ้งเตือน" : "Notifications"} subtitle={locale === "th" ? "ติดตาม LINE delivery และส่งเข้าคิวใหม่เมื่อจำเป็น" : "Monitor LINE delivery and request safe retries"} /><PageState loading={loading} error={error} empty={!items.length} locale={locale} />
    <section className="module-panel"><div className="record-list notification-list">{items.map((item) => <article key={item.eventId}><div><strong>{item.eventType}</strong><span>{item.publicBookingId ?? item.eventId}</span><small>{locale === "th" ? "พยายามส่ง" : "Attempts"}: {item.attemptCount ?? 0}{item.lastErrorCode ? ` • ${item.lastErrorCode}` : ""}</small></div><div className="row-form"><span className={`state-chip ${item.state === "SENT" ? "success" : item.state === "ENQUEUED" ? "warning" : "danger"}`}>{item.state}</span>{item.state !== "SENT" && <button onClick={() => retry(item.eventId)}>{locale === "th" ? "ส่งเข้าคิวใหม่" : "Retry"}</button>}</div></article>)}</div></section>
  </main>;
}
