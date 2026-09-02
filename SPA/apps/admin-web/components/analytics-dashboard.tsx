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

type DailyRevenue = AnalyticsResponse["daily"][number];

type RevenueChartPoint = {
  key: string;
  dateFrom: string;
  dateTo: string;
  serviceRevenueSatang: number;
  tipSatang: number;
  bookingCount: number;
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

function eachDate(dateFrom: string, dateTo: string): string[] {
  const dates: string[] = [];
  const current = new Date(`${dateFrom}T00:00:00Z`);
  const end = new Date(`${dateTo}T00:00:00Z`);

  while (current <= end) {
    dates.push(current.toISOString().slice(0, 10));
    current.setUTCDate(current.getUTCDate() + 1);
  }

  return dates;
}

function fillDailyRevenue(daily: DailyRevenue[], dateFrom: string, dateTo: string): DailyRevenue[] {
  const byDate = new Map(daily.map((item) => [item.localDate, item]));
  return eachDate(dateFrom, dateTo).map((localDate) => byDate.get(localDate) ?? {
    localDate,
    serviceRevenueSatang: 0,
    tipSatang: 0,
    bookingCount: 0,
  });
}

function buildRevenueChartPoints(daily: DailyRevenue[]): RevenueChartPoint[] {
  if (daily.length <= 31) {
    return daily.map((item) => ({
      key: item.localDate,
      dateFrom: item.localDate,
      dateTo: item.localDate,
      serviceRevenueSatang: item.serviceRevenueSatang,
      tipSatang: item.tipSatang,
      bookingCount: item.bookingCount,
    }));
  }

  const weekly: RevenueChartPoint[] = [];
  for (let index = 0; index < daily.length; index += 7) {
    const items = daily.slice(index, index + 7);
    weekly.push({
      key: `${items[0].localDate}:${items.at(-1)?.localDate ?? items[0].localDate}`,
      dateFrom: items[0].localDate,
      dateTo: items.at(-1)?.localDate ?? items[0].localDate,
      serviceRevenueSatang: items.reduce((total, item) => total + item.serviceRevenueSatang, 0),
      tipSatang: items.reduce((total, item) => total + item.tipSatang, 0),
      bookingCount: items.reduce((total, item) => total + item.bookingCount, 0),
    });
  }
  return weekly;
}

function niceMaximum(value: number): number {
  if (value <= 0) return 100;
  const roughStep = value / 4;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  return Math.ceil(roughStep / magnitude) * magnitude * 4;
}

function chartDateLabel(point: RevenueChartPoint, locale: Locale): string {
  if (point.dateFrom === point.dateTo) return shortDate(point.dateFrom, locale);
  return `${shortDate(point.dateFrom, locale)}–${shortDate(point.dateTo, locale)}`;
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

  const completeDaily = useMemo(
    () => data ? fillDailyRevenue(data.daily, data.dateFrom, data.dateTo) : [],
    [data],
  );
  const revenueChart = useMemo(() => buildRevenueChartPoints(completeDaily), [completeDaily]);
  const chartTotals = useMemo(
    () => revenueChart.map((item) => item.serviceRevenueSatang + item.tipSatang),
    [revenueChart],
  );
  const chartTotal = useMemo(() => chartTotals.reduce((total, item) => total + item, 0), [chartTotals]);
  const chartAverage = revenueChart.length ? chartTotal / revenueChart.length : 0;
  const chartMaximum = useMemo(() => niceMaximum(Math.max(0, ...chartTotals)), [chartTotals]);
  const peakChartIndex = chartTotals.length ? chartTotals.indexOf(Math.max(...chartTotals)) : -1;
  const peakDay = useMemo(
    () => data?.daily.length ? completeDaily.reduce<DailyRevenue | null>((peak, item) => {
      const itemTotal = item.serviceRevenueSatang + item.tipSatang;
      const peakTotal = peak ? peak.serviceRevenueSatang + peak.tipSatang : -1;
      return itemTotal > peakTotal ? item : peak;
    }, null) : null,
    [completeDaily, data],
  );
  const dateLabelStep = Math.max(1, Math.ceil(revenueChart.length / 10));
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
          <div className="analytics-trend-header">
            <div>
              <h2 id="revenue-trend-title">{locale === "th" ? "รายได้ตามวันที่ให้บริการ" : "Revenue by service date"}</h2>
              <small>{locale === "th"
                ? revenueChart.length === completeDaily.length ? "แสดงรายวันตามวันที่ให้บริการ" : "รวมข้อมูลเป็นช่วงละ 7 วัน"
                : revenueChart.length === completeDaily.length ? "Daily totals by service date" : "Grouped into 7-day periods"}</small>
            </div>
            <dl className="analytics-trend-summary">
              <div><dt>{locale === "th" ? "รายได้รวม" : "Total revenue"}</dt><dd>{baht(chartTotal, locale)}</dd></div>
              <div><dt>{locale === "th" ? "เฉลี่ยต่อวัน" : "Daily average"}</dt><dd>{baht(completeDaily.length ? chartTotal / completeDaily.length : 0, locale)}</dd></div>
              <div><dt>{locale === "th" ? "วันที่สูงสุด" : "Peak day"}</dt><dd>{peakDay ? `${shortDate(peakDay.localDate, locale)} · ${baht(peakDay.serviceRevenueSatang + peakDay.tipSatang, locale)}` : "—"}</dd></div>
            </dl>
          </div>
          {data.daily.length ? <>
            <div className="analytics-revenue-chart">
              <div className="analytics-y-axis" aria-hidden="true">{[4, 3, 2, 1, 0].map((part) => <span key={part}>{baht((chartMaximum * part) / 4, locale)}</span>)}</div>
              <div className="analytics-plot">
                <div className="analytics-average-line" style={{ bottom: `${48 + (chartAverage / chartMaximum) * 200}px` }} aria-hidden="true"><span>{locale === "th" ? "เฉลี่ย" : "Average"}</span></div>
                <div
                  className="analytics-bars"
                  role="list"
                  aria-label={locale === "th" ? "กราฟรายได้ แยกค่าบริการสุทธิและทิป" : "Revenue chart split by net service revenue and tips"}
                  style={{ gridTemplateColumns: `repeat(${revenueChart.length}, minmax(26px, 1fr))`, minWidth: `${revenueChart.length * 32}px` }}
                >
                  {revenueChart.map((item, index) => {
                    const total = item.serviceRevenueSatang + item.tipSatang;
                    const dateText = chartDateLabel(item, locale);
                    const showDate = index === 0 || index === revenueChart.length - 1 || index % dateLabelStep === 0;
                    const showValue = index === peakChartIndex || index === revenueChart.length - 1;
                    const accessibleLabel = locale === "th"
                      ? `${dateText}: ค่าบริการสุทธิ ${baht(item.serviceRevenueSatang, locale)}, ทิป ${baht(item.tipSatang, locale)}, รวม ${baht(total, locale)}, ${item.bookingCount} รายการ`
                      : `${dateText}: net service ${baht(item.serviceRevenueSatang, locale)}, tips ${baht(item.tipSatang, locale)}, total ${baht(total, locale)}, ${item.bookingCount} bookings`;
                    return <div className={`analytics-bar-column${total === 0 ? " is-zero" : ""}`} key={item.key} role="listitem" tabIndex={0} aria-label={accessibleLabel}>
                      <span className={`analytics-bar-value${showValue ? " is-visible" : ""}`}>{baht(total, locale)}</span>
                      <div className="analytics-revenue-stack" aria-hidden="true">
                        <span className={`analytics-tip-segment${item.tipSatang > 0 ? " has-value" : ""}`} style={{ height: `${(item.tipSatang / chartMaximum) * 100}%` }} />
                        <span className={`analytics-service-segment${item.serviceRevenueSatang > 0 ? " has-value" : ""}`} style={{ height: `${(item.serviceRevenueSatang / chartMaximum) * 100}%` }} />
                      </div>
                      <small className={showDate ? "is-visible" : ""}>{dateText}</small>
                      <span className="analytics-chart-tooltip" aria-hidden="true"><strong>{dateText}</strong><span>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service"} {baht(item.serviceRevenueSatang, locale)}</span><span>{locale === "th" ? "ทิป" : "Tips"} {baht(item.tipSatang, locale)}</span><span>{locale === "th" ? "รวม" : "Total"} {baht(total, locale)}</span></span>
                    </div>;
                  })}
                </div>
              </div>
            </div>
            <div className="analytics-chart-footer">
              <div className="analytics-legend"><span><i className="service" />{locale === "th" ? "ค่าบริการสุทธิ" : "Net service revenue"}</span><span><i className="tip" />{locale === "th" ? "ทิป" : "Tips"}</span><span><i className="average" />{locale === "th" ? revenueChart.length === completeDaily.length ? "เฉลี่ยต่อวัน" : "เฉลี่ยต่อช่วง 7 วัน" : revenueChart.length === completeDaily.length ? "Daily average" : "7-day period average"}</span></div>
              <small>{locale === "th" ? "วางเมาส์หรือใช้ Tab เพื่อดูรายละเอียด" : "Hover or use Tab for exact values"}</small>
            </div>
          </> : <div className="module-state">{locale === "th" ? "ยังไม่มีบริการในช่วงนี้" : "No serviced bookings in this range"}</div>}
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
