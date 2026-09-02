"use client";

import type { User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { adminApi, adminDownload } from "@/lib/admin-api";
import type { Locale } from "@spa/shared-types";

type InsightView = "REVENUE" | "SERVICES" | "THERAPISTS" | "BOOKINGS";
type FilterValue = "ALL" | "YES" | "NO";

type InsightFilters = {
  dateFrom: string;
  dateTo: string;
  channel: string;
  serviceId: string;
  variantId: string;
  therapistId: string;
  bookingStatus: string;
  paymentStatus: string;
  settlementState: string;
  hasDiscount: FilterValue;
  hasTip: FilterValue;
  hourFrom: string;
  hourTo: string;
};

type InsightSummary = {
  bookingCount: number;
  netServiceAmountSatang: number;
  tipAmountSatang: number;
  grossAmountSatang: number;
  paidAmountSatang: number;
  outstandingAmountSatang: number;
  therapistPaySatang: number;
  therapistTipSatang: number;
  shopTotalSatang: number;
  settlementPendingCount: number;
};

type InsightResponse = {
  dateFrom: string;
  dateTo: string;
  timezone: string;
  view: InsightView;
  summary: InsightSummary;
  items: Array<Record<string, unknown>>;
  pagination: { page: number; pageSize: number; totalItems: number; totalPages: number };
};

type ServiceOption = {
  serviceId: string;
  nameTh: string;
  nameEn: string;
  variants: Array<{ variantId: string; durationMinutes: number; active: boolean }>;
};

type TherapistOption = { therapistId: string; displayName: string; active: boolean };

const PAGE_SIZE = 50;

function bangkokDate(offsetDays = 0): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Bangkok",
  }).format(new Date(Date.now() + offsetDays * 86_400_000));
}

function initialFilters(): InsightFilters {
  return {
    dateFrom: bangkokDate(-29),
    dateTo: bangkokDate(),
    channel: "",
    serviceId: "",
    variantId: "",
    therapistId: "",
    bookingStatus: "",
    paymentStatus: "",
    settlementState: "",
    hasDiscount: "ALL",
    hasTip: "ALL",
    hourFrom: "",
    hourTo: "",
  };
}

function baht(value: unknown, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(Number(value ?? 0) / 100);
}

function dateLabel(value: unknown, locale: Locale): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Bangkok",
  }).format(new Date(`${String(value)}T12:00:00+07:00`));
}

function joined(value: unknown): string {
  return Array.isArray(value) ? value.map(String).join(" • ") : String(value ?? "—");
}

function buildFilterPayload(filters: InsightFilters): Record<string, string | boolean> {
  const payload: Record<string, string | boolean> = {
    branchId: "branch_001",
    dateFrom: filters.dateFrom,
    dateTo: filters.dateTo,
  };
  if (["GUEST_WEB", "LINE_CUSTOMER", "ADMIN_WEB"].includes(filters.channel)) payload.source = filters.channel;
  if (["WALK_IN", "STAFF_ASSISTED", "HISTORICAL_RECORD"].includes(filters.channel)) payload.adminEntryMode = filters.channel;
  for (const [key, value] of Object.entries({
    serviceId: filters.serviceId,
    variantId: filters.variantId,
    therapistId: filters.therapistId,
    bookingStatus: filters.bookingStatus,
    paymentStatus: filters.paymentStatus,
    settlementState: filters.settlementState,
    hourFrom: filters.hourFrom,
    hourTo: filters.hourTo,
  })) {
    if (value) payload[key] = value;
  }
  if (filters.hasDiscount !== "ALL") payload.hasDiscount = filters.hasDiscount === "YES";
  if (filters.hasTip !== "ALL") payload.hasTip = filters.hasTip === "YES";
  return payload;
}

function queryString(filters: InsightFilters, view: InsightView, page: number): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({
    ...buildFilterPayload(filters),
    view,
    page: String(page),
    pageSize: String(PAGE_SIZE),
  })) params.set(key, String(value));
  return params.toString();
}

function StateLabel({ value, locale }: { value: unknown; locale: Locale }) {
  const state = String(value ?? "PENDING");
  const labels: Record<string, { th: string; en: string }> = {
    ALLOCATED: { th: "สรุปแล้ว", en: "Allocated" },
    PENDING: { th: "รอสรุป", en: "Pending" },
    STALE: { th: "ต้องแบ่งทิปใหม่", en: "Stale" },
  };
  return <span className={`insight-state state-${state.toLowerCase()}`}>{labels[state]?.[locale] ?? state}</span>;
}

export function InsightWorkspace({ locale, user }: { locale: Locale; user: User }) {
  const { notify } = useAdminFeedback();
  const [view, setView] = useState<InsightView>("REVENUE");
  const [draft, setDraft] = useState<InsightFilters>(initialFilters);
  const [applied, setApplied] = useState<InsightFilters>(initialFilters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<InsightResponse | null>(null);
  const [services, setServices] = useState<ServiceOption[]>([]);
  const [therapists, setTherapists] = useState<TherapistOption[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error" | "exporting">("loading");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    setError("");
    try {
      setData(await adminApi<InsightResponse>(user, `/analytics/insight?${queryString(applied, view, page)}`));
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Insight unavailable");
      setState("error");
    }
  }, [applied, page, user, view]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);
  useEffect(() => {
    let active = true;
    Promise.all([
      adminApi<{ items: ServiceOption[] }>(user, "/services"),
      adminApi<{ items: TherapistOption[] }>(user, "/therapists"),
    ]).then(([servicePayload, therapistPayload]) => {
      if (!active) return;
      setServices(servicePayload.items);
      setTherapists(therapistPayload.items.filter((item) => item.active));
    }).catch(() => {
      // Insight still works without filter option labels.
    });
    return () => { active = false; };
  }, [user]);

  const selectedService = useMemo(
    () => services.find((item) => item.serviceId === draft.serviceId),
    [draft.serviceId, services],
  );

  function applyFilters() {
    setPage(1);
    setApplied({ ...draft });
  }

  function resetFilters() {
    const next = initialFilters();
    setDraft(next);
    setApplied(next);
    setPage(1);
  }

  async function exportCsv() {
    if (state === "exporting") return;
    setState("exporting");
    try {
      await adminDownload(user, "/analytics/insight:export", {
        method: "POST",
        body: JSON.stringify({ ...buildFilterPayload(applied), view }),
      });
      notify({
        tone: "success",
        title: locale === "th" ? "ดาวน์โหลด Insight CSV แล้ว" : "Insight CSV downloaded",
        message: locale === "th" ? "ไฟล์ใช้ตัวกรองที่กำลังแสดงและบันทึก Audit แล้ว" : "Current filters were applied and the export was audited.",
      });
      setState("ready");
    } catch (caught) {
      setState("error");
      setError(caught instanceof Error ? caught.message : "Export failed");
    }
  }

  const summary = data?.summary;
  const tabs: Array<[InsightView, string, string]> = [
    ["REVENUE", "รายได้", "Revenue"],
    ["SERVICES", "บริการ", "Services"],
    ["THERAPISTS", "หมอนวด", "Therapists"],
    ["BOOKINGS", "รายการให้บริการ", "Bookings"],
  ];

  return <main className="dashboard-content insight-workspace">
    <div className="module-heading-action insight-heading">
      <div className="module-heading"><p className="eyebrow">DETAILED PERFORMANCE • ASIA/BANGKOK</p><h1>{locale === "th" ? "Insight รายละเอียดธุรกิจ" : "Business insight"}</h1><p>{locale === "th" ? "วิเคราะห์รายได้ บริการ และผลงานหมอจากข้อมูลที่ให้บริการจริง" : "Explore serviced revenue, treatments, and therapist performance."}</p></div>
      <button type="button" className="primary-compact-button insight-export" disabled={state === "loading" || state === "exporting" || !data} onClick={() => { void exportCsv(); }}>{state === "exporting" ? (locale === "th" ? "กำลัง Export…" : "Exporting…") : `Export CSV • ${tabs.find(([id]) => id === view)?.[locale === "th" ? 1 : 2]}`}</button>
    </div>

    <form className="insight-filter-bar" onSubmit={(event) => { event.preventDefault(); applyFilters(); }}>
      <div className="insight-filter-primary">
        <label><span>{locale === "th" ? "ตั้งแต่" : "From"}</span><input type="date" value={draft.dateFrom} max={draft.dateTo} onChange={(event) => setDraft((current) => ({ ...current, dateFrom: event.target.value }))} /></label>
        <label><span>{locale === "th" ? "ถึง" : "To"}</span><input type="date" value={draft.dateTo} min={draft.dateFrom} onChange={(event) => setDraft((current) => ({ ...current, dateTo: event.target.value }))} /></label>
        <label><span>{locale === "th" ? "ช่องทาง" : "Channel"}</span><select value={draft.channel} onChange={(event) => setDraft((current) => ({ ...current, channel: event.target.value }))}><option value="">{locale === "th" ? "ทั้งหมด" : "All channels"}</option><option value="LINE_CUSTOMER">LINE</option><option value="GUEST_WEB">Guest Web</option><option value="STAFF_ASSISTED">Admin Assisted</option><option value="WALK_IN">Walk-in</option><option value="HISTORICAL_RECORD">Historical</option></select></label>
        <label><span>{locale === "th" ? "บริการ" : "Service"}</span><select value={draft.serviceId} onChange={(event) => setDraft((current) => ({ ...current, serviceId: event.target.value, variantId: "" }))}><option value="">{locale === "th" ? "ทุกบริการ" : "All services"}</option>{services.map((item) => <option value={item.serviceId} key={item.serviceId}>{locale === "th" ? item.nameTh : item.nameEn}</option>)}</select></label>
        <label><span>{locale === "th" ? "ระยะเวลา" : "Duration"}</span><select value={draft.variantId} disabled={!selectedService} onChange={(event) => setDraft((current) => ({ ...current, variantId: event.target.value }))}><option value="">{locale === "th" ? "ทุกระยะเวลา" : "All durations"}</option>{selectedService?.variants.filter((item) => item.active).map((item) => <option value={item.variantId} key={item.variantId}>{item.durationMinutes} {locale === "th" ? "นาที" : "min"}</option>)}</select></label>
        <label><span>{locale === "th" ? "หมอนวด" : "Therapist"}</span><select value={draft.therapistId} onChange={(event) => setDraft((current) => ({ ...current, therapistId: event.target.value }))}><option value="">{locale === "th" ? "ทุกคน" : "All therapists"}</option>{therapists.map((item) => <option value={item.therapistId} key={item.therapistId}>{item.displayName}</option>)}</select></label>
      </div>
      <details className="insight-more-filters"><summary>{locale === "th" ? "ตัวกรองเพิ่มเติม" : "More filters"}</summary><div className="insight-filter-secondary">
        <label><span>{locale === "th" ? "สถานะรายการ" : "Booking status"}</span><select value={draft.bookingStatus} onChange={(event) => setDraft((current) => ({ ...current, bookingStatus: event.target.value }))}><option value="">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="COMPLETED">COMPLETED</option><option value="RECORDED">RECORDED</option></select></label>
        <label><span>{locale === "th" ? "การชำระเงิน" : "Payment"}</span><select value={draft.paymentStatus} onChange={(event) => setDraft((current) => ({ ...current, paymentStatus: event.target.value }))}><option value="">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="PAID">PAID</option><option value="DUE">DUE</option><option value="UNAVAILABLE">UNAVAILABLE</option></select></label>
        <label><span>{locale === "th" ? "สรุปค่าหมอ" : "Settlement"}</span><select value={draft.settlementState} onChange={(event) => setDraft((current) => ({ ...current, settlementState: event.target.value }))}><option value="">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="ALLOCATED">ALLOCATED</option><option value="PENDING">PENDING</option><option value="STALE">STALE</option></select></label>
        <label><span>{locale === "th" ? "มีส่วนลด" : "Discount"}</span><select value={draft.hasDiscount} onChange={(event) => setDraft((current) => ({ ...current, hasDiscount: event.target.value as FilterValue }))}><option value="ALL">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="YES">{locale === "th" ? "มี" : "Yes"}</option><option value="NO">{locale === "th" ? "ไม่มี" : "No"}</option></select></label>
        <label><span>{locale === "th" ? "มีทิป" : "Tip"}</span><select value={draft.hasTip} onChange={(event) => setDraft((current) => ({ ...current, hasTip: event.target.value as FilterValue }))}><option value="ALL">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="YES">{locale === "th" ? "มี" : "Yes"}</option><option value="NO">{locale === "th" ? "ไม่มี" : "No"}</option></select></label>
        <label><span>{locale === "th" ? "เวลาเริ่มตั้งแต่" : "Hour from"}</span><input type="number" min="0" max="23" value={draft.hourFrom} placeholder="0" onChange={(event) => setDraft((current) => ({ ...current, hourFrom: event.target.value }))} /></label>
        <label><span>{locale === "th" ? "ถึงเวลา" : "Hour to"}</span><input type="number" min="0" max="23" value={draft.hourTo} placeholder="23" onChange={(event) => setDraft((current) => ({ ...current, hourTo: event.target.value }))} /></label>
      </div></details>
      <div className="insight-filter-actions"><button type="button" onClick={resetFilters}>{locale === "th" ? "ล้างตัวกรอง" : "Reset"}</button><button type="submit" className="confirm-button">{locale === "th" ? "ใช้ตัวกรอง" : "Apply filters"}</button></div>
    </form>

    {error && <div className="module-state error" role="alert">{locale === "th" ? `โหลด Insight ไม่สำเร็จ: ${error}` : `Insight unavailable: ${error}`}</div>}
    {state === "loading" && <div className="module-state" role="status">{locale === "th" ? "กำลังคำนวณ Insight…" : "Calculating insight…"}</div>}
    {summary && <section className="insight-summary" aria-label={locale === "th" ? "สรุปตามตัวกรอง" : "Filtered summary"}><div><span>{locale === "th" ? "รายการ" : "Bookings"}</span><strong>{summary.bookingCount}</strong></div><div><span>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service"}</span><strong>{baht(summary.netServiceAmountSatang, locale)}</strong></div><div><span>{locale === "th" ? "ยอดรวมทิป" : "Tips"}</span><strong>{baht(summary.tipAmountSatang, locale)}</strong></div><div><span>{locale === "th" ? "รับเงินแล้ว" : "Collected"}</span><strong>{baht(summary.paidAmountSatang, locale)}</strong></div><div className={summary.settlementPendingCount ? "warning" : ""}><span>{locale === "th" ? "รอสรุปค่าหมอ" : "Awaiting allocation"}</span><strong>{summary.settlementPendingCount}</strong></div></section>}

    <section className="module-panel insight-results" aria-labelledby="insight-result-title">
      <div className="insight-tabs" role="tablist" aria-label={locale === "th" ? "มุมมอง Insight" : "Insight view"}>{tabs.map(([id, th, en]) => <button type="button" role="tab" aria-selected={view === id} onClick={() => { setView(id); setPage(1); }} key={id}>{locale === "th" ? th : en}</button>)}</div>
      <h2 id="insight-result-title" className="sr-only">{tabs.find(([id]) => id === view)?.[locale === "th" ? 1 : 2]}</h2>
      {data && <InsightTable view={view} items={data.items} locale={locale} />}
      {data && !data.items.length && <div className="module-state">{locale === "th" ? "ไม่พบข้อมูลที่ตรงกับตัวกรอง" : "No data matches these filters"}</div>}
      {data && <nav className="insight-pagination" aria-label={locale === "th" ? "เปลี่ยนหน้าผลลัพธ์" : "Insight pagination"}><span>{locale === "th" ? `${data.pagination.totalItems} รายการ • หน้า ${data.pagination.page}/${data.pagination.totalPages}` : `${data.pagination.totalItems} records • Page ${data.pagination.page}/${data.pagination.totalPages}`}</span><div><button type="button" disabled={page <= 1 || state === "loading"} onClick={() => setPage((value) => Math.max(1, value - 1))}>← {locale === "th" ? "ก่อนหน้า" : "Previous"}</button><button type="button" disabled={page >= data.pagination.totalPages || state === "loading"} onClick={() => setPage((value) => value + 1)}>{locale === "th" ? "ถัดไป" : "Next"} →</button></div></nav>}
    </section>
  </main>;
}

function InsightTable({ view, items, locale }: { view: InsightView; items: Array<Record<string, unknown>>; locale: Locale }) {
  if (view === "REVENUE") return <div className="table-scroll"><table className="insight-table"><thead><tr><th>{locale === "th" ? "วันที่" : "Date"}</th><th>{locale === "th" ? "รายการ" : "Bookings"}</th><th>{locale === "th" ? "ค่าบริการ" : "Net service"}</th><th>{locale === "th" ? "ทิป" : "Tips"}</th><th>{locale === "th" ? "รับแล้ว" : "Collected"}</th><th>{locale === "th" ? "ค้างรับ" : "Outstanding"}</th><th>{locale === "th" ? "ค่าหมอ/ทิป" : "Therapist pay/tip"}</th><th>{locale === "th" ? "ส่วนร้าน" : "Shop share"}</th></tr></thead><tbody>{items.map((item) => <tr key={String(item.localDate)}><td><strong>{dateLabel(item.localDate, locale)}</strong></td><td>{String(item.bookingCount)}</td><td>{baht(item.netServiceAmountSatang, locale)}</td><td>{baht(item.tipAmountSatang, locale)}</td><td>{baht(item.paidAmountSatang, locale)}</td><td>{baht(item.outstandingAmountSatang, locale)}</td><td>{baht(item.therapistPaySatang, locale)}<small>+ {baht(item.therapistTipSatang, locale)}</small></td><td><strong>{baht(item.shopTotalSatang, locale)}</strong></td></tr>)}</tbody></table></div>;
  if (view === "SERVICES") return <div className="table-scroll"><table className="insight-table"><thead><tr><th>{locale === "th" ? "บริการ" : "Service"}</th><th>{locale === "th" ? "ระยะเวลา" : "Duration"}</th><th>{locale === "th" ? "ครั้ง" : "Sessions"}</th><th>{locale === "th" ? "ผู้รับบริการ" : "Guests"}</th><th>{locale === "th" ? "ราคาก่อนลด" : "Gross"}</th><th>{locale === "th" ? "ส่วนลด" : "Discount"}</th><th>{locale === "th" ? "ยอดสุทธิ" : "Net"}</th></tr></thead><tbody>{items.map((item) => <tr key={`${item.serviceId}:${item.variantId}`}><td><strong>{String(locale === "th" ? item.serviceNameTh : item.serviceNameEn)}</strong><small>{String(item.variantId)}</small></td><td>{String(item.durationMinutes)} {locale === "th" ? "นาที" : "min"}</td><td>{String(item.sessionCount)}</td><td>{String(item.participantCount)}</td><td>{baht(item.grossServiceSatang, locale)}</td><td>{baht(item.discountAllocatedSatang, locale)}</td><td><strong>{baht(item.netServiceSatang, locale)}</strong></td></tr>)}</tbody></table></div>;
  if (view === "THERAPISTS") return <div className="table-scroll"><table className="insight-table"><thead><tr><th>{locale === "th" ? "หมอนวด" : "Therapist"}</th><th>{locale === "th" ? "จำนวนงาน" : "Services"}</th><th>{locale === "th" ? "เวลารวม" : "Duration"}</th><th>{locale === "th" ? "ค่าหมอ" : "Pay"}</th><th>{locale === "th" ? "ส่วนแบ่งทิป" : "Tip share"}</th><th>{locale === "th" ? "รับรวม" : "Total"}</th></tr></thead><tbody>{items.map((item) => <tr key={String(item.therapistId)}><td><strong>{String(item.therapistName)}</strong></td><td>{String(item.serviceCount)}</td><td>{Math.round(Number(item.durationMinutes ?? 0) / 6) / 10} {locale === "th" ? "ชม." : "hrs"}</td><td>{baht(item.therapistPaySatang, locale)}</td><td>{baht(item.tipSatang, locale)}</td><td><strong>{baht(Number(item.therapistPaySatang ?? 0) + Number(item.tipSatang ?? 0), locale)}</strong></td></tr>)}</tbody></table></div>;
  return <div className="table-scroll"><table className="insight-table insight-booking-table"><thead><tr><th>{locale === "th" ? "วัน/เวลา" : "Date/time"}</th><th>Booking ID</th><th>{locale === "th" ? "บริการ" : "Services"}</th><th>{locale === "th" ? "ช่องทาง" : "Channel"}</th><th>{locale === "th" ? "ยอดรับรวม" : "Gross"}</th><th>{locale === "th" ? "ชำระเงิน" : "Payment"}</th><th>{locale === "th" ? "หมอนวด" : "Therapists"}</th><th>{locale === "th" ? "สรุปค่าหมอ" : "Settlement"}</th></tr></thead><tbody>{items.map((item) => <tr key={String(item.bookingId)}><td><strong>{dateLabel(item.localDate, locale)}</strong><small>{String(item.localStartTime ?? "—")}</small></td><td><strong>{String(item.bookingId)}</strong><small>{String(item.status)}</small></td><td>{joined(locale === "th" ? item.serviceNamesTh : item.serviceNamesEn)}</td><td>{String(item.adminEntryMode ?? item.source ?? "—")}</td><td><strong>{baht(item.grossAmountSatang, locale)}</strong><small>{locale === "th" ? `ลด ${baht(item.discountAmountSatang, locale)}` : `${baht(item.discountAmountSatang, locale)} discount`}</small></td><td>{String(item.paymentStatus)}<small>{baht(item.paidAmountSatang, locale)}</small></td><td>{joined(item.therapistNames)}</td><td><StateLabel value={item.settlementState} locale={locale} /></td></tr>)}</tbody></table></div>;
}
