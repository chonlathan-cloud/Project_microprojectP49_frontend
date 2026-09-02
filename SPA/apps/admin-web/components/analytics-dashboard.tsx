"use client";

import type { User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useState } from "react";

import { adminApi } from "@/lib/admin-api";
import type { Locale } from "@spa/shared-types";

type AnalyticsSummary = {
  bookingCount: number;
  servicedBookingCount: number;
  serviceRevenueSatang: number;
  tipSatang: number;
  earnedGrossSatang: number;
  verifiedCollectedSatang: number;
  historicalRecordedGrossSatang: number;
  outstandingSatang: number;
  therapistPaySatang: number;
  therapistTipSatang: number;
  shopServiceSatang: number;
  shopTipSatang: number;
  shopTotalSatang: number;
  settlementPendingCount: number;
  negativeShopServiceCount: number;
};

type AnalyticsResponse = {
  dateFrom: string;
  dateTo: string;
  summary: AnalyticsSummary;
  daily: Array<{ localDate: string; serviceRevenueSatang: number; tipSatang: number; bookingCount: number }>;
  services: Array<{
    serviceId: string;
    variantId: string;
    serviceNameTh: string;
    serviceNameEn: string;
    durationMinutes: number;
    sessionCount: number;
    participantCount: number;
    grossServiceSatang: number;
    discountAllocatedSatang: number;
    netServiceSatang: number;
  }>;
  therapists: Array<{
    therapistId: string;
    therapistName: string;
    serviceCount: number;
    durationMinutes: number;
    therapistPaySatang: number;
    tipSatang: number;
    services: Array<{
      serviceName: string;
      count: number;
      durationMinutes: number;
      therapistPaySatang: number;
      tipSatang: number;
    }>;
  }>;
  peakHours: Array<{ hour: string; scheduledCount: number; actualCount: number }>;
};

function bangkokDate(offsetDays = 0): string {
  const value = new Date(Date.now() + offsetDays * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Bangkok",
  }).format(value);
}

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

function shortDate(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "Asia/Bangkok",
  }).format(new Date(`${value}T12:00:00+07:00`));
}

function SummaryMetric({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "warning" | "danger" | "positive" }) {
  return <div className={`analytics-metric ${tone ?? ""}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

export function AnalyticsDashboard({ locale, user }: { locale: Locale; user: User }) {
  const [dateFrom, setDateFrom] = useState(() => bangkokDate(-29));
  const [dateTo, setDateTo] = useState(() => bangkokDate());
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ branchId: "branch_001", dateFrom, dateTo });
    try {
      setData(await adminApi<AnalyticsResponse>(user, `/analytics/overview?${params.toString()}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Analytics unavailable");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, user]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  const maxDaily = useMemo(() => Math.max(1, ...(data?.daily.map((item) => item.serviceRevenueSatang + item.tipSatang) ?? [1])), [data]);
  const maxHour = useMemo(() => Math.max(1, ...(data?.peakHours.map((item) => Math.max(item.scheduledCount, item.actualCount)) ?? [1])), [data]);
  const summary = data?.summary;

  return <main className="dashboard-content analytics-workspace">
    <div className="module-heading-action analytics-heading">
      <div className="module-heading"><p className="eyebrow">STORE PERFORMANCE • ASIA/BANGKOK</p><h1>{locale === "th" ? "ภาพรวมรายได้และบริการ" : "Revenue & service overview"}</h1><p>{locale === "th" ? "แยกยอดที่เกิดขึ้น เงินที่รับแล้ว ค่าหมอ และส่วนของร้านอย่างชัดเจน" : "Separate earned sales, collected payments, therapist compensation, and shop share."}</p></div>
      <div className="analytics-date-filter" aria-label={locale === "th" ? "ช่วงวันที่ให้บริการ" : "Service date range"}>
        <label><span>{locale === "th" ? "ตั้งแต่" : "From"}</span><input type="date" value={dateFrom} max={dateTo} onChange={(event) => setDateFrom(event.target.value)} /></label>
        <label><span>{locale === "th" ? "ถึง" : "To"}</span><input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} /></label>
      </div>
    </div>

    {loading && <div className="module-state" role="status">{locale === "th" ? "กำลังคำนวณข้อมูลจริง…" : "Calculating live data…"}</div>}
    {error && <div className="module-state error" role="alert">{locale === "th" ? `โหลด Dashboard ไม่สำเร็จ: ${error}` : `Dashboard unavailable: ${error}`}</div>}

    {!loading && summary && <>
      {(summary.settlementPendingCount > 0 || summary.negativeShopServiceCount > 0) && <section className="analytics-attention" aria-label={locale === "th" ? "รายการที่ต้องตรวจสอบ" : "Items requiring review"}>
        <strong>{locale === "th" ? "ต้องตรวจสอบ" : "Review required"}</strong>
        <span>{locale === "th" ? `${summary.settlementPendingCount} รายการยังไม่สรุปค่าหมอ/ทิป` : `${summary.settlementPendingCount} services await compensation allocation`}</span>
        {summary.negativeShopServiceCount > 0 && <span className="danger">{locale === "th" ? `${summary.negativeShopServiceCount} รายการมีส่วนร้านติดลบ` : `${summary.negativeShopServiceCount} allocations have a negative shop share`}</span>}
      </section>}

      <section className="analytics-summary" aria-label={locale === "th" ? "สรุปการเงิน" : "Financial summary"}>
        <SummaryMetric label={locale === "th" ? "ค่าบริการที่เกิดขึ้น" : "Earned service revenue"} value={baht(summary.serviceRevenueSatang, locale)} note={locale === "th" ? `${summary.servicedBookingCount} รายการให้บริการจริง` : `${summary.servicedBookingCount} serviced bookings`} />
        <SummaryMetric label={locale === "th" ? "รับเงินยืนยันแล้ว" : "Verified collected"} value={baht(summary.verifiedCollectedSatang, locale)} note={locale === "th" ? "เฉพาะ Payment สถานะ PAID" : "Payments with PAID status only"} tone="positive" />
        <SummaryMetric label={locale === "th" ? "ยอดย้อนหลังที่บันทึก" : "Historical recorded gross"} value={baht(summary.historicalRecordedGrossSatang, locale)} note={locale === "th" ? "ไม่มีหลักฐานวิธีรับชำระ" : "Payment method not captured"} />
        <SummaryMetric label={locale === "th" ? "ค้างรับ" : "Outstanding"} value={baht(summary.outstandingSatang, locale)} note={locale === "th" ? "บริการเสร็จแต่ยังไม่ PAID" : "Completed but not PAID"} tone={summary.outstandingSatang > 0 ? "warning" : undefined} />
        <SummaryMetric label={locale === "th" ? "ค่าหมอ + ทิปหมอ" : "Therapist pay + tips"} value={baht(summary.therapistPaySatang + summary.therapistTipSatang, locale)} note={`${baht(summary.therapistPaySatang, locale)} + ${baht(summary.therapistTipSatang, locale)}`} />
        <SummaryMetric label={locale === "th" ? "ส่วนของร้านที่สรุปแล้ว" : "Allocated shop share"} value={baht(summary.shopTotalSatang, locale)} note={locale === "th" ? `ค่าบริการ ${baht(summary.shopServiceSatang, locale)} • ทิป ${baht(summary.shopTipSatang, locale)}` : `Service ${baht(summary.shopServiceSatang, locale)} • tip ${baht(summary.shopTipSatang, locale)}`} tone={summary.shopTotalSatang < 0 ? "danger" : "positive"} />
      </section>

      <div className="analytics-grid">
        <section className="module-panel analytics-trend" aria-labelledby="revenue-trend-title">
          <div className="panel-title"><div><h2 id="revenue-trend-title">{locale === "th" ? "รายได้ตามวันที่ให้บริการ" : "Revenue by service date"}</h2><small>{locale === "th" ? "ค่าบริการสุทธิ + ทิป" : "Net service revenue + tips"}</small></div></div>
          {data.daily.length ? <div className="analytics-bars" role="img" aria-label={locale === "th" ? "กราฟรายได้รายวัน" : "Daily revenue chart"}>{data.daily.slice(-31).map((item) => {
            const total = item.serviceRevenueSatang + item.tipSatang;
            return <div className="analytics-bar-column" key={item.localDate} title={`${shortDate(item.localDate, locale)} • ${baht(total, locale)}`}><span className="analytics-bar-value">{baht(total, locale)}</span><div className="analytics-bar-track"><span style={{ height: `${Math.max(3, (total / maxDaily) * 100)}%` }} /></div><small>{shortDate(item.localDate, locale)}</small></div>;
          })}</div> : <div className="module-state">{locale === "th" ? "ยังไม่มีบริการในช่วงนี้" : "No serviced bookings in this range"}</div>}
        </section>

        <section className="module-panel analytics-services" aria-labelledby="top-services-title">
          <div className="panel-title"><div><h2 id="top-services-title">{locale === "th" ? "บริการที่ได้รับบ่อยสุด" : "Top serviced treatments"}</h2><small>{locale === "th" ? "นับเฉพาะ COMPLETED และ RECORDED ที่ไม่ถูกยกเลิก" : "Completed and active historical records only"}</small></div></div>
          <div className="table-scroll"><table><thead><tr><th>{locale === "th" ? "บริการ" : "Service"}</th><th>{locale === "th" ? "ครั้ง" : "Sessions"}</th><th>{locale === "th" ? "ผู้รับบริการ" : "Guests"}</th><th>{locale === "th" ? "ยอดสุทธิ" : "Net"}</th></tr></thead><tbody>{data.services.slice(0, 10).map((item) => <tr key={`${item.serviceId}:${item.variantId}`}><td><strong>{locale === "th" ? item.serviceNameTh : item.serviceNameEn}</strong><small>{item.durationMinutes} {locale === "th" ? "นาที" : "min"}</small></td><td>{item.sessionCount}</td><td>{item.participantCount}</td><td><strong>{baht(item.netServiceSatang, locale)}</strong>{item.discountAllocatedSatang > 0 && <small>{locale === "th" ? `ลด ${baht(item.discountAllocatedSatang, locale)}` : `${baht(item.discountAllocatedSatang, locale)} discount`}</small>}</td></tr>)}</tbody></table></div>
          {!data.services.length && <div className="module-state">{locale === "th" ? "ยังไม่มีข้อมูลบริการ" : "No service data"}</div>}
        </section>

        <section className="module-panel analytics-peak" aria-labelledby="peak-hours-title">
          <div className="panel-title"><div><h2 id="peak-hours-title">{locale === "th" ? "ช่วงเวลาที่ลูกค้ามาใช้บริการ" : "Peak service hours"}</h2><small>{locale === "th" ? "เวลานัด เทียบเวลาเริ่มจริงที่ระบบเก็บได้" : "Scheduled versus captured actual starts"}</small></div></div>
          <div className="peak-hour-list">{data.peakHours.map((item) => <div key={item.hour}><time>{item.hour}:00</time><div className="peak-track"><span className="scheduled" style={{ width: `${(item.scheduledCount / maxHour) * 100}%` }} /><span className="actual" style={{ width: `${(item.actualCount / maxHour) * 100}%` }} /></div><strong>{item.scheduledCount}<small> / {item.actualCount}</small></strong></div>)}</div>
          <div className="analytics-legend"><span><i className="scheduled" />{locale === "th" ? "เวลานัด" : "Scheduled"}</span><span><i className="actual" />{locale === "th" ? "เวลาเริ่มจริง" : "Actual"}</span></div>
        </section>

        <section className="module-panel analytics-therapists" aria-labelledby="therapist-performance-title">
          <div className="panel-title"><div><h2 id="therapist-performance-title">{locale === "th" ? "ผลงานและค่าหมอ" : "Therapist performance"}</h2><small>{locale === "th" ? "แสดงเฉพาะรายการที่ Admin สรุปแล้ว" : "Finalized allocations only"}</small></div></div>
          <div className="table-scroll"><table><thead><tr><th>{locale === "th" ? "หมอนวด" : "Therapist"}</th><th>{locale === "th" ? "งาน/เวลา" : "Work/time"}</th><th>{locale === "th" ? "บริการ / ค่าหมอ" : "Services / pay"}</th><th>{locale === "th" ? "ค่าหมอรวม" : "Total pay"}</th><th>{locale === "th" ? "ทิป" : "Tips"}</th></tr></thead><tbody>{data.therapists.map((item) => <tr key={item.therapistId}><td><strong>{item.therapistName}</strong></td><td>{item.serviceCount}<small>{Math.round(item.durationMinutes / 60 * 10) / 10} {locale === "th" ? "ชม." : "hrs"}</small></td><td>{item.services.slice(0, 3).map((service) => <small key={service.serviceName}>{service.serviceName} × {service.count} • {baht(service.therapistPaySatang, locale)}</small>)}</td><td><strong>{baht(item.therapistPaySatang, locale)}</strong></td><td>{baht(item.tipSatang, locale)}</td></tr>)}</tbody></table></div>
          {!data.therapists.length && <div className="module-state">{locale === "th" ? "ยังไม่มีรายการค่าหมอที่สรุปแล้ว" : "No finalized compensation allocations"}</div>}
        </section>
      </div>
    </>}
  </main>;
}
