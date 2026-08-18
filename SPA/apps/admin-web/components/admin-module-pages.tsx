"use client";

import { INITIAL_SERVICE_CATALOG, type BookingStatus, type Locale, type PreviewBooking } from "@spa/shared-types";
import type { User } from "firebase/auth";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";

import { adminApi } from "@/lib/admin-api";
import { countNotificationsRequiringAction, isNotificationState, notificationRequiresAction, type NotificationState } from "@/lib/notification-state";

export type AdminView = "calendar" | "capacity" | "services" | "therapists" | "notifications";

type Resource = { resourceId: string; name: string; active: boolean; version: number };
type Closure = { closureId: string; localDate: string; reason: string };
type Variant = { variantId: string; durationMinutes: number; priceSatang: number; active: boolean };
type ServiceCategory = "SIGNATURE" | "MASSAGE" | "STANDALONE";
type Service = { serviceId: string; category?: ServiceCategory; nameTh: string; nameEn: string; descriptionTh?: string; descriptionEn?: string; active: boolean; version?: number; imageVersion?: string | null; updatedAt?: string; variants: Variant[] };
type NewServiceDraft = { nameTh: string; nameEn: string; descriptionTh: string; descriptionEn: string; category: ServiceCategory; durationMinutes: string; priceBaht: string; packageType: "SINGLE" | "COUPLE" };
type Therapist = { therapistId: string; displayName: string; active: boolean };
type NotificationEvent = { eventId: string; publicBookingId?: string; eventType: string; state: string; attemptCount?: number; lastErrorCode?: string; createdAt?: string };

async function api<T>(user: User, path: string, init?: RequestInit): Promise<T> {
  return adminApi<T>(user, path, {
    ...init,
    cache: "no-store"
  });
}

function PageState({ loading, error, empty, locale }: { loading: boolean; error: string; empty: boolean; locale: Locale }) {
  if (loading) return <div className="module-state" role="status">{locale === "th" ? "กำลังโหลดข้อมูลจริง…" : "Loading live data…"}</div>;
  if (error) return <div className="module-state error" role="alert">{error}</div>;
  if (empty) return <div className="module-state">{locale === "th" ? "ยังไม่มีข้อมูล" : "No records yet"}</div>;
  return null;
}

export function AdminModulePage({ view, locale, user, bookings, notificationFilter, onNotificationFilterChange, onNotificationCountChange, onBookingsChanged, onSelectBooking }: {
  view: AdminView;
  locale: Locale;
  user: User;
  bookings: PreviewBooking[];
  notificationFilter: "ALL" | "ACTION_REQUIRED";
  onNotificationFilterChange: (filter: "ALL" | "ACTION_REQUIRED") => void;
  onNotificationCountChange: (count: number) => void;
  onBookingsChanged: () => void;
  onSelectBooking: (bookingId: string) => void;
}) {
  if (view === "calendar") return <CalendarPage locale={locale} bookings={bookings} onSelectBooking={onSelectBooking} />;
  if (view === "capacity") return <CapacityPage locale={locale} user={user} />;
  if (view === "services") return <ServicesPage locale={locale} user={user} />;
  if (view === "therapists") return <TherapistsPage locale={locale} user={user} bookings={bookings} onBookingsChanged={onBookingsChanged} />;
  return <NotificationsPage locale={locale} user={user} filter={notificationFilter} onFilterChange={onNotificationFilterChange} onActionRequiredCountChange={onNotificationCountChange} />;
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

const calendarStatusLabel: Record<BookingStatus, { th: string; en: string }> = {
  PENDING: { th: "รอยืนยัน", en: "Pending" },
  CONFIRMED: { th: "ยืนยันแล้ว", en: "Confirmed" },
  IN_SERVICE: { th: "กำลังให้บริการ", en: "In service" },
  COMPLETED: { th: "เสร็จสิ้น", en: "Completed" },
  CANCELLED: { th: "ยกเลิก", en: "Cancelled" },
  NO_SHOW: { th: "ไม่มาตามนัด", en: "No show" }
};

function bangkokTime(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Bangkok"
  }).format(new Date(value));
}

function bookingTimeRange(booking: PreviewBooking, locale: Locale): string {
  const endAt = new Date(new Date(booking.startLocal).getTime() + booking.durationMinutes * 60_000).toISOString();
  return `${bangkokTime(booking.startLocal, locale)}–${bangkokTime(endAt, locale)}`;
}

function localizedServiceName(booking: PreviewBooking, locale: Locale): string {
  const localizedSnapshot = locale === "th" ? booking.serviceNameTh : booking.serviceNameEn;
  if (localizedSnapshot) return localizedSnapshot;
  const service = INITIAL_SERVICE_CATALOG.find((item) => booking.serviceName.includes(item.nameEn) || booking.serviceName.includes(item.nameTh));
  if (!service) return booking.serviceName;
  return locale === "th" ? service.nameTh : service.nameEn;
}

function CalendarPage({ locale, bookings, onSelectBooking }: { locale: Locale; bookings: PreviewBooking[]; onSelectBooking: (bookingId: string) => void }) {
  const firstDate = bookings[0] ? bangkokDate(bookings[0].startLocal) : new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok" }).format(new Date());
  const [date, setDate] = useState(firstDate);
  const dayBookings = useMemo(() => bookings.filter((item) => bangkokDate(item.startLocal) === date), [bookings, date]);
  return <main className="dashboard-content">
    <ModuleHeading eyebrow="BOOKING CALENDAR • ASIA/BANGKOK" title={locale === "th" ? "ปฏิทินการจอง" : "Booking calendar"} subtitle={locale === "th" ? "ดูตารางการให้บริการตามวันและเวลา" : "Review the daily service schedule"} />
    <section className="module-panel"><div className="module-toolbar"><label>{locale === "th" ? "วันที่" : "Date"}<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><strong>{dayBookings.length} {locale === "th" ? "รายการ" : "bookings"}</strong></div>
      <div className="calendar-grid">{Array.from({ length: 13 }, (_, index) => `${String(index + 10).padStart(2, "0")}:00`).map((time) => {
        const items = dayBookings.filter((item) => bangkokHour(item.startLocal) === time.slice(0, 2));
        return <div className="calendar-row" key={time}><time>{time}</time><div>{items.length ? items.map((item) => {
          const timeRange = bookingTimeRange(item, locale);
          const serviceName = localizedServiceName(item, locale);
          const status = calendarStatusLabel[item.status][locale];
          const therapist = item.therapistName ?? (locale === "th" ? "ยังไม่มอบหมาย" : "Unassigned");
          return <button type="button" className={`calendar-booking status-${item.status.toLowerCase()}`} key={item.bookingId} onClick={() => onSelectBooking(item.bookingId)} aria-label={`${timeRange} ${item.customerName} ${serviceName} ${status}`}>
            <span className="calendar-booking-top"><time dateTime={item.startLocal}>{timeRange}</time><span className={`status status-${item.status.toLowerCase()}`}>{status}</span></span>
            <strong>{item.customerName}</strong>
            <span className="calendar-service">{serviceName} · {item.durationMinutes} {locale === "th" ? "นาที" : "min"} · {item.pax} {locale === "th" ? "ท่าน" : "pax"}</span>
            <span className={item.therapistName ? "calendar-therapist" : "calendar-therapist unassigned"}>{locale === "th" ? "หมอนวด" : "Therapist"}: {therapist}</span>
            <span className="calendar-booking-footer"><small>{item.bookingId}</small>{item.healthAlert && <span className="calendar-health-alert">⚠ {locale === "th" ? "ตรวจข้อมูลสุขภาพ" : "Health review"}</span>}</span>
          </button>;
        }) : <span className="calendar-empty">—</span>}</div></div>;
      })}</div>
    </section>
  </main>;
}

function CapacityPage({ locale, user }: { locale: Locale; user: User }) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [closures, setClosures] = useState<Closure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const load = async () => {
    setLoading(true); setError("");
    try {
      const [resourceData, closureData] = await Promise.all([api<{ items: Resource[] }>(user, "/resources"), api<{ items: Closure[] }>(user, "/closures")]);
      setResources(resourceData.items); setClosures(closureData.items);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Capacity unavailable"); }
    finally { setLoading(false); }
  };
  // Each module remounts when selected; defer the initial remote sync until after render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [user]);
  const toggle = async (item: Resource) => {
    try { await api(user, `/resources/${item.resourceId}`, { method: "PATCH", body: JSON.stringify({ active: !item.active, expectedVersion: item.version }) }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Resource update failed"); }
  };
  const createClosure = async () => {
    if (!date || !reason.trim()) return;
    try { await api(user, "/closures", { method: "POST", body: JSON.stringify({ branchId: "branch_001", localDate: date, reason: reason.trim() }) }); setDate(""); setReason(""); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Closure update failed"); }
  };
  const removeClosure = async (id: string) => { try { await api(user, `/closures/${id}`, { method: "DELETE" }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Closure removal failed"); } };
  return <main className="dashboard-content"><ModuleHeading eyebrow="RESOURCE CONTROL" title={locale === "th" ? "สล็อตและความจุ" : "Slots and capacity"} subtitle={locale === "th" ? "เปิดหรือปิดเตียง และกำหนดวันปิดพิเศษ" : "Control beds and special closures"} />
    <PageState loading={loading} error={error} empty={false} locale={locale} />
    {!loading && <><section className="module-panel"><div className="panel-title"><h2>{locale === "th" ? "เตียงให้บริการ" : "Treatment beds"}</h2><strong>{resources.filter((item) => item.active).length}/{resources.length} {locale === "th" ? "เปิดใช้งาน" : "active"}</strong></div><div className="resource-grid">{resources.map((item) => <article key={item.resourceId}><div><strong>{item.name}</strong><small>{item.resourceId}</small></div><button className={item.active ? "toggle active" : "toggle"} aria-pressed={item.active} onClick={() => toggle(item)}>{item.active ? (locale === "th" ? "เปิด" : "Active") : (locale === "th" ? "ปิด" : "Inactive")}</button></article>)}</div></section>
    <section className="module-panel"><div className="panel-title"><h2>{locale === "th" ? "วันปิดพิเศษ" : "Special closures"}</h2></div><div className="inline-form"><label>{locale === "th" ? "วันที่" : "Date"}<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>{locale === "th" ? "เหตุผล" : "Reason"}<input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={300} /></label><button onClick={createClosure} disabled={!date || !reason.trim()}>{locale === "th" ? "เพิ่มวันปิด" : "Add closure"}</button></div><div className="record-list">{closures.map((item) => <article key={item.closureId}><div><strong>{item.localDate}</strong><span>{item.reason}</span></div><button className="danger-link" onClick={() => removeClosure(item.closureId)}>{locale === "th" ? "ลบ" : "Remove"}</button></article>)}</div></section></>}
  </main>;
}

function ServicesPage({ locale, user }: { locale: Locale; user: User }) {
  const [items, setItems] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<"ALL" | ServiceCategory>("ALL");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [newService, setNewService] = useState<NewServiceDraft>({ nameTh: "", nameEn: "", descriptionTh: "", descriptionEn: "", category: "MASSAGE", durationMinutes: "60", priceBaht: "", packageType: "SINGLE" });
  const [categoryDraft, setCategoryDraft] = useState<ServiceCategory>("MASSAGE");
  const [descriptionTh, setDescriptionTh] = useState("");
  const [descriptionEn, setDescriptionEn] = useState("");
  const [priceDrafts, setPriceDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [canManageImages, setCanManageImages] = useState(false);
  const [pendingImage, setPendingImage] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState("");
  const [confirmRemoveImage, setConfirmRemoveImage] = useState(false);
  const [confirmRemoveService, setConfirmRemoveService] = useState(false);
  const serviceDrawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const createDrawerRef = useRef<HTMLElement>(null);
  const createCloseButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api<{ items: Service[]; permissions?: { manageServiceImages?: boolean } }>(user, "/services");
      setItems(result.items);
      setCanManageImages(result.permissions?.manageServiceImages === true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Services unavailable");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [user]);
  useEffect(() => () => { if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl); }, [imagePreviewUrl]);
  useEffect(() => {
    if (!selectedId) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const handleDrawerKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedId(null);
        return;
      }
      if (event.key !== "Tab" || !serviceDrawerRef.current) return;
      const focusable = Array.from(serviceDrawerRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href]'
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
    document.addEventListener("keydown", handleDrawerKeys);
    return () => {
      document.removeEventListener("keydown", handleDrawerKeys);
      previousFocusRef.current?.focus();
    };
  }, [selectedId]);
  useEffect(() => {
    if (!isCreating) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    createCloseButtonRef.current?.focus();
    const handleDrawerKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsCreating(false);
        return;
      }
      if (event.key !== "Tab" || !createDrawerRef.current) return;
      const focusable = Array.from(createDrawerRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])'
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
    document.addEventListener("keydown", handleDrawerKeys);
    return () => {
      document.removeEventListener("keydown", handleDrawerKeys);
      previousFocusRef.current?.focus();
    };
  }, [isCreating]);

  const selected = items.find((item) => item.serviceId === selectedId) ?? null;
  const filteredItems = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return items.filter((service) => {
      const matchesCategory = category === "ALL" || service.category === category;
      const matchesQuery = !needle || `${service.serviceId} ${service.nameTh} ${service.nameEn}`.toLocaleLowerCase().includes(needle);
      return matchesCategory && matchesQuery;
    });
  }, [items, query, category]);

  const openEditor = (service: Service) => {
    setSelectedId(service.serviceId);
    setCategoryDraft(service.category ?? "MASSAGE");
    setDescriptionTh(service.descriptionTh ?? "");
    setDescriptionEn(service.descriptionEn ?? "");
    setPriceDrafts(Object.fromEntries(service.variants.map((variant) => [variant.variantId, String(variant.priceSatang / 100)])));
    setPendingImage(null);
    setImagePreviewUrl("");
    setConfirmRemoveImage(false);
    setConfirmRemoveService(false);
    setError("");
    setNotice("");
  };

  const openCreator = () => {
    setSelectedId(null);
    setNewService({ nameTh: "", nameEn: "", descriptionTh: "", descriptionEn: "", category: "MASSAGE", durationMinutes: "60", priceBaht: "", packageType: "SINGLE" });
    setError("");
    setNotice("");
    setIsCreating(true);
  };

  const createService = async () => {
    const durationMinutes = Number(newService.durationMinutes);
    const priceBaht = Number(newService.priceBaht);
    if (!newService.nameTh.trim() || !newService.nameEn.trim()) return;
    if (!Number.isInteger(durationMinutes) || durationMinutes < 15 || durationMinutes > 480 || durationMinutes % 15 !== 0) {
      setError(locale === "th" ? "ระยะเวลาต้องเป็นช่วงละ 15 นาที ระหว่าง 15–480 นาที" : "Duration must be a 15-minute increment between 15 and 480 minutes.");
      return;
    }
    if (!Number.isFinite(priceBaht) || priceBaht < 0) {
      setError(locale === "th" ? "กรุณาระบุราคาเป็นตัวเลขตั้งแต่ 0 บาทขึ้นไป" : "Enter a valid price of THB 0 or more.");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, "/services", {
        method: "POST",
        body: JSON.stringify({
          branchId: "branch_001",
          category: newService.category,
          nameTh: newService.nameTh.trim(),
          nameEn: newService.nameEn.trim(),
          descriptionTh: newService.descriptionTh.trim(),
          descriptionEn: newService.descriptionEn.trim(),
          durationMinutes,
          priceSatang: Math.round(priceBaht * 100),
          pricingMode: newService.packageType === "COUPLE" ? "PER_BOOKING" : "PER_PARTICIPANT",
          requiredPax: newService.packageType === "COUPLE" ? 2 : 1
        })
      });
      setIsCreating(false);
      setNotice(locale === "th" ? "เพิ่มบริการใหม่และเปิดขายแล้ว" : "New service created and published.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Service creation failed");
    } finally {
      setSaving(false);
    }
  };

  const toggleService = async (service: Service) => {
    setError("");
    setNotice("");
    try {
      await api(user, `/services/${service.serviceId}`, { method: "PATCH", body: JSON.stringify({ active: !service.active, expectedVersion: service.version ?? 1 }) });
      setNotice(locale === "th" ? "อัปเดตสถานะขายแล้ว" : "Sales status updated.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Service update failed");
    }
  };

  const saveDescriptions = async (service: Service) => {
    if (!descriptionTh.trim() || !descriptionEn.trim()) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, `/services/${service.serviceId}`, { method: "PATCH", body: JSON.stringify({ descriptionTh: descriptionTh.trim(), descriptionEn: descriptionEn.trim(), expectedVersion: service.version ?? 1 }) });
      setNotice(locale === "th" ? "บันทึกรายละเอียดบริการแล้ว" : "Service descriptions saved.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Description update failed");
    } finally {
      setSaving(false);
    }
  };

  const saveCategory = async (service: Service) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, `/services/${service.serviceId}`, { method: "PATCH", body: JSON.stringify({ category: categoryDraft, expectedVersion: service.version ?? 1 }) });
      setNotice(locale === "th" ? "เปลี่ยนหมวดหมู่บริการแล้ว" : "Service category updated.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Category update failed");
    } finally {
      setSaving(false);
    }
  };

  const removeService = async (service: Service) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, `/services/${service.serviceId}`, { method: "PATCH", body: JSON.stringify({ active: false, expectedVersion: service.version ?? 1 }) });
      setConfirmRemoveService(false);
      setSelectedId(null);
      setNotice(locale === "th" ? "นำบริการออกจากหน้าจองแล้ว สามารถเปิดขายใหม่ได้ภายหลัง" : "Service removed from booking and can be reactivated later.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Service removal failed");
    } finally {
      setSaving(false);
    }
  };

  const savePrice = async (service: Service, variant: Variant) => {
    const value = Number(priceDrafts[variant.variantId]);
    if (!Number.isFinite(value) || value < 0) {
      setError(locale === "th" ? "กรุณาระบุราคาเป็นตัวเลขตั้งแต่ 0 บาทขึ้นไป" : "Enter a valid price of THB 0 or more.");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, `/services/${service.serviceId}/variants/${variant.variantId}`, { method: "PATCH", body: JSON.stringify({ priceSatang: Math.round(value * 100), expectedVersion: service.version ?? 1 }) });
      setNotice(locale === "th" ? `บันทึกราคา ${variant.durationMinutes} นาทีแล้ว` : `${variant.durationMinutes}-minute price saved.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Price update failed");
    } finally {
      setSaving(false);
    }
  };

  const selectImage = (file?: File) => {
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 5 * 1024 * 1024) {
      setError(locale === "th" ? "รองรับ JPG, PNG หรือ WebP ขนาดไม่เกิน 5 MB" : "Use a JPG, PNG, or WebP file up to 5 MB.");
      return;
    }
    setError("");
    setPendingImage(file);
    setImagePreviewUrl(URL.createObjectURL(file));
  };

  const uploadImage = async (service: Service) => {
    if (!pendingImage) return;
    setSaving(true);
    setError("");
    setNotice("");
    const form = new FormData();
    form.set("image", pendingImage);
    form.set("expected_version", String(service.version ?? 1));
    try {
      await api(user, `/services/${service.serviceId}/image`, { method: "PUT", body: form });
      setPendingImage(null);
      setImagePreviewUrl("");
      setNotice(locale === "th" ? "อัปเดตรูปปกแล้ว รูปใหม่จะแสดงบน Customer Web" : "Cover updated for Customer Web.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Image update failed");
    } finally {
      setSaving(false);
    }
  };

  const removeImage = async (service: Service) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, `/services/${service.serviceId}/image`, { method: "DELETE", body: JSON.stringify({ expectedVersion: service.version ?? 1 }) });
      setConfirmRemoveImage(false);
      setNotice(locale === "th" ? "ลบรูปปกแล้ว" : "Cover image removed.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Image removal failed");
    } finally {
      setSaving(false);
    }
  };

  const money = (priceSatang: number) => new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-US", { style: "currency", currency: "THB", maximumFractionDigits: 0 }).format(priceSatang / 100);
  const categoryLabel = (value?: ServiceCategory) => ({ SIGNATURE: locale === "th" ? "แพ็กเกจ" : "Signature", MASSAGE: locale === "th" ? "นวด" : "Massage", STANDALONE: locale === "th" ? "บริการเสริม" : "Add-on" }[value ?? "MASSAGE"]);

  return <main className="dashboard-content service-workspace">
    <ModuleHeading eyebrow="SERVICE CATALOG" title={locale === "th" ? "บริการและราคา" : "Services and prices"} subtitle={locale === "th" ? "จัดการข้อมูลที่แสดงบน Customer Web ราคาทั้งหมดรวม VAT" : "Manage Customer Web content; all prices include VAT"} />
    <PageState loading={loading} error={error} empty={false} locale={locale} />
    {notice && <div className="action-message success service-notice" role="status">{notice}</div>}
    {!loading && <section className="service-list-panel" aria-labelledby="service-list-title">
      <div className="service-list-toolbar">
        <div><h2 id="service-list-title">{locale === "th" ? "รายการบริการ" : "Service catalog"}</h2><p>{filteredItems.length} / {items.length} {locale === "th" ? "บริการ" : "services"}</p></div>
        <div className="service-toolbar-actions"><label className="service-search"><span className="sr-only">{locale === "th" ? "ค้นหาบริการ" : "Search services"}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={locale === "th" ? "ค้นหาชื่อหรือ Service ID" : "Search name or service ID"} /></label><button type="button" className="service-add-button" onClick={openCreator}>+ {locale === "th" ? "เพิ่มบริการ" : "Add service"}</button></div>
      </div>
      <div className="service-category-tabs" role="group" aria-label={locale === "th" ? "กรองตามหมวดหมู่" : "Filter by category"}>
        {(["ALL", "SIGNATURE", "MASSAGE", "STANDALONE"] as const).map((value) => <button key={value} aria-pressed={category === value} onClick={() => setCategory(value)}>{value === "ALL" ? (locale === "th" ? "ทั้งหมด" : "All") : categoryLabel(value)} <span>{value === "ALL" ? items.length : items.filter((item) => item.category === value).length}</span></button>)}
      </div>
      <div className="service-table-scroll">
        <table className="service-table">
          <thead><tr><th>{locale === "th" ? "บริการ" : "Service"}</th><th>{locale === "th" ? "หมวดหมู่" : "Category"}</th><th>{locale === "th" ? "ระยะเวลาและราคา" : "Duration and price"}</th><th>{locale === "th" ? "สถานะขาย" : "Sales status"}</th><th><span className="sr-only">{locale === "th" ? "การทำงาน" : "Actions"}</span></th></tr></thead>
          <tbody>{filteredItems.map((service) => <tr key={service.serviceId} className={selectedId === service.serviceId ? "selected-row" : undefined}>
            <td><div className="service-identity"><div className={service.imageVersion ? "service-thumbnail" : "service-thumbnail empty"}>{service.imageVersion ? <Image src={`/api/spa/api/v1/public/services/${encodeURIComponent(service.serviceId)}/image?v=${encodeURIComponent(service.imageVersion)}`} alt="" fill unoptimized sizes="96px" /> : <span aria-hidden="true">—</span>}</div><div><strong>{service.nameTh}</strong><span>{service.nameEn}</span><small>{service.serviceId}</small></div></div></td>
            <td><span className="category-chip">{categoryLabel(service.category)}</span></td>
            <td><div className="variant-summary">{service.variants.map((variant) => <span key={variant.variantId}><strong>{variant.durationMinutes}</strong> min · {money(variant.priceSatang)}</span>)}</div></td>
            <td><button className={service.active ? "toggle active" : "toggle"} aria-pressed={service.active} onClick={() => { void toggleService(service); }}>{service.active ? (locale === "th" ? "เปิดขาย" : "Active") : (locale === "th" ? "ปิดขาย" : "Inactive")}</button></td>
            <td><button className="service-edit-button" onClick={() => openEditor(service)}>{locale === "th" ? "จัดการ" : "Manage"}<span aria-hidden="true">→</span></button></td>
          </tr>)}</tbody>
        </table>
      </div>
      {!filteredItems.length && <div className="empty-state">{locale === "th" ? "ไม่พบบริการที่ตรงกับตัวกรอง" : "No services match these filters."}</div>}
    </section>}

    {isCreating && <aside ref={createDrawerRef} className="service-drawer" role="dialog" aria-modal="true" aria-labelledby="service-create-title">
      <div className="drawer-header"><div><p className="eyebrow">NEW SERVICE</p><h2 id="service-create-title">{locale === "th" ? "เพิ่มบริการ" : "Add service"}</h2></div><button ref={createCloseButtonRef} aria-label={locale === "th" ? "ปิดแบบฟอร์ม" : "Close form"} onClick={() => setIsCreating(false)}>×</button></div>
      <form className="service-create-form" onSubmit={(event) => { event.preventDefault(); void createService(); }}>
        <div className="service-editor-scroll">
          <section className="service-editor-section"><div className="service-section-heading"><div><h3>{locale === "th" ? "ข้อมูลบริการ" : "Service details"}</h3><p>{locale === "th" ? "ชื่อจะแสดงบน Customer Web ทั้งสองภาษา" : "Names are published to Customer Web in both languages"}</p></div></div><div className="service-field-grid"><label>{locale === "th" ? "ชื่อภาษาไทย" : "Thai name"}<input required maxLength={160} value={newService.nameTh} onChange={(event) => setNewService((current) => ({ ...current, nameTh: event.target.value }))} /></label><label>{locale === "th" ? "ชื่อภาษาอังกฤษ" : "English name"}<input required maxLength={160} value={newService.nameEn} onChange={(event) => setNewService((current) => ({ ...current, nameEn: event.target.value }))} /></label><label>{locale === "th" ? "หมวดหมู่" : "Category"}<select value={newService.category} onChange={(event) => setNewService((current) => ({ ...current, category: event.target.value as ServiceCategory }))}>{(["SIGNATURE", "MASSAGE", "STANDALONE"] as const).map((value) => <option value={value} key={value}>{categoryLabel(value)}</option>)}</select></label></div></section>
          <section className="service-editor-section"><div className="service-section-heading"><div><h3>{locale === "th" ? "รายละเอียดสองภาษา" : "Bilingual descriptions"}</h3><p>{locale === "th" ? "เพิ่มภายหลังก็ได้ แต่ควรกรอกก่อนเผยแพร่" : "Optional now, recommended before publishing"}</p></div></div><div className="service-copy-form"><label>{locale === "th" ? "คำอธิบายภาษาไทย" : "Thai description"}<textarea maxLength={500} rows={4} value={newService.descriptionTh} onChange={(event) => setNewService((current) => ({ ...current, descriptionTh: event.target.value }))} /></label><label>{locale === "th" ? "คำอธิบายภาษาอังกฤษ" : "English description"}<textarea maxLength={500} rows={4} value={newService.descriptionEn} onChange={(event) => setNewService((current) => ({ ...current, descriptionEn: event.target.value }))} /></label></div></section>
          <section className="service-editor-section"><div className="service-section-heading"><div><h3>{locale === "th" ? "ราคาเริ่มต้น" : "Initial price"}</h3><p>{locale === "th" ? "สร้างพร้อมหนึ่งระยะเวลา ราคาเป็นบาทรวม VAT" : "Create with one duration; THB, VAT inclusive"}</p></div></div><div className="service-field-grid two-columns"><label>{locale === "th" ? "ระยะเวลา (นาที)" : "Duration (minutes)"}<input required type="number" min="15" max="480" step="15" value={newService.durationMinutes} onChange={(event) => setNewService((current) => ({ ...current, durationMinutes: event.target.value }))} /></label><label>{locale === "th" ? "ราคา (บาท)" : "Price (THB)"}<input required type="number" min="0" step="1" value={newService.priceBaht} onChange={(event) => setNewService((current) => ({ ...current, priceBaht: event.target.value }))} /></label><label>{locale === "th" ? "รูปแบบบริการ" : "Service type"}<select value={newService.packageType} onChange={(event) => setNewService((current) => ({ ...current, packageType: event.target.value as NewServiceDraft["packageType"] }))}><option value="SINGLE">{locale === "th" ? "ต่อผู้รับบริการ 1 คน" : "Per participant (1 guest)"}</option><option value="COUPLE">{locale === "th" ? "แพ็กเกจคู่ 2 คน" : "Couple package (2 guests)"}</option></select></label></div></section>
        </div>
        {(error || notice) && <div className={`drawer-feedback ${error ? "error" : "success"}`} role={error ? "alert" : "status"}>{error || notice}</div>}
        <div className="service-create-actions"><button type="button" onClick={() => setIsCreating(false)}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button type="submit" className="save-button" disabled={saving || !newService.nameTh.trim() || !newService.nameEn.trim() || !newService.priceBaht}>{saving ? (locale === "th" ? "กำลังเพิ่ม…" : "Creating…") : (locale === "th" ? "เพิ่มและเปิดขาย" : "Create and publish")}</button></div>
      </form>
    </aside>}

    {selected && <aside ref={serviceDrawerRef} className="service-drawer" role="dialog" aria-modal="true" aria-labelledby="service-editor-title">
      <div className="drawer-header"><div><p className="eyebrow">{selected.serviceId}</p><h2 id="service-editor-title">{locale === "th" ? "จัดการบริการ" : "Manage service"}</h2></div><button ref={closeButtonRef} aria-label={locale === "th" ? "ปิดตัวแก้ไข" : "Close editor"} onClick={() => setSelectedId(null)}>×</button></div>
      <div className="service-drawer-title"><div><strong>{selected.nameTh}</strong><span>{selected.nameEn}</span></div><button className={selected.active ? "toggle active" : "toggle"} aria-pressed={selected.active} onClick={() => { void toggleService(selected); }}>{selected.active ? (locale === "th" ? "เปิดขาย" : "Active") : (locale === "th" ? "ปิดขาย" : "Inactive")}</button></div>
      <div className="service-editor-scroll">
        <section className="service-editor-section" aria-labelledby="category-title"><div className="service-section-heading"><div><h3 id="category-title">{locale === "th" ? "หมวดหมู่" : "Category"}</h3><p>{locale === "th" ? "มีผลกับการจัดกลุ่มบน Customer Web" : "Controls grouping on Customer Web"}</p></div></div><div className="service-category-editor"><select aria-label={locale === "th" ? "หมวดหมู่บริการ" : "Service category"} value={categoryDraft} onChange={(event) => setCategoryDraft(event.target.value as ServiceCategory)}>{(["SIGNATURE", "MASSAGE", "STANDALONE"] as const).map((value) => <option value={value} key={value}>{categoryLabel(value)}</option>)}</select><button type="button" disabled={saving || categoryDraft === (selected.category ?? "MASSAGE")} onClick={() => { void saveCategory(selected); }}>{locale === "th" ? "บันทึกหมวดหมู่" : "Save category"}</button></div></section>
        <section className="service-editor-section" aria-labelledby="cover-title"><div className="service-section-heading"><div><h3 id="cover-title">{locale === "th" ? "รูปปก" : "Cover image"}</h3><p>{locale === "th" ? "ตัวอย่างก่อนแสดงบน Customer Web" : "Preview before publishing to Customer Web"}</p></div></div>
          <div className={imagePreviewUrl || selected.imageVersion ? "service-image-preview" : "service-image-preview empty"}>{imagePreviewUrl ? <Image src={imagePreviewUrl} alt={locale === "th" ? "ตัวอย่างรูปปกใหม่" : "New cover preview"} fill unoptimized sizes="420px" /> : selected.imageVersion ? <Image src={`/api/spa/api/v1/public/services/${encodeURIComponent(selected.serviceId)}/image?v=${encodeURIComponent(selected.imageVersion)}`} alt={locale === "th" ? `รูปปก ${selected.nameTh}` : `${selected.nameEn} cover`} fill unoptimized sizes="420px" /> : <span>{locale === "th" ? "ยังไม่มีรูปปก" : "No cover image"}</span>}</div>
          {canManageImages && <div className="service-image-actions"><label className="image-upload-button"><input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" disabled={saving} onChange={(event) => { selectImage(event.target.files?.[0]); event.currentTarget.value = ""; }} /><span>{selected.imageVersion ? (locale === "th" ? "เลือกรูปใหม่" : "Choose replacement") : (locale === "th" ? "เลือกรูป" : "Choose image")}</span></label>{pendingImage && <><button type="button" className="save-button" disabled={saving} onClick={() => { void uploadImage(selected); }}>{saving ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "บันทึกรูป" : "Save image")}</button><button type="button" disabled={saving} onClick={() => { setPendingImage(null); setImagePreviewUrl(""); }}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button></>}{selected.imageVersion && !pendingImage && <button type="button" className="danger-link" disabled={saving} onClick={() => setConfirmRemoveImage(true)}>{locale === "th" ? "ลบรูป" : "Remove"}</button>}<small>{locale === "th" ? "JPG, PNG หรือ WebP · ไม่เกิน 5 MB · ระบบจัดเป็น 4:3" : "JPG, PNG, or WebP · max 5 MB · cropped to 4:3"}</small></div>}
          {confirmRemoveImage && <div className="inline-confirm" role="alertdialog" aria-labelledby="remove-image-title"><strong id="remove-image-title">{locale === "th" ? "ลบรูปปกนี้?" : "Remove this cover?"}</strong><p>{locale === "th" ? "Customer Web จะไม่มีรูปปกสำหรับบริการนี้" : "Customer Web will no longer show a cover for this service."}</p><div><button onClick={() => setConfirmRemoveImage(false)}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button className="danger-button" disabled={saving} onClick={() => { void removeImage(selected); }}>{locale === "th" ? "ยืนยันลบรูป" : "Remove image"}</button></div></div>}
        </section>

        <section className="service-editor-section" aria-labelledby="copy-title"><div className="service-section-heading"><div><h3 id="copy-title">{locale === "th" ? "รายละเอียดสองภาษา" : "Bilingual descriptions"}</h3><p>{locale === "th" ? "ตรวจข้อความก่อนเผยแพร่ทุกครั้ง" : "Review customer-facing copy before saving"}</p></div></div><div className="service-copy-form"><label>{locale === "th" ? "คำอธิบายภาษาไทย" : "Thai description"}<textarea value={descriptionTh} onChange={(event) => setDescriptionTh(event.target.value)} maxLength={500} rows={4} /><small>{descriptionTh.length}/500</small></label><label>{locale === "th" ? "คำอธิบายภาษาอังกฤษ" : "English description"}<textarea value={descriptionEn} onChange={(event) => setDescriptionEn(event.target.value)} maxLength={500} rows={4} /><small>{descriptionEn.length}/500</small></label><div className="service-copy-actions"><button type="button" className="save-button" onClick={() => { void saveDescriptions(selected); }} disabled={saving || !descriptionTh.trim() || !descriptionEn.trim()}>{saving ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "บันทึกรายละเอียด" : "Save descriptions")}</button></div></div></section>

        <section className="service-editor-section" aria-labelledby="price-title"><div className="service-section-heading"><div><h3 id="price-title">{locale === "th" ? "ระยะเวลาและราคา" : "Duration and prices"}</h3><p>{locale === "th" ? "ราคาเป็นบาท รวม VAT และมีผลกับ Booking ใหม่" : "THB, VAT inclusive; applies to new bookings"}</p></div></div><div className="variant-editor-list">{selected.variants.map((variant) => <div className="variant-editor-row" key={variant.variantId}><div><strong>{variant.durationMinutes} {locale === "th" ? "นาที" : "minutes"}</strong><small>{variant.variantId}</small></div><label><span>{locale === "th" ? "ราคา (บาท)" : "Price (THB)"}</span><input type="number" min="0" step="1" inputMode="decimal" value={priceDrafts[variant.variantId] ?? ""} onChange={(event) => setPriceDrafts((current) => ({ ...current, [variant.variantId]: event.target.value }))} /></label><button disabled={saving || Number(priceDrafts[variant.variantId]) === variant.priceSatang / 100} onClick={() => { void savePrice(selected, variant); }}>{locale === "th" ? "บันทึกราคา" : "Save price"}</button></div>)}</div></section>
        <section className="service-editor-section service-danger-zone" aria-labelledby="remove-service-title"><div className="service-section-heading"><div><h3 id="remove-service-title">{locale === "th" ? "นำบริการออก" : "Remove service"}</h3><p>{locale === "th" ? "ปิดบริการแบบย้อนกลับได้ ประวัติ Booking เดิมยังคงอยู่" : "Reversible deactivation; existing booking history is preserved"}</p></div></div>{!confirmRemoveService ? <button type="button" className="danger-link service-remove-button" disabled={saving || !selected.active} onClick={() => setConfirmRemoveService(true)}>{selected.active ? (locale === "th" ? "นำออกจากหน้าจอง" : "Remove from booking") : (locale === "th" ? "บริการนี้ปิดอยู่แล้ว" : "Service already inactive")}</button> : <div className="inline-confirm" role="alertdialog" aria-labelledby="confirm-remove-service-title"><strong id="confirm-remove-service-title">{locale === "th" ? `นำ “${selected.nameTh}” ออกจากหน้าจอง?` : `Remove “${selected.nameEn}” from booking?`}</strong><p>{locale === "th" ? "ลูกค้าจะเลือกบริการนี้ไม่ได้ แต่ Admin สามารถเปิดขายใหม่จากตารางได้" : "Customers cannot select it, but Admin can reactivate it from the table."}</p><div><button type="button" onClick={() => setConfirmRemoveService(false)}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button type="button" className="danger-button" disabled={saving} onClick={() => { void removeService(selected); }}>{locale === "th" ? "ยืนยันนำออก" : "Confirm removal"}</button></div></div>}</section>
      </div>
      {(error || notice) && <div className={`drawer-feedback ${error ? "error" : "success"}`} role={error ? "alert" : "status"}>{error || notice}</div>}
    </aside>}
  </main>;
}

function TherapistsPage({ locale, user, bookings, onBookingsChanged }: { locale: Locale; user: User; bookings: PreviewBooking[]; onBookingsChanged: () => void }) {
  const [items, setItems] = useState<Therapist[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [assignmentDrafts, setAssignmentDrafts] = useState<Record<string, string[]>>({});
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeDialogButtonRef = useRef<HTMLButtonElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const addButtonRef = useRef<HTMLButtonElement>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setItems((await api<{ items: Therapist[] }>(user, "/therapists")).items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Therapists unavailable");
    } finally {
      setLoading(false);
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [user]);
  useEffect(() => {
    if (!registrationOpen) return;
    const trigger = addButtonRef.current;
    nameInputRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setRegistrationOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled])'
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
      trigger?.focus();
    };
  }, [registrationOpen]);

  const openRegistration = () => {
    setName("");
    setDialogError("");
    setRegistrationOpen(true);
  };

  const add = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setDialogError("");
    try {
      await api(user, "/therapists", { method: "POST", body: JSON.stringify({ branchId: "branch_001", displayName: name.trim() }) });
      setRegistrationOpen(false);
      setNotice(locale === "th" ? `ลงทะเบียน ${name.trim()} แล้ว พร้อมรับการมอบหมาย` : `${name.trim()} registered and available for assignment.`);
      setName("");
      await load();
    } catch (caught) {
      setDialogError(caught instanceof Error ? caught.message : "Therapist creation failed");
    } finally {
      setSaving(false);
    }
  };

  const updateAssignment = (bookingId: string, participantIndex: number, therapistId: string) => {
    setAssignmentDrafts((current) => {
      const next = [...(current[bookingId] ?? [])];
      next[participantIndex] = therapistId;
      return { ...current, [bookingId]: next };
    });
  };

  const assign = async (booking: PreviewBooking) => {
    const therapistIds = assignmentDrafts[booking.bookingId] ?? [];
    if (therapistIds.length !== booking.pax || therapistIds.some((item) => !item)) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api(user, `/bookings/${booking.bookingId}/assignments`, { method: "PUT", body: JSON.stringify({ therapistIds, expectedVersion: booking.version }) });
      setAssignmentDrafts((current) => {
        const next = { ...current };
        delete next[booking.bookingId];
        return next;
      });
      setNotice(locale === "th" ? `มอบหมายหมอนวดให้ ${booking.bookingId} แล้ว รายการจองกำลังอัปเดต` : `Therapists assigned to ${booking.bookingId}; the booking list is updating.`);
      onBookingsChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Assignment failed");
    } finally {
      setSaving(false);
    }
  };

  const unassigned = bookings.filter((item) => item.status === "CONFIRMED" && !item.therapistName);
  const activeTherapists = items.filter((item) => item.active);
  const formatBookingDateTime = (value: string) => new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Bangkok" }).format(new Date(value));

  return <main className="dashboard-content therapist-workspace">
    <ModuleHeading eyebrow="THERAPIST ROSTER" title={locale === "th" ? "หมอนวดและการมอบหมาย" : "Therapists and assignment"} subtitle={locale === "th" ? "ลงทะเบียนหมอนวดและมอบหมายให้ครบก่อนเริ่มบริการ" : "Register therapists and assign every guest before service starts"} />
    <PageState loading={loading} error={error} empty={false} locale={locale} />
    {notice && <div className="action-message success therapist-notice" role="status">{notice}</div>}
    {!loading && <div className="therapist-dispatch-grid">
      <section className="module-panel therapist-roster-panel" aria-labelledby="therapist-roster-title">
        <div className="panel-title"><div><h2 id="therapist-roster-title">{locale === "th" ? "รายชื่อหมอนวด" : "Roster"}</h2><small>{activeTherapists.length}/{items.length} {locale === "th" ? "คนพร้อมรับงาน" : "available"}</small></div><button ref={addButtonRef} type="button" className="primary-compact-button" onClick={openRegistration}>+ {locale === "th" ? "เพิ่มหมอนวด" : "Add therapist"}</button></div>
        <div className="therapist-roster-list">{items.map((item) => <article key={item.therapistId}><div className="therapist-avatar" aria-hidden="true">{item.displayName.trim().slice(0, 1)}</div><div><strong>{item.displayName}</strong><small>{item.therapistId}</small></div><span className={`state-chip ${item.active ? "success" : ""}`}>{item.active ? (locale === "th" ? "พร้อม" : "Active") : (locale === "th" ? "ปิด" : "Inactive")}</span></article>)}</div>
        {!items.length && <div className="module-state">{locale === "th" ? "ยังไม่มีหมอนวด กด “เพิ่มหมอนวด” เพื่อเริ่มต้น" : "No therapists yet. Select “Add therapist” to begin."}</div>}
      </section>

      <section className="module-panel assignment-panel" aria-labelledby="assignment-title">
        <div className="panel-title"><div><h2 id="assignment-title">{locale === "th" ? "รายการรอมอบหมาย" : "Unassigned bookings"}</h2><small>{locale === "th" ? "เฉพาะ Booking ที่ยืนยันแล้ว" : "Confirmed bookings only"}</small></div><strong>{unassigned.length}</strong></div>
        <div className="assignment-list">{unassigned.map((booking) => {
          const draft = assignmentDrafts[booking.bookingId] ?? [];
          const assignmentComplete = draft.length === booking.pax && draft.every(Boolean);
          return <article key={booking.bookingId} className="assignment-item"><div className="assignment-booking"><div><strong>{booking.bookingId}</strong><span>{booking.customerName} • {booking.serviceName}</span><time dateTime={booking.startLocal}>{formatBookingDateTime(booking.startLocal)} • {booking.pax} {locale === "th" ? "คน" : "pax"}</time></div></div><div className="assignment-controls"><div className="assignment-selects">{Array.from({ length: booking.pax }, (_, index) => <label key={index}><span>{locale === "th" ? `ผู้รับบริการ ${index + 1}` : `Guest ${index + 1}`}</span><select value={draft[index] ?? ""} onChange={(event) => updateAssignment(booking.bookingId, index, event.target.value)}><option value="">— {locale === "th" ? "เลือกหมอนวด" : "Select therapist"} —</option>{activeTherapists.map((item) => <option value={item.therapistId} key={item.therapistId}>{item.displayName}</option>)}</select></label>)}</div><button type="button" disabled={saving || !assignmentComplete} onClick={() => { void assign(booking); }}>{saving ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "ยืนยันมอบหมาย" : "Confirm assignment")}</button></div></article>;
        })}</div>
        {!unassigned.length && <div className="module-state">{locale === "th" ? "ไม่มีรายการรอมอบหมาย" : "No unassigned bookings"}</div>}
        {!!unassigned.length && !activeTherapists.length && <div className="assignment-warning" role="alert">{locale === "th" ? "ต้องลงทะเบียนหมอนวดที่พร้อมรับงานก่อนจึงจะมอบหมายได้" : "Register an active therapist before assigning bookings."}</div>}
      </section>
    </div>}

    {registrationOpen && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setRegistrationOpen(false); }}><div ref={dialogRef} className="registration-dialog" role="dialog" aria-modal="true" aria-labelledby="therapist-dialog-title" aria-describedby="therapist-dialog-description"><div className="drawer-header"><div><p className="eyebrow">NEW THERAPIST</p><h2 id="therapist-dialog-title">{locale === "th" ? "ลงทะเบียนหมอนวดใหม่" : "Register new therapist"}</h2></div><button ref={closeDialogButtonRef} type="button" aria-label={locale === "th" ? "ปิดหน้าต่าง" : "Close dialog"} onClick={() => setRegistrationOpen(false)}>×</button></div><form onSubmit={(event) => { event.preventDefault(); void add(); }}><p id="therapist-dialog-description">{locale === "th" ? "หมอนวดใหม่จะเปิดใช้งานทันทีและเลือกมอบหมายให้ Booking ได้" : "The new therapist becomes active immediately and can be assigned to bookings."}</p><label htmlFor="therapist-display-name">{locale === "th" ? "ชื่อที่ใช้แสดงในระบบ" : "Display name"}</label><input ref={nameInputRef} id="therapist-display-name" required maxLength={100} autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} placeholder={locale === "th" ? "เช่น คุณนิด" : "e.g. Nid"} />{dialogError && <div className="action-message error" role="alert">{dialogError}</div>}<div className="dialog-actions"><button type="button" onClick={() => setRegistrationOpen(false)}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button type="submit" className="confirm-button" disabled={saving || !name.trim()}>{saving ? (locale === "th" ? "กำลังลงทะเบียน…" : "Registering…") : (locale === "th" ? "ลงทะเบียนหมอนวด" : "Register therapist")}</button></div></form></div></div>}
  </main>;
}

const notificationStateLabel: Record<NotificationState, { th: string; en: string }> = {
  PENDING: { th: "รอสร้างคิว", en: "Pending" },
  ENQUEUED: { th: "เข้าคิวแล้ว", en: "Queued" },
  PROCESSING: { th: "กำลังส่ง", en: "Sending" },
  RETRYABLE: { th: "รอส่งซ้ำ", en: "Awaiting retry" },
  SENT: { th: "ส่งสำเร็จ", en: "Sent" },
  FAILED: { th: "ส่งไม่สำเร็จ", en: "Failed" }
};

function notificationStateTone(state: string): "success" | "warning" | "danger" | "" {
  if (state === "SENT") return "success";
  if (state === "FAILED" || state === "RETRYABLE") return "danger";
  if (state === "PENDING" || state === "ENQUEUED" || state === "PROCESSING") return "warning";
  return "";
}

function formatNotificationState(state: string, locale: Locale): string {
  return isNotificationState(state) ? notificationStateLabel[state][locale] : state;
}

function NotificationsPage({ locale, user, filter, onFilterChange, onActionRequiredCountChange }: { locale: Locale; user: User; filter: "ALL" | "ACTION_REQUIRED"; onFilterChange: (filter: "ALL" | "ACTION_REQUIRED") => void; onActionRequiredCountChange: (count: number) => void }) {
  const [items, setItems] = useState<NotificationEvent[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const load = async () => { setLoading(true); setError(""); try { const nextItems = (await api<{ items: NotificationEvent[] }>(user, "/notifications")).items; setItems(nextItems); onActionRequiredCountChange(countNotificationsRequiringAction(nextItems)); } catch (caught) { setError(caught instanceof Error ? caught.message : "Notifications unavailable"); } finally { setLoading(false); } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { queueMicrotask(() => { void load(); }); }, [user]);
  const retry = async (id: string) => { try { await api(user, `/notifications/${id}:retry`, { method: "POST" }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Retry failed"); } };
  const actionRequiredCount = countNotificationsRequiringAction(items);
  const visibleItems = filter === "ACTION_REQUIRED" ? items.filter((item) => notificationRequiresAction(item.state)) : items;
  return <main className="dashboard-content"><ModuleHeading eyebrow="DELIVERY OPERATIONS" title={locale === "th" ? "การแจ้งเตือน" : "Notifications"} subtitle={locale === "th" ? "ติดตามการส่ง LINE และจัดการเฉพาะรายการที่ต้องตรวจสอบ" : "Monitor LINE delivery and act only on items requiring review"} /><PageState loading={loading} error={error} empty={!items.length} locale={locale} />
    {!loading && items.length > 0 && <div className="notification-filter" role="group" aria-label={locale === "th" ? "ตัวกรองการแจ้งเตือน" : "Notification filter"}><button type="button" aria-pressed={filter === "ALL"} onClick={() => onFilterChange("ALL")}>{locale === "th" ? "ทั้งหมด" : "All"} <span>{items.length}</span></button><button type="button" aria-pressed={filter === "ACTION_REQUIRED"} onClick={() => onFilterChange("ACTION_REQUIRED")}>{locale === "th" ? "ต้องตรวจสอบ" : "Requires review"} <span>{actionRequiredCount}</span></button></div>}
    <section className="module-panel"><div className="record-list notification-list">{visibleItems.map((item) => <article key={item.eventId}><div><strong>{item.eventType}</strong><span>{item.publicBookingId ?? item.eventId}</span><small>{locale === "th" ? "พยายามส่ง" : "Attempts"}: {item.attemptCount ?? 0}{item.lastErrorCode ? ` • ${item.lastErrorCode}` : ""}</small></div><div className="row-form"><span className={`state-chip ${notificationStateTone(item.state)}`}>{formatNotificationState(item.state, locale)}</span>{item.state === "FAILED" && <button onClick={() => retry(item.eventId)}>{locale === "th" ? "ส่งเข้าคิวใหม่" : "Retry"}</button>}</div></article>)}</div>{!loading && items.length > 0 && visibleItems.length === 0 && <div className="module-state">{locale === "th" ? "ไม่มีรายการที่ต้องตรวจสอบ" : "No notifications require review"}</div>}</section>
  </main>;
}
