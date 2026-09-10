"use client";

import type { User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { CashDepositWorkflow } from "@/components/cash-deposit-workflow";
import { adminApi } from "@/lib/admin-api";
import type { Locale } from "@spa/shared-types";

type ExportStatus = "READY" | "ENQUEUE_PENDING" | "ENQUEUED" | "PROCESSING" | "RETRYABLE" | "RECONCILE_REQUIRED" | "REVIEW_REQUIRED" | "SYNCED";
type PaymentSource = "BEAM" | "CASH" | "BANK_TRANSFER";
type BankTransferAccount = { key: string; labelTh: string; labelEn: string };
type PaymentRow = {
  exportId: string;
  paymentId: string;
  bookingId: string;
  serviceAt?: string | null;
  customerName: string;
  customerPhoneMasked: string;
  serviceSummary: string;
  pax: number;
  paymentSource: PaymentSource;
  paidAt: string;
  providerReferenceId?: string | null;
  serviceAmountSatang: number;
  tipAmountSatang: number;
  grossAmountSatang: number;
  projectName: string;
  exportStatus: ExportStatus;
  flowAccountDocumentId?: string | null;
  flowAccountDocumentSerial?: string | null;
  flowAccountDocumentUrl?: string | null;
  cashSettlementStatus: string;
  cashDepositId?: string | null;
  attemptCount: number;
  lastErrorCode?: string | null;
  accountingDate: string;
  syncedAt?: string | null;
  adminEntryMode?: string | null;
  historicalFinancialRecord?: boolean;
  bankAccountKey?: string | null;
  bankAccountLabel?: string | null;
};
type HistoricalCandidate = {
  bookingId: string;
  serviceAt?: string | null;
  suggestedPaidAt?: string | null;
  customerName: string;
  customerPhoneMasked: string;
  serviceSummary: string;
  pax: number;
  serviceAmountSatang: number;
  tipAmountSatang: number;
  grossAmountSatang: number;
  eligible: boolean;
  blockingReason?: "NON_POSITIVE_AMOUNT" | null;
  version: number;
};
type HistoricalCandidateResponse = { items: HistoricalCandidate[]; total: number };
type ListResponse = {
  items: PaymentRow[];
  nextPageToken?: string | null;
  summary: {
    paidGrossSatang: number;
    beamGrossSatang: number;
    cashGrossSatang: number;
    bankTransferGrossSatang: number;
    syncedCount: number;
    attentionCount: number;
  };
  permissions: { read: boolean; sync: boolean; cashDeposit: boolean };
};
type SyncRun = {
  runId: string;
  status: "PENDING" | "ENQUEUING" | "RUNNING" | "COMPLETED" | "PARTIAL_FAILURE";
  selectedCount?: number;
  enqueuedCount?: number;
  processedCount?: number;
  syncedCount?: number;
  failedCount?: number;
  reviewCount?: number;
};
type DetailResponse = { payment: PaymentRow; attempts: Array<Record<string, unknown>> };

const terminalRuns = new Set(["COMPLETED", "PARTIAL_FAILURE"]);
const attentionStates = new Set<ExportStatus>(["RECONCILE_REQUIRED", "REVIEW_REQUIRED"]);
const selectableStates = new Set<ExportStatus>(["READY", "RETRYABLE"]);

const statusText: Record<ExportStatus, { th: string; en: string }> = {
  READY: { th: "พร้อมส่ง", en: "Ready" },
  ENQUEUE_PENDING: { th: "กำลังเข้าคิว", en: "Queueing" },
  ENQUEUED: { th: "เข้าคิวแล้ว", en: "Queued" },
  PROCESSING: { th: "กำลังส่ง", en: "Processing" },
  RETRYABLE: { th: "ลองใหม่ได้", en: "Retryable" },
  RECONCILE_REQUIRED: { th: "ต้องตรวจสอบผล", en: "Reconcile" },
  REVIEW_REQUIRED: { th: "ต้องให้ผู้ดูแลตรวจ", en: "Review" },
  SYNCED: { th: "ส่งสำเร็จ", en: "Synced" },
};

function todayBangkok(): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Bangkok"
  }).format(new Date());
}

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency", currency: "THB", minimumFractionDigits: 2
  }).format(value / 100);
}

function dateTime(value: string | null | undefined, locale: Locale): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok"
  }).format(new Date(value));
}

function bangkokDateTimeLocal(value: string | null | undefined): string {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-GB", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Bangkok"
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

function currentBangkokDateTimeLocal(): string {
  return bangkokDateTimeLocal(new Date().toISOString());
}

function paymentSourceText(source: PaymentSource, locale: Locale): string {
  if (source === "CASH") return locale === "th" ? "เงินสด" : "Cash";
  if (source === "BANK_TRANSFER") return locale === "th" ? "โอนธนาคาร" : "Bank transfer";
  return "Beam";
}

export function AccountingOperations({ locale, user }: { locale: Locale; user: User }) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const [items, setItems] = useState<PaymentRow[]>([]);
  const [permissions, setPermissions] = useState({ read: true, sync: false, cashDeposit: false });
  const [summary, setSummary] = useState<ListResponse["summary"]>({ paidGrossSatang: 0, beamGrossSatang: 0, cashGrossSatang: 0, bankTransferGrossSatang: 0, syncedCount: 0, attentionCount: 0 });
  const [historicalCandidates, setHistoricalCandidates] = useState<HistoricalCandidate[]>([]);
  const [historicalTotal, setHistoricalTotal] = useState(0);
  const [historicalError, setHistoricalError] = useState("");
  const [activeHistorical, setActiveHistorical] = useState<HistoricalCandidate | null>(null);
  const [historicalSource, setHistoricalSource] = useState<"CASH" | "BANK_TRANSFER" | "">("");
  const [historicalPaidAt, setHistoricalPaidAt] = useState("");
  const [bankTransferAccounts, setBankTransferAccounts] = useState<BankTransferAccount[]>([]);
  const [historicalBankAccountKey, setHistoricalBankAccountKey] = useState("");
  const [historicalSubmitting, setHistoricalSubmitting] = useState(false);
  const [dateFrom, setDateFrom] = useState(todayBangkok);
  const [dateTo, setDateTo] = useState(todayBangkok);
  const [source, setSource] = useState("ALL");
  const [exportStatus, setExportStatus] = useState("ALL");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [nextToken, setNextToken] = useState<string | null>(null);
  const [pageToken, setPageToken] = useState<string | null>(null);
  const [previousTokens, setPreviousTokens] = useState<Array<string | null>>([]);
  const [run, setRun] = useState<SyncRun | null>(null);
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cashDepositOpen, setCashDepositOpen] = useState(false);
  const [cashDepositId, setCashDepositId] = useState<string | null>(null);
  const [cashPaymentId, setCashPaymentId] = useState<string | null>(null);
  const closeDetailRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ branchId: "branch_001", dateFrom, dateTo, pageSize: "25" });
    if (source !== "ALL") params.set("paymentSource", source);
    if (exportStatus !== "ALL") params.set("exportStatus", exportStatus);
    if (attentionOnly) params.set("requiresAttention", "true");
    if (debouncedQuery.trim()) params.set("search", debouncedQuery.trim());
    if (pageToken) params.set("pageToken", pageToken);
    try {
      const result = await adminApi<ListResponse>(user, `/payments?${params.toString()}`);
      setItems(result.items);
      setSummary(result.summary);
      setPermissions(result.permissions);
      setNextToken(result.nextPageToken ?? null);
      setSelected(new Set());
      if (result.permissions.sync) {
        try {
          const [candidates, options] = await Promise.all([
            adminApi<HistoricalCandidateResponse>(user, "/historical-accounting-candidates?branchId=branch_001"),
            adminApi<{ bankTransferAccounts: BankTransferAccount[] }>(user, "/manual-payment-options"),
          ]);
          setHistoricalCandidates(candidates.items);
          setHistoricalTotal(candidates.total);
          setBankTransferAccounts(options.bankTransferAccounts);
          setHistoricalError("");
        } catch (candidateError) {
          setHistoricalError(candidateError instanceof Error ? candidateError.message : "Historical accounting queue is unavailable");
        }
      } else {
        setHistoricalCandidates([]);
        setHistoricalTotal(0);
        setBankTransferAccounts([]);
      }
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : "";
      setError(locale === "th" ? `โหลดข้อมูลบัญชีไม่สำเร็จ${detail ? `: ${detail}` : ""}` : `Accounting data is unavailable${detail ? `: ${detail}` : ""}`);
    } finally {
      setLoading(false);
    }
  }, [attentionOnly, dateFrom, dateTo, debouncedQuery, exportStatus, locale, pageToken, source, user]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!run || terminalRuns.has(run.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const current = await adminApi<SyncRun>(user, `/accounting-sync-runs/${run.runId}`);
        setRun(current);
        if (terminalRuns.has(current.status)) {
          window.clearInterval(timer);
          await load();
          notify({
            tone: current.status === "COMPLETED" ? "success" : "error",
            title: locale === "th" ? "รอบส่งบัญชีเสร็จแล้ว" : "Accounting run completed",
            message: `${current.syncedCount ?? 0}/${current.enqueuedCount ?? 0}`
          });
        }
      } catch { /* The visible run state remains available for a manual reload. */ }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [load, locale, notify, run, user]);

  useEffect(() => {
    if (!detail) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeDetailRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetail(null);
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = Array.from(drawerRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled])'));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); previousFocusRef.current?.focus(); };
  }, [detail]);

  const selectedRows = useMemo(() => items.filter((item) => selected.has(item.exportId)), [items, selected]);
  const eligibleOnPage = useMemo(() => items.filter((item) => selectableStates.has(item.exportStatus)), [items]);

  const startRun = async (exportIds?: string[]) => {
    const selectedDates = exportIds
      ? [...new Set(items.filter((item) => exportIds.includes(item.exportId)).map((item) => item.accountingDate))]
      : [];
    const scopeText = exportIds
      ? locale === "th" ? `${exportIds.length} รายการที่เลือก • วันที่บัญชี ${selectedDates.join(", ")}` : `${exportIds.length} selected records • accounting date ${selectedDates.join(", ")}`
      : locale === "th" ? "backlog ที่ถึงกำหนดจากวันก่อนหน้าและเก่ากว่า สูงสุด 100 รายการ" : "up to 100 due backlog records from the previous business date and older";
    const confirmed = await requestConfirmation({
      title: locale === "th" ? "ยืนยันส่งข้อมูลไป FlowAccount?" : "Sync to FlowAccount?",
      message: locale === "th" ? `${scopeText} จะเข้าคิวแบบ asynchronous และไม่สร้างซ้ำจากรายการที่ส่งสำเร็จแล้ว` : `${scopeText} will be queued asynchronously. Synced records cannot be created again.`,
      confirmLabel: locale === "th" ? "ยืนยันเข้าคิว" : "Queue sync",
      cancelLabel: locale === "th" ? "ยกเลิก" : "Cancel"
    });
    if (!confirmed.confirmed) return;
    try {
      const body = exportIds ? { exportIds } : { filter: { branchId: "branch_001" } };
      const accepted = await adminApi<SyncRun>(user, "/accounting-sync-runs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(body)
      });
      setRun(accepted);
      notify({ tone: "info", title: locale === "th" ? "รับคำสั่งแล้ว" : "Run accepted", message: locale === "th" ? "ระบบกำลังส่งข้อมูลไป FlowAccount" : "FlowAccount sync is now in progress" });
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "เข้าคิวไม่สำเร็จ" : "Could not queue sync", message: caught instanceof Error ? caught.message : undefined });
    }
  };

  const exportAction = async (row: PaymentRow, action: "retry" | "reconcile") => {
    const reference = `${row.bookingId} • ${locale === "th" ? "วันที่บัญชี" : "accounting date"} ${row.accountingDate}`;
    const confirmed = await requestConfirmation({
      title: action === "retry" ? (locale === "th" ? "ลองส่งรายการนี้อีกครั้ง?" : "Retry this export?") : (locale === "th" ? "ตรวจสอบผลกับ FlowAccount?" : "Reconcile with FlowAccount?"),
      message: action === "retry" ? reference : `${reference} • ${locale === "th" ? "ระบบจะค้นหาเอกสารเดิมก่อน และจะไม่ POST ซ้ำโดยไม่ตรวจสอบ" : "The worker searches for the existing document and will not blindly POST again."}`,
      confirmLabel: locale === "th" ? "ยืนยัน" : "Confirm",
      cancelLabel: locale === "th" ? "ยกเลิก" : "Cancel"
    });
    if (!confirmed.confirmed) return;
    try {
      const accepted = await adminApi<SyncRun>(user, `/accounting-exports/${row.exportId}:${action}`, {
        method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }
      });
      setRun(accepted);
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "ดำเนินการไม่สำเร็จ" : "Action failed", message: caught instanceof Error ? caught.message : undefined });
    }
  };

  const openDetail = async (row: PaymentRow) => {
    setDetailLoading(true);
    try { setDetail(await adminApi<DetailResponse>(user, `/payments/${row.paymentId}`)); }
    catch (caught) { notify({ tone: "error", title: locale === "th" ? "เปิดรายละเอียดไม่สำเร็จ" : "Detail unavailable", message: caught instanceof Error ? caught.message : undefined }); }
    finally { setDetailLoading(false); }
  };

  const toggleAll = () => setSelected(selected.size === eligibleOnPage.length ? new Set() : new Set(eligibleOnPage.map((item) => item.exportId)));
  const toggleOne = (id: string) => setSelected((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const resetPage = () => { setPageToken(null); setPreviousTokens([]); };
  const openCashDeposit = (options: { depositId?: string | null; paymentId?: string | null } = {}) => {
    setCashDepositId(options.depositId ?? null);
    setCashPaymentId(options.paymentId ?? null);
    setCashDepositOpen(true);
  };
  const openHistoricalClassification = (candidate: HistoricalCandidate) => {
    setActiveHistorical(candidate);
    setHistoricalSource("");
    setHistoricalBankAccountKey("");
    setHistoricalPaidAt(bangkokDateTimeLocal(candidate.suggestedPaidAt || candidate.serviceAt));
  };
  const classifyHistorical = async () => {
    if (!activeHistorical || !historicalSource || !historicalPaidAt) return;
    if (historicalSource === "BANK_TRANSFER" && !historicalBankAccountKey) return;
    if (historicalPaidAt > currentBangkokDateTimeLocal()) {
      notify({ tone: "error", title: locale === "th" ? "วันเวลารับเงินไม่ถูกต้อง" : "Invalid payment time", message: locale === "th" ? "วันและเวลาที่ได้รับเงินต้องไม่เป็นอนาคต" : "Payment received time cannot be in the future." });
      return;
    }
    const confirmed = await requestConfirmation({
      title: locale === "th" ? "ยืนยันการรับเงินย้อนหลัง?" : "Confirm historical payment?",
      message: locale === "th"
        ? `${activeHistorical.bookingId} • ${paymentSourceText(historicalSource, locale)}${historicalSource === "BANK_TRANSFER" ? ` • ${bankTransferAccounts.find((account) => account.key === historicalBankAccountKey)?.labelTh ?? "—"}` : ""} • ${baht(activeHistorical.grossAmountSatang, locale)} ระบบจะสร้างรายการชำระและคิวส่ง FlowAccount โดยไม่สร้างรายการซ้ำ`
        : `${activeHistorical.bookingId} • ${paymentSourceText(historicalSource, locale)}${historicalSource === "BANK_TRANSFER" ? ` • ${bankTransferAccounts.find((account) => account.key === historicalBankAccountKey)?.labelEn ?? "—"}` : ""} • ${baht(activeHistorical.grossAmountSatang, locale)}. A payment and FlowAccount export queue will be created without duplicating existing records.`,
      confirmLabel: locale === "th" ? "ยืนยันและลงบัญชี" : "Confirm and account",
      cancelLabel: locale === "th" ? "กลับไปตรวจสอบ" : "Review again",
    });
    if (!confirmed.confirmed) return;
    setHistoricalSubmitting(true);
    try {
      await adminApi(user, `/historical-accounting-candidates/${encodeURIComponent(activeHistorical.bookingId)}:record`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          paymentSource: historicalSource,
          paidAt: `${historicalPaidAt}:00+07:00`,
          bankAccountKey: historicalSource === "BANK_TRANSFER" ? historicalBankAccountKey : null,
          expectedVersion: activeHistorical.version,
          confirmed: true,
        }),
      });
      notify({ tone: "success", title: locale === "th" ? "ลงบัญชีรายการย้อนหลังแล้ว" : "Historical payment recorded", message: activeHistorical.bookingId });
      setActiveHistorical(null);
      await load();
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "ลงบัญชีไม่สำเร็จ" : "Could not record payment", message: caught instanceof Error ? caught.message : undefined });
    } finally {
      setHistoricalSubmitting(false);
    }
  };

  return <main className="dashboard-content accounting-page">
    <div className="module-heading-action">
      <div className="module-heading"><p className="eyebrow">PAYMENTS • FLOWACCOUNT • ASIA/BANGKOK</p><h1>{locale === "th" ? "การชำระเงินและบัญชี" : "Payments & Accounting"}</h1><p>{locale === "th" ? "ตรวจสอบยอดรับ สถานะเงินสด และส่ง Cash Invoice แบบ VAT รวม 7%" : "Review customer payments, cash settlement, and VAT-inclusive Cash Invoice sync."}</p></div>
      <div className="accounting-heading-actions">
        {permissions.sync && <button className="accounting-secondary-action" type="button" disabled={loading || Boolean(run && !terminalRuns.has(run.status))} onClick={() => { void startRun(); }}>{locale === "th" ? "ส่ง FlowAccount backlog" : "Run FlowAccount backlog"}</button>}
        <button className="new-booking" type="button" disabled={loading || !permissions.cashDeposit} title={!permissions.cashDeposit ? (locale === "th" ? "ยังไม่เปิด Cash Deposit configuration ใน environment นี้" : "Cash Deposit configuration is not enabled in this environment") : undefined} onClick={() => openCashDeposit()}>{locale === "th" ? "นำเงินสดเข้าบัญชี" : "Deposit cash"}</button>
      </div>
    </div>

    {run && <section className={`accounting-run ${run.status === "PARTIAL_FAILURE" ? "warning" : ""}`} aria-live="polite"><div><strong>{locale === "th" ? "รอบส่งบัญชี" : "Accounting run"}</strong></div><div><span>{run.status}</span><strong>{run.processedCount ?? 0}/{run.enqueuedCount ?? run.selectedCount ?? 0}</strong></div></section>}

    {permissions.sync && (historicalCandidates.length > 0 || historicalError) && <section className="module-panel historical-accounting-queue" aria-labelledby="historical-accounting-title">
      <div className="historical-accounting-heading"><div><p className="eyebrow">HISTORICAL • PAYMENT CLASSIFICATION</p><h2 id="historical-accounting-title">{locale === "th" ? "รายการย้อนหลังที่รอลงบัญชี" : "Historical records awaiting accounting"}</h2><p>{locale === "th" ? "รายการเหล่านี้ยังไม่มี Payment และไม่เคยสร้าง FlowAccount จากระบบ กรุณาตรวจหลักฐานแล้วเลือกช่องทางรับเงินจริง" : "These records have no Payment and were never exported by this system. Verify the evidence, then choose the actual payment source."}</p></div><strong>{historicalTotal}</strong></div>
      {historicalError && <div className="module-state error" role="alert">{historicalError}</div>}
      <div className="historical-accounting-list">{historicalCandidates.map((candidate) => <article key={candidate.bookingId} className={activeHistorical?.bookingId === candidate.bookingId ? "active" : undefined}>
        <div className="historical-accounting-record"><div><strong>{dateTime(candidate.serviceAt, locale)}</strong><small>{candidate.bookingId}</small></div><div><strong>{candidate.customerName}</strong><small>{candidate.serviceSummary} · {candidate.pax} pax</small></div><div><strong>{baht(candidate.grossAmountSatang, locale)}</strong><small>{locale === "th" ? "บริการ" : "Service"} {baht(candidate.serviceAmountSatang, locale)} · {locale === "th" ? "ทิป" : "Tip"} {baht(candidate.tipAmountSatang, locale)}</small>{!candidate.eligible && <small className="historical-accounting-blocked">{locale === "th" ? "ต้องแก้ยอด Booking ให้มากกว่า 0 บาทก่อน" : "Correct the Booking to a positive amount first"}</small>}</div><button type="button" disabled={!candidate.eligible} title={!candidate.eligible ? (locale === "th" ? "รายการยอด 0 บาทยังลงบัญชีไม่ได้" : "A zero-value record cannot be accounted") : undefined} onClick={() => openHistoricalClassification(candidate)}>{locale === "th" ? "ตรวจและลงบัญชี" : "Review & account"}</button></div>
        {activeHistorical?.bookingId === candidate.bookingId && <div className="historical-accounting-form"><fieldset><legend>{locale === "th" ? "ช่องทางที่ได้รับเงินจริง" : "Payment received via"}</legend><label><input type="radio" name={`source-${candidate.bookingId}`} checked={historicalSource === "CASH"} onChange={() => { setHistoricalSource("CASH"); setHistoricalBankAccountKey(""); }} /> {locale === "th" ? "เงินสด" : "Cash"}</label><label title={!bankTransferAccounts.length ? (locale === "th" ? "Environment นี้ยังไม่มีบัญชี FlowAccount ที่เปิดใช้" : "No FlowAccount bank account is enabled in this environment") : undefined}><input type="radio" name={`source-${candidate.bookingId}`} disabled={!bankTransferAccounts.length} checked={historicalSource === "BANK_TRANSFER"} onChange={() => setHistoricalSource("BANK_TRANSFER")} /> {locale === "th" ? "โอนธนาคาร" : "Bank transfer"}</label></fieldset>{historicalSource === "BANK_TRANSFER" && <label><span>{locale === "th" ? "บัญชีที่รับเงิน" : "Receiving account"}</span><select value={historicalBankAccountKey} onChange={(event) => setHistoricalBankAccountKey(event.target.value)}><option value="">— {locale === "th" ? "เลือกบัญชี" : "Choose an account"} —</option>{bankTransferAccounts.map((account) => <option key={account.key} value={account.key}>{locale === "th" ? account.labelTh : account.labelEn}</option>)}</select></label>}<label><span>{locale === "th" ? "วันที่และเวลาที่ได้รับเงิน" : "Payment received at"}</span><input type="datetime-local" max={currentBangkokDateTimeLocal()} value={historicalPaidAt} onChange={(event) => setHistoricalPaidAt(event.target.value)} /></label><div><button type="button" onClick={() => setActiveHistorical(null)}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button className="primary-compact-button" type="button" disabled={!historicalSource || !historicalPaidAt || (historicalSource === "BANK_TRANSFER" && !historicalBankAccountKey) || historicalSubmitting} onClick={() => { void classifyHistorical(); }}>{historicalSubmitting ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "ยืนยันและลงบัญชี" : "Confirm and account")}</button></div></div>}
      </article>)}</div>
    </section>}

    <section className="accounting-summary" aria-label={locale === "th" ? "สรุปยอดในหน้าปัจจุบัน" : "Current page summary"}>
      <div><span>{locale === "th" ? "ยอดรับรวมในหน้านี้" : "Page gross"}</span><strong>{baht(summary.paidGrossSatang, locale)}</strong></div>
      <div><span>Beam</span><strong>{baht(summary.beamGrossSatang, locale)}</strong></div>
      <div><span>{locale === "th" ? "เงินสด" : "Cash"}</span><strong>{baht(summary.cashGrossSatang, locale)}</strong></div>
      <div><span>{locale === "th" ? "โอนธนาคาร" : "Bank transfer"}</span><strong>{baht(summary.bankTransferGrossSatang, locale)}</strong></div>
      <div><span>{locale === "th" ? "ส่งสำเร็จ / ต้องตรวจ" : "Synced / Attention"}</span><strong>{summary.syncedCount} / {summary.attentionCount}</strong></div>
    </section>

    <section className="module-panel accounting-filters" aria-label={locale === "th" ? "ตัวกรองรายการชำระเงิน" : "Payment filters"}>
      <div className="accounting-filter-grid">
        <label>{locale === "th" ? "จากวันที่" : "From"}<input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); resetPage(); }} /></label>
        <label>{locale === "th" ? "ถึงวันที่" : "To"}<input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); resetPage(); }} /></label>
        <label>{locale === "th" ? "ช่องทาง" : "Source"}<select value={source} onChange={(event) => { setSource(event.target.value); resetPage(); }}><option value="ALL">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="BEAM">Beam</option><option value="CASH">{locale === "th" ? "เงินสด" : "Cash"}</option><option value="BANK_TRANSFER">{locale === "th" ? "โอนธนาคาร" : "Bank transfer"}</option></select></label>
        <label>FlowAccount<select value={exportStatus} onChange={(event) => { setExportStatus(event.target.value); resetPage(); }}><option value="ALL">{locale === "th" ? "ทุกสถานะ" : "All statuses"}</option>{Object.entries(statusText).map(([value, label]) => <option value={value} key={value}>{label[locale]}</option>)}</select></label>
        <label className="accounting-search">{locale === "th" ? "Booking / ลูกค้า" : "Booking / customer"}<input value={query} maxLength={100} onChange={(event) => { setQuery(event.target.value); resetPage(); }} placeholder={locale === "th" ? "ค้นหา Booking, ชื่อ หรือเบอร์ที่ปกปิด" : "Search booking, name, or masked phone"} /></label>
        <label className="attention-toggle"><input type="checkbox" checked={attentionOnly} onChange={(event) => { setAttentionOnly(event.target.checked); resetPage(); }} />{locale === "th" ? "เฉพาะรายการที่ต้องตรวจ" : "Requires attention"}</label>
      </div>
    </section>

    {error && <div className="module-state error" role="alert">{error}</div>}
    <section className="operations-panel accounting-table-panel" aria-labelledby="accounting-table-title">
      <div className="table-toolbar"><div><h2 id="accounting-table-title">{locale === "th" ? "รายการรับชำระ" : "Customer payments"}</h2><p>{items.length} {locale === "th" ? "รายการ • สรุปด้านบนเป็นยอดของหน้านี้" : "records • summary reflects this page"}</p></div>{permissions.sync && <button className="primary-compact-button" type="button" disabled={!selectedRows.length} onClick={() => { void startRun(selectedRows.map((item) => item.exportId)); }}>{locale === "th" ? `ส่งที่เลือก (${selectedRows.length})` : `Sync selected (${selectedRows.length})`}</button>}</div>
      <div className="table-scroll" aria-busy={loading}>
        <table className="accounting-table">
          <thead><tr><th><input type="checkbox" aria-label={locale === "th" ? "เลือกทุกรายการที่ส่งได้" : "Select all eligible rows"} checked={eligibleOnPage.length > 0 && selected.size === eligibleOnPage.length} onChange={toggleAll} /></th><th>{locale === "th" ? "วันที่ / Booking" : "Date / Booking"}</th><th>{locale === "th" ? "ลูกค้า / บริการ" : "Customer / service"}</th><th>{locale === "th" ? "ยอดรับ" : "Amount"}</th><th>{locale === "th" ? "การชำระ" : "Payment"}</th><th>FlowAccount</th><th>{locale === "th" ? "เงินสดเข้าบัญชี" : "Cash settlement"}</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{items.map((row) => <tr key={row.exportId} className={attentionStates.has(row.exportStatus) ? "attention-row" : undefined}>
            <td><input type="checkbox" aria-label={`${locale === "th" ? "เลือก" : "Select"} ${row.bookingId}`} checked={selected.has(row.exportId)} disabled={!permissions.sync || !selectableStates.has(row.exportStatus)} onChange={() => toggleOne(row.exportId)} /></td>
            <td><strong>{dateTime(row.serviceAt || row.paidAt, locale)}</strong><small>{row.bookingId}</small></td>
            <td><strong>{row.customerName}</strong><small>{row.customerPhoneMasked}</small><span className="accounting-service">{row.serviceSummary} · {row.pax} pax</span>{row.historicalFinancialRecord && <span className="historical-payment-badge">{locale === "th" ? "บันทึกย้อนหลัง" : "Historical"}</span>}</td>
            <td><strong>{baht(row.grossAmountSatang, locale)}</strong><small>{locale === "th" ? "บริการ" : "Service"} {baht(row.serviceAmountSatang, locale)} · {locale === "th" ? "ทิป" : "Tip"} {baht(row.tipAmountSatang, locale)}</small></td>
            <td><span className={`payment-source source-${row.paymentSource.toLowerCase()}`}>{paymentSourceText(row.paymentSource, locale)}</span>{row.bankAccountLabel && <small>{row.bankAccountLabel}</small>}<small>{dateTime(row.paidAt, locale)}</small></td>
            <td><span className={`accounting-status accounting-status-${row.exportStatus.toLowerCase()}`}>{statusText[row.exportStatus][locale]}</span>{row.flowAccountDocumentSerial && <small>{row.flowAccountDocumentSerial}</small>}{row.lastErrorCode && <small className="accounting-error-code">{row.lastErrorCode}</small>}</td>
            <td><span>{row.paymentSource === "CASH" ? row.cashSettlementStatus : (locale === "th" ? "ไม่เกี่ยวข้อง" : "N/A")}</span></td>
            <td><div className="accounting-row-actions"><button type="button" disabled={detailLoading} onClick={() => { void openDetail(row); }} aria-label={`${locale === "th" ? "รายละเอียด" : "Details"} ${row.bookingId}`}>→</button>{permissions.cashDeposit && row.paymentSource === "CASH" && row.cashSettlementStatus === "UNSETTLED" && <button type="button" onClick={() => openCashDeposit({ paymentId: row.paymentId })}>{locale === "th" ? "รวมยอด" : "Deposit"}</button>}{permissions.cashDeposit && row.paymentSource === "CASH" && row.cashDepositId && <button type="button" onClick={() => openCashDeposit({ depositId: row.cashDepositId })}>{locale === "th" ? "ดูชุด" : "Batch"}</button>}{permissions.sync && row.exportStatus === "READY" && <button type="button" onClick={() => { void startRun([row.exportId]); }}>{locale === "th" ? "ส่ง" : "Sync"}</button>}{permissions.sync && row.exportStatus === "RETRYABLE" && <button type="button" onClick={() => { void exportAction(row, "retry"); }}>{locale === "th" ? "ลองใหม่" : "Retry"}</button>}{permissions.sync && row.exportStatus === "RECONCILE_REQUIRED" && <button type="button" onClick={() => { void exportAction(row, "reconcile"); }}>{locale === "th" ? "ตรวจผล" : "Reconcile"}</button>}</div></td>
          </tr>)}</tbody>
        </table>
      </div>
      {loading && <div className="accounting-skeleton" role="status">{locale === "th" ? "กำลังโหลดรายการชำระเงิน…" : "Loading payments…"}</div>}
      {!loading && !items.length && !error && <div className="empty-state">{locale === "th" ? "ไม่พบรายการรับชำระในช่วงนี้" : "No customer payments in this range"}</div>}
      <nav className="booking-pagination" aria-label={locale === "th" ? "เปลี่ยนหน้ารายการบัญชี" : "Accounting pagination"}><p role="status">{locale === "th" ? "เรียงตามเวลาชำระล่าสุด" : "Newest paid first"}</p><div><button type="button" disabled={!previousTokens.length || loading} onClick={() => { const tokens = [...previousTokens]; setPageToken(tokens.pop() ?? null); setPreviousTokens(tokens); }}>← {locale === "th" ? "ก่อนหน้า" : "Previous"}</button><button type="button" disabled={!nextToken || loading} onClick={() => { setPreviousTokens((values) => [...values, pageToken]); setPageToken(nextToken); }}>{locale === "th" ? "ถัดไป" : "Next"} →</button></div></nav>
    </section>

    {detail && <><div className="accounting-scrim" aria-hidden="true" onClick={() => setDetail(null)} /><aside ref={drawerRef} className="detail-drawer accounting-detail" role="dialog" aria-modal="true" aria-labelledby="accounting-detail-title"><div className="drawer-header"><div><p className="eyebrow">{detail.payment.bookingId}</p><h2 id="accounting-detail-title">{locale === "th" ? "รายละเอียดบัญชี" : "Accounting detail"}</h2></div><button ref={closeDetailRef} type="button" aria-label={locale === "th" ? "ปิดรายละเอียด" : "Close detail"} onClick={() => setDetail(null)}>×</button></div><dl><div><dt>FlowAccount</dt><dd>{statusText[detail.payment.exportStatus][locale]}<small>{detail.payment.flowAccountDocumentSerial || "—"}</small></dd></div><div><dt>{locale === "th" ? "ความพยายาม" : "Attempts"}</dt><dd>{detail.payment.attemptCount}</dd></div><div><dt>{locale === "th" ? "ยอดรับ" : "Gross"}</dt><dd>{baht(detail.payment.grossAmountSatang, locale)}</dd></div>{detail.payment.bankAccountLabel && <div><dt>{locale === "th" ? "บัญชีที่รับเงิน" : "Receiving account"}</dt><dd>{detail.payment.bankAccountLabel}</dd></div>}<div><dt>{locale === "th" ? "เงินสดเข้าบัญชี" : "Cash settlement"}</dt><dd>{detail.payment.cashSettlementStatus}</dd></div></dl>{detail.payment.flowAccountDocumentUrl && <a className="accounting-document-link" href={detail.payment.flowAccountDocumentUrl} target="_blank" rel="noopener noreferrer">{locale === "th" ? "เปิดเอกสารใน FlowAccount ↗" : "Open in FlowAccount ↗"}</a>}<section className="attempt-list" aria-label={locale === "th" ? "ประวัติการส่ง" : "Sync attempts"}><h3>{locale === "th" ? "ประวัติการส่ง" : "Sync attempts"}</h3>{detail.attempts.length ? detail.attempts.map((attempt, index) => <div key={String(attempt.attemptId ?? index)}><strong>{String(attempt.result ?? "—")}</strong><span>{String(attempt.safeErrorCode ?? attempt.operation ?? "—")}</span></div>) : <p>{locale === "th" ? "ยังไม่มีการส่ง" : "No attempts yet"}</p>}</section></aside></>}
    {cashDepositOpen && <CashDepositWorkflow locale={locale} user={user} initialDepositId={cashDepositId} initialPaymentId={cashPaymentId} onClose={() => setCashDepositOpen(false)} onChanged={load} />}
  </main>;
}
