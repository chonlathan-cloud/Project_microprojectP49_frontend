"use client";

import type { Locale } from "@spa/shared-types";
import type { User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { adminApi } from "@/lib/admin-api";

export type CompensationTab = "TODAY" | "LEDGER" | "PROFILES";

type DayRow = {
  localDate: string;
  present: boolean;
  attendanceVersion: number;
  guaranteeRateSatang: number;
  guaranteeTopUpSatang: number;
};

type CompensationRow = {
  therapistId: string;
  therapistName: string;
  active: boolean;
  profileVersion: number;
  dailyGuaranteeSatang: number;
  guaranteeEffectiveFrom: string | null;
  attendedDays: number;
  serviceCount: number;
  durationMinutes: number;
  servicePaySatang: number;
  tipSatang: number;
  guaranteeTopUpSatang: number;
  shopAdjustmentSatang: number;
  shopSourceSatang: number;
  totalEarnedSatang: number;
  paidSatang: number;
  outstandingSatang: number;
  payoutState: "UNPAID" | "PARTIAL" | "PAID";
  days: DayRow[];
};

type CompensationEntry = {
  entryId: string;
  source: "SERVICE" | "SHOP";
  kind: "SERVICE_ALLOCATION" | "GUARANTEE_TOP_UP" | "BONUS" | "ADJUSTMENT";
  localDate: string;
  therapistId: string;
  therapistName: string;
  amountSatang: number;
  tipSatang: number;
  bookingId?: string;
  bookingLineItemId?: string;
  serviceNameTh?: string;
  serviceNameEn?: string;
  durationMinutes?: number;
  reason?: string;
  version?: number;
  editable: boolean;
  lockedReason?: "PAID";
};

type CompensationPayload = {
  dateFrom: string;
  dateTo: string;
  summary: CompensationRow[];
  entries: CompensationEntry[];
  payouts: Array<{
    payoutId: string;
    therapistId: string;
    therapistName: string;
    dateFrom: string;
    dateTo: string;
    amountSatang: number;
    paymentMethod: "CASH" | "TRANSFER";
    note?: string;
    paidAt?: string;
  }>;
  totals: {
    servicePaySatang: number;
    shopSourceSatang: number;
    tipSatang: number;
    totalEarnedSatang: number;
    paidSatang: number;
    outstandingSatang: number;
  };
};

type SettlementAllocation = {
  bookingLineItemId: string;
  participantId: string;
  participantName: string;
  therapistId: string | null;
  therapistPaySatang: number;
  tipShareSatang: number;
};

type Settlement = {
  version: number;
  allocations: SettlementAllocation[];
};

type Editor =
  | { kind: "CREATE_ADJUSTMENT"; row: CompensationRow }
  | { kind: "EDIT_ADJUSTMENT"; entry: CompensationEntry }
  | { kind: "EDIT_SERVICE"; entry: CompensationEntry; settlement: Settlement }
  | { kind: "EDIT_PROFILE"; row: CompensationRow }
  | { kind: "PAYOUT"; row: CompensationRow };

function bangkokToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Bangkok",
  }).format(new Date());
}

function daysBefore(value: string, days: number): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() - days);
  return parsed.toISOString().slice(0, 10);
}

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

function dateLabel(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Bangkok",
  }).format(new Date(`${value}T12:00:00+07:00`));
}

function payoutLabel(value: CompensationRow["payoutState"], locale: Locale): string {
  const labels = {
    UNPAID: { th: "ยังไม่จ่าย", en: "Unpaid" },
    PARTIAL: { th: "จ่ายบางส่วน", en: "Partially paid" },
    PAID: { th: "จ่ายแล้ว", en: "Paid" },
  };
  return labels[value][locale];
}

function entryKindLabel(entry: CompensationEntry, locale: Locale): string {
  const labels = {
    SERVICE_ALLOCATION: { th: "ค่ามือจากบริการ", en: "Service allocation" },
    GUARANTEE_TOP_UP: { th: "เติมค่าประกันมือ", en: "Guarantee top-up" },
    BONUS: { th: "โบนัสจากร้าน", en: "Shop bonus" },
    ADJUSTMENT: { th: "รายการปรับปรุง", en: "Adjustment" },
  };
  return labels[entry.kind][locale];
}

function CompensationEditor({
  editor,
  locale,
  saving,
  onClose,
  onSubmit,
}: {
  editor: Editor;
  locale: Locale;
  saving: boolean;
  onClose: () => void;
  onSubmit: (values: { amountBaht: number; tipBaht: number; reason: string; effectiveFrom: string; adjustmentKind: "BONUS" | "ADJUSTMENT"; paymentMethod: "CASH" | "TRANSFER" }) => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const source = "row" in editor ? editor.row : editor.entry;
  const initialAmount = editor.kind === "EDIT_PROFILE"
    ? editor.row.dailyGuaranteeSatang
    : editor.kind === "PAYOUT"
      ? editor.row.outstandingSatang
      : editor.kind === "CREATE_ADJUSTMENT"
        ? 0
        : editor.entry.amountSatang;
  const initialTip = editor.kind === "EDIT_SERVICE" ? editor.entry.tipSatang : 0;
  const [amount, setAmount] = useState(String(initialAmount / 100));
  const [tip, setTip] = useState(String(initialTip / 100));
  const [reason, setReason] = useState(editor.kind === "EDIT_ADJUSTMENT" ? editor.entry.reason ?? "" : "");
  const [effectiveFrom, setEffectiveFrom] = useState(editor.kind === "EDIT_PROFILE" ? editor.row.guaranteeEffectiveFrom ?? bangkokToday() : bangkokToday());
  const [adjustmentKind, setAdjustmentKind] = useState<"BONUS" | "ADJUSTMENT">(editor.kind === "EDIT_ADJUSTMENT" && editor.entry.kind === "BONUS" ? "BONUS" : "ADJUSTMENT");
  const [paymentMethod, setPaymentMethod] = useState<"CASH" | "TRANSFER">("TRANSFER");
  const amountNumber = Number(amount);
  const tipNumber = Number(tip);
  const valid = Number.isSafeInteger(amountNumber)
    && (editor.kind === "CREATE_ADJUSTMENT" || editor.kind === "EDIT_ADJUSTMENT" ? amountNumber !== 0 : amountNumber >= 0)
    && Number.isSafeInteger(tipNumber)
    && tipNumber >= 0
    && (editor.kind === "PAYOUT" || reason.trim().length > 0)
    && reason.length <= 300
    && Boolean(effectiveFrom);

  useEffect(() => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.requestAnimationFrame(() => closeRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => { document.removeEventListener("keydown", handleKeyDown); previousFocus.current?.focus(); };
  }, [onClose, saving]);

  const title = editor.kind === "CREATE_ADJUSTMENT" ? (locale === "th" ? "เพิ่มรายการจากร้าน" : "Add shop entry")
    : editor.kind === "EDIT_ADJUSTMENT" ? (locale === "th" ? "แก้รายการจากร้าน" : "Edit shop entry")
      : editor.kind === "EDIT_SERVICE" ? (locale === "th" ? "แก้ค่ามือจากบริการ" : "Edit service pay")
        : editor.kind === "EDIT_PROFILE" ? (locale === "th" ? "แก้ค่าประกันมือ" : "Edit guarantee")
          : (locale === "th" ? "บันทึกจ่ายเงินให้หมอ" : "Record therapist payout");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || saving) return;
    await onSubmit({ amountBaht: amountNumber, tipBaht: tipNumber, reason: reason.trim(), effectiveFrom, adjustmentKind, paymentMethod });
  }

  return <div className="modal-backdrop compensation-editor-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
    <div ref={dialogRef} className="compensation-editor" role="dialog" aria-modal="true" aria-labelledby="compensation-editor-title">
      <div className="drawer-header start-service-header"><div><p className="eyebrow">THERAPIST COMPENSATION</p><h2 id="compensation-editor-title">{title}</h2><p>{source.therapistName}</p></div><button ref={closeRef} type="button" disabled={saving} aria-label={locale === "th" ? "ปิดหน้าต่าง" : "Close dialog"} onClick={onClose}>×</button></div>
      <form onSubmit={submit}>
        <div className="compensation-editor-body">
          {editor.kind === "PAYOUT" && <div className="compensation-payout-due"><span>{locale === "th" ? "ยอดค้างจ่ายในช่วงที่เลือก" : "Outstanding in selected period"}</span><strong>{baht(editor.row.outstandingSatang, locale)}</strong></div>}
          {(editor.kind === "CREATE_ADJUSTMENT" || editor.kind === "EDIT_ADJUSTMENT") && <label><span>{locale === "th" ? "ประเภทรายการจากร้าน" : "Shop entry type"}</span><select value={adjustmentKind} disabled={saving} onChange={(event) => setAdjustmentKind(event.target.value as "BONUS" | "ADJUSTMENT")}><option value="BONUS">{locale === "th" ? "โบนัส" : "Bonus"}</option><option value="ADJUSTMENT">{locale === "th" ? "ปรับเพิ่ม/ลด" : "Adjustment"}</option></select></label>}
          {editor.kind !== "PAYOUT" && <label><span>{editor.kind === "EDIT_PROFILE" ? (locale === "th" ? "ค่าประกันมือต่อวัน (บาท)" : "Daily guarantee (THB)") : (locale === "th" ? "จำนวนเงิน (บาท)" : "Amount (THB)")}</span><input type="number" step="1" min={editor.kind === "CREATE_ADJUSTMENT" || editor.kind === "EDIT_ADJUSTMENT" ? undefined : 0} required value={amount} disabled={saving} onChange={(event) => setAmount(event.target.value)} /></label>}
          {editor.kind === "EDIT_SERVICE" && <label><span>{locale === "th" ? "ส่วนแบ่งทิปของหมอ (บาท)" : "Therapist tip share (THB)"}</span><input type="number" min="0" step="1" required value={tip} disabled={saving} onChange={(event) => setTip(event.target.value)} /></label>}
          {editor.kind === "EDIT_PROFILE" && <label><span>{locale === "th" ? "เริ่มใช้ตั้งแต่" : "Effective from"}</span><input type="date" required value={effectiveFrom} disabled={saving} onChange={(event) => setEffectiveFrom(event.target.value)} /></label>}
          {editor.kind === "PAYOUT" && <label><span>{locale === "th" ? "วิธีจ่าย" : "Payment method"}</span><select value={paymentMethod} disabled={saving} onChange={(event) => setPaymentMethod(event.target.value as "CASH" | "TRANSFER")}><option value="TRANSFER">{locale === "th" ? "โอนเงิน" : "Transfer"}</option><option value="CASH">{locale === "th" ? "เงินสด" : "Cash"}</option></select></label>}
          <label><span>{editor.kind === "PAYOUT" ? (locale === "th" ? "หมายเหตุ (ไม่บังคับ)" : "Note (optional)") : (locale === "th" ? "เหตุผลการแก้ไข" : "Reason")}</span><textarea rows={3} required={editor.kind !== "PAYOUT"} maxLength={300} value={reason} disabled={saving} onChange={(event) => setReason(event.target.value)} /></label>
          {editor.kind === "PAYOUT" && <p className="compensation-editor-note">{locale === "th" ? "ระบบจะบันทึกจ่ายยอดค้างทั้งหมดของช่วงวันที่ที่เลือก รายการที่จ่ายแล้วจะแก้ทับไม่ได้" : "The entire outstanding balance for the selected period will be recorded. Paid entries cannot be overwritten."}</p>}
        </div>
        <div className="start-service-actions"><button type="button" disabled={saving} onClick={onClose}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button type="submit" className="confirm-button" disabled={!valid || saving}>{saving ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : (locale === "th" ? "ยืนยันและบันทึก" : "Confirm & save")}</button></div>
      </form>
    </div>
  </div>;
}

export function TherapistCompensationWorkspace({ tab, locale, user }: { tab: CompensationTab; locale: Locale; user: User }) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const today = bangkokToday();
  const [dateFrom, setDateFrom] = useState(tab === "TODAY" || tab === "PROFILES" ? today : daysBefore(today, 6));
  const [dateTo, setDateTo] = useState(today);
  const [payload, setPayload] = useState<CompensationPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<"ALL" | "SERVICE" | "SHOP">("ALL");
  const [therapistFilter, setTherapistFilter] = useState("ALL");
  const [editor, setEditor] = useState<Editor | null>(null);
  const closeEditor = useCallback(() => setEditor(null), []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await adminApi<CompensationPayload>(user, `/therapist-compensation?dateFrom=${encodeURIComponent(dateFrom)}&dateTo=${encodeURIComponent(dateTo)}&branchId=branch_001`);
      setPayload(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Therapist compensation unavailable");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, user]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  const filteredEntries = useMemo(() => (payload?.entries ?? []).filter((entry) =>
    (sourceFilter === "ALL" || entry.source === sourceFilter)
    && (therapistFilter === "ALL" || entry.therapistId === therapistFilter)), [payload, sourceFilter, therapistFilter]);

  async function markAttendance(row: CompensationRow, present: boolean) {
    const day = row.days.find((item) => item.localDate === dateFrom);
    setSaving(true);
    try {
      await adminApi(user, `/therapist-compensation/attendance/${encodeURIComponent(row.therapistId)}/${dateFrom}?branchId=branch_001`, { method: "PUT", body: JSON.stringify({ present, expectedVersion: day?.attendanceVersion ?? 0 }) });
      notify({ tone: "success", title: present ? (locale === "th" ? "บันทึกมาทำงานแล้ว" : "Attendance recorded") : (locale === "th" ? "ยกเลิกการมาทำงานแล้ว" : "Attendance removed"), message: row.therapistName });
      await load();
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "บันทึกเวลาเข้างานไม่สำเร็จ" : "Attendance update failed", message: caught instanceof Error ? caught.message : undefined });
    } finally { setSaving(false); }
  }

  async function openServiceEditor(entry: CompensationEntry) {
    if (!entry.bookingId) return;
    setSaving(true);
    try {
      const settlement = await adminApi<Settlement>(user, `/bookings/${encodeURIComponent(entry.bookingId)}/settlement`);
      setEditor({ kind: "EDIT_SERVICE", entry, settlement });
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "เปิดค่ามือไม่สำเร็จ" : "Could not open service pay", message: caught instanceof Error ? caught.message : undefined });
    } finally { setSaving(false); }
  }

  async function submitEditor(values: { amountBaht: number; tipBaht: number; reason: string; effectiveFrom: string; adjustmentKind: "BONUS" | "ADJUSTMENT"; paymentMethod: "CASH" | "TRANSFER" }) {
    if (!editor) return;
    setSaving(true);
    try {
      if (editor.kind === "CREATE_ADJUSTMENT") {
        await adminApi(user, "/therapist-compensation/adjustments", { method: "POST", body: JSON.stringify({ branchId: "branch_001", therapistId: editor.row.therapistId, localDate: dateFrom, amountSatang: values.amountBaht * 100, kind: values.adjustmentKind, reason: values.reason, commandId: crypto.randomUUID() }) });
      } else if (editor.kind === "EDIT_ADJUSTMENT") {
        await adminApi(user, `/therapist-compensation/adjustments/${encodeURIComponent(editor.entry.entryId)}`, { method: "PATCH", body: JSON.stringify({ amountSatang: values.amountBaht * 100, kind: values.adjustmentKind, reason: values.reason, expectedVersion: editor.entry.version ?? 1 }) });
      } else if (editor.kind === "EDIT_PROFILE") {
        await adminApi(user, `/therapists/${encodeURIComponent(editor.row.therapistId)}/compensation-profile`, { method: "PATCH", body: JSON.stringify({ dailyGuaranteeSatang: values.amountBaht * 100, effectiveFrom: values.effectiveFrom, expectedVersion: editor.row.profileVersion, reason: values.reason }) });
      } else if (editor.kind === "PAYOUT") {
        const confirmation = await requestConfirmation({ title: locale === "th" ? "ยืนยันการจ่ายเงินให้หมอ" : "Confirm therapist payout", message: locale === "th" ? `บันทึกจ่าย ${baht(editor.row.outstandingSatang, locale)} ให้ ${editor.row.therapistName} สำหรับ ${dateLabel(dateFrom, locale)} ถึง ${dateLabel(dateTo, locale)}` : `Record ${baht(editor.row.outstandingSatang, locale)} paid to ${editor.row.therapistName} for ${dateLabel(dateFrom, locale)} to ${dateLabel(dateTo, locale)}.`, confirmLabel: locale === "th" ? "ยืนยันว่าจ่ายแล้ว" : "Confirm paid", cancelLabel: locale === "th" ? "กลับไปตรวจ" : "Review again" });
        if (!confirmation.confirmed) { setSaving(false); return; }
        await adminApi(user, "/therapist-compensation/payouts", { method: "POST", body: JSON.stringify({ branchId: "branch_001", therapistId: editor.row.therapistId, dateFrom, dateTo, paymentMethod: values.paymentMethod, note: values.reason, commandId: crypto.randomUUID() }) });
      } else {
        const allocation = editor.settlement.allocations.find((item) => item.bookingLineItemId === editor.entry.bookingLineItemId);
        if (!allocation || !editor.entry.bookingId) throw new Error("Service allocation is unavailable");
        await adminApi(user, `/bookings/${encodeURIComponent(editor.entry.bookingId)}/settlement`, { method: "PUT", body: JSON.stringify({ expectedVersion: editor.settlement.version, correctionReason: values.reason, allocations: editor.settlement.allocations.map((item) => item.bookingLineItemId === allocation.bookingLineItemId ? { ...item, therapistPaySatang: values.amountBaht * 100, tipShareSatang: values.tipBaht * 100 } : item).map(({ bookingLineItemId, participantId, therapistId, therapistPaySatang, tipShareSatang }) => ({ bookingLineItemId, participantId, therapistId, therapistPaySatang, tipShareSatang })) }) });
      }
      notify({ tone: "success", title: locale === "th" ? "บันทึกข้อมูลค่าหมอแล้ว" : "Therapist compensation saved" });
      setEditor(null);
      await load();
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "บันทึกข้อมูลไม่สำเร็จ" : "Save failed", message: caught instanceof Error ? caught.message : undefined });
    } finally { setSaving(false); }
  }

  const toolbar = <div className="compensation-toolbar">
    <div><label><span>{locale === "th" ? (tab === "TODAY" ? "วันที่ทำงาน" : "ตั้งแต่") : (tab === "TODAY" ? "Work date" : "From")}</span><input type="date" value={dateFrom} max={dateTo} onChange={(event) => { setDateFrom(event.target.value); if (tab === "TODAY") setDateTo(event.target.value); }} /></label>{tab !== "TODAY" && <label><span>{locale === "th" ? "ถึง" : "To"}</span><input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} /></label>}</div>
    <button type="button" disabled={loading} onClick={() => { void load(); }}>{locale === "th" ? "รีเฟรชข้อมูล" : "Refresh"}</button>
  </div>;

  if (loading && !payload) return <><div className="module-state" role="status">{locale === "th" ? "กำลังโหลดค่าหมอ…" : "Loading therapist compensation…"}</div></>;
  if (error && !payload) return <><div className="module-state error" role="alert">{error}</div></>;

  if (tab === "LEDGER") return <section className="module-panel compensation-panel" aria-labelledby="compensation-ledger-title">
    <div className="panel-title"><div><h2 id="compensation-ledger-title">{locale === "th" ? "รายการค่ามือและเงินจากร้าน" : "Compensation ledger"}</h2><small>{locale === "th" ? "ค่าจากบริการเชื่อมกับ Settlement; รายการจากร้านมีประวัติแก้ไข" : "Service pay remains linked to settlement; shop entries keep revision history."}</small></div></div>
    {toolbar}
    <div className="compensation-ledger-filters"><label><span>{locale === "th" ? "แหล่งเงิน" : "Source"}</span><select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as typeof sourceFilter)}><option value="ALL">{locale === "th" ? "ทั้งหมด" : "All"}</option><option value="SERVICE">{locale === "th" ? "จากการให้บริการ" : "From service"}</option><option value="SHOP">{locale === "th" ? "จากร้านนวด" : "From shop"}</option></select></label><label><span>{locale === "th" ? "หมอนวด" : "Therapist"}</span><select value={therapistFilter} onChange={(event) => setTherapistFilter(event.target.value)}><option value="ALL">{locale === "th" ? "ทุกคน" : "All therapists"}</option>{payload?.summary.map((row) => <option value={row.therapistId} key={row.therapistId}>{row.therapistName}</option>)}</select></label></div>
    <div className="table-scroll"><table className="compensation-ledger-table"><thead><tr><th>{locale === "th" ? "วันที่" : "Date"}</th><th>{locale === "th" ? "หมอนวด / รายการ" : "Therapist / item"}</th><th>{locale === "th" ? "แหล่งเงิน" : "Source"}</th><th>{locale === "th" ? "ค่ามือ" : "Pay"}</th><th>{locale === "th" ? "ทิป" : "Tip"}</th><th>{locale === "th" ? "สถานะ" : "Status"}</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{filteredEntries.map((entry) => <tr key={entry.entryId}><td>{dateLabel(entry.localDate, locale)}</td><td><strong>{entry.therapistName}</strong><small>{entryKindLabel(entry, locale)}{entry.bookingId ? ` • ${entry.bookingId}` : ""}{entry.reason ? ` • ${entry.reason}` : ""}</small></td><td><span className={`compensation-source ${entry.source.toLowerCase()}`}>{entry.source === "SERVICE" ? (locale === "th" ? "จากการให้บริการ" : "Service") : (locale === "th" ? "จากร้านนวด" : "Shop")}</span></td><td className={entry.amountSatang < 0 ? "negative-amount" : ""}>{baht(entry.amountSatang, locale)}</td><td>{baht(entry.tipSatang, locale)}</td><td><span className={`state-chip ${entry.lockedReason === "PAID" ? "success" : "warning"}`}>{entry.lockedReason === "PAID" ? (locale === "th" ? "จ่ายแล้ว" : "Paid") : (locale === "th" ? "ยังแก้ไขได้" : "Editable")}</span></td><td>{entry.editable ? <button type="button" className="table-action" disabled={saving} onClick={() => { if (entry.source === "SERVICE") void openServiceEditor(entry); else if (entry.kind !== "GUARANTEE_TOP_UP") setEditor({ kind: "EDIT_ADJUSTMENT", entry }); }}>{locale === "th" ? "แก้ไข" : "Edit"}</button> : <span className="not-applicable">—</span>}</td></tr>)}</tbody></table></div>
    {!filteredEntries.length && <div className="module-state">{locale === "th" ? "ไม่มีรายการตามตัวกรอง" : "No ledger entries match the filters."}</div>}
    {!!payload?.payouts.length && <div className="compensation-payout-history"><h3>{locale === "th" ? "ประวัติการจ่าย" : "Payout history"}</h3>{payload.payouts.map((item) => <div key={item.payoutId}><span><strong>{item.therapistName}</strong><small>{dateLabel(item.dateFrom, locale)} – {dateLabel(item.dateTo, locale)} • {item.paymentMethod === "TRANSFER" ? (locale === "th" ? "โอนเงิน" : "Transfer") : (locale === "th" ? "เงินสด" : "Cash")}</small></span><strong>{baht(item.amountSatang, locale)}</strong></div>)}</div>}
    {editor && <CompensationEditor editor={editor} locale={locale} saving={saving} onClose={closeEditor} onSubmit={submitEditor} />}
  </section>;

  if (tab === "PROFILES") return <section className="module-panel compensation-panel" aria-labelledby="compensation-profile-title">
    <div className="panel-title"><div><h2 id="compensation-profile-title">{locale === "th" ? "เงื่อนไขค่าประกันมือ" : "Hand-guarantee profiles"}</h2><small>{locale === "th" ? "เรตมีวันที่เริ่มใช้และไม่แก้ย้อนหลังข้ามช่วงที่จ่ายแล้ว" : "Rates are effective-dated and cannot rewrite a paid period."}</small></div></div>
    <div className="table-scroll"><table className="compensation-profile-table"><thead><tr><th>{locale === "th" ? "หมอนวด" : "Therapist"}</th><th>{locale === "th" ? "สถานะ" : "Status"}</th><th>{locale === "th" ? "ค่าประกันมือต่อวัน" : "Daily guarantee"}</th><th>{locale === "th" ? "เริ่มใช้" : "Effective from"}</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{payload?.summary.map((row) => <tr key={row.therapistId}><td><strong>{row.therapistName}</strong></td><td><span className={`state-chip ${row.active ? "success" : ""}`}>{row.active ? (locale === "th" ? "เปิดใช้งาน" : "Active") : (locale === "th" ? "ปิดใช้งาน" : "Inactive")}</span></td><td><strong>{baht(row.dailyGuaranteeSatang, locale)}</strong></td><td>{row.guaranteeEffectiveFrom ? dateLabel(row.guaranteeEffectiveFrom, locale) : (locale === "th" ? "ค่าเริ่มต้นระบบ" : "System default")}</td><td><button type="button" className="table-action" onClick={() => setEditor({ kind: "EDIT_PROFILE", row })}>{locale === "th" ? "แก้เงื่อนไข" : "Edit terms"}</button></td></tr>)}</tbody></table></div>
    {editor && <CompensationEditor editor={editor} locale={locale} saving={saving} onClose={closeEditor} onSubmit={submitEditor} />}
  </section>;

  return <section className="module-panel compensation-panel" aria-labelledby="compensation-summary-title">
    <div className="panel-title"><div><h2 id="compensation-summary-title">{locale === "th" ? "ภาพรวมค่าหมอ" : "Therapist compensation overview"}</h2><small>{locale === "th" ? "ต้องระบุมาทำงานก่อน ระบบจึงคำนวณส่วนเติมค่าประกันมือ" : "Attendance is required before a guarantee top-up is calculated."}</small></div></div>
    {toolbar}
    {payload && <dl className="compensation-summary-strip"><div><dt>{locale === "th" ? "จากบริการ" : "Service"}</dt><dd>{baht(payload.totals.servicePaySatang, locale)}</dd></div><div><dt>{locale === "th" ? "จากร้าน" : "Shop"}</dt><dd>{baht(payload.totals.shopSourceSatang, locale)}</dd></div><div><dt>{locale === "th" ? "ทิปหมอ" : "Tips"}</dt><dd>{baht(payload.totals.tipSatang, locale)}</dd></div><div><dt>{locale === "th" ? "จ่ายแล้ว" : "Paid"}</dt><dd>{baht(payload.totals.paidSatang, locale)}</dd></div><div className="outstanding"><dt>{locale === "th" ? "ค้างจ่าย" : "Outstanding"}</dt><dd>{baht(payload.totals.outstandingSatang, locale)}</dd></div></dl>}
    <div className="table-scroll"><table className="compensation-summary-table"><thead><tr><th>{locale === "th" ? "หมอนวด" : "Therapist"}</th><th>{locale === "th" ? "มาทำงาน" : "Attendance"}</th><th>{locale === "th" ? "งาน / นาที" : "Jobs / min"}</th><th>{locale === "th" ? "จากบริการ" : "Service"}</th><th>{locale === "th" ? "จากร้าน" : "Shop"}</th><th>{locale === "th" ? "ทิป" : "Tip"}</th><th>{locale === "th" ? "รวมต้องจ่าย" : "Total due"}</th><th>{locale === "th" ? "จ่ายแล้ว / ค้าง" : "Paid / due"}</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{payload?.summary.map((row) => { const day = row.days.find((item) => item.localDate === dateFrom); return <tr key={row.therapistId}><td><strong>{row.therapistName}</strong><small>{locale === "th" ? `ประกัน ${baht(row.dailyGuaranteeSatang, locale)}/วัน` : `Guarantee ${baht(row.dailyGuaranteeSatang, locale)}/day`}</small></td><td><button type="button" role="switch" aria-checked={Boolean(day?.present)} className={`attendance-switch ${day?.present ? "active" : ""}`} disabled={saving} onClick={() => { void markAttendance(row, !day?.present); }}>{day?.present ? (locale === "th" ? "มาทำงาน" : "Present") : (locale === "th" ? "ยังไม่ระบุ" : "Not marked")}</button></td><td><strong>{row.serviceCount}</strong><small>{row.durationMinutes} {locale === "th" ? "นาที" : "min"}</small></td><td>{baht(row.servicePaySatang, locale)}</td><td><strong>{baht(row.shopSourceSatang, locale)}</strong><small>{locale === "th" ? `ประกัน ${baht(row.guaranteeTopUpSatang, locale)}` : `Guarantee ${baht(row.guaranteeTopUpSatang, locale)}`}</small></td><td>{baht(row.tipSatang, locale)}</td><td><strong>{baht(row.totalEarnedSatang, locale)}</strong></td><td><span className={`state-chip ${row.payoutState === "PAID" ? "success" : row.payoutState === "PARTIAL" ? "warning" : ""}`}>{payoutLabel(row.payoutState, locale)}</span><small>{baht(row.paidSatang, locale)} / {baht(row.outstandingSatang, locale)}</small></td><td><div className="compensation-row-actions"><button type="button" onClick={() => setEditor({ kind: "CREATE_ADJUSTMENT", row })}>{locale === "th" ? "+ จากร้าน" : "+ Shop entry"}</button><button type="button" className="primary" disabled={row.outstandingSatang <= 0} onClick={() => setEditor({ kind: "PAYOUT", row })}>{locale === "th" ? "บันทึกจ่าย" : "Record payout"}</button></div></td></tr>; })}</tbody></table></div>
    {!payload?.summary.length && <div className="module-state">{locale === "th" ? "ยังไม่มีข้อมูลหมอนวด" : "No therapists found."}</div>}
    {editor && <CompensationEditor editor={editor} locale={locale} saving={saving} onClose={closeEditor} onSubmit={submitEditor} />}
  </section>;
}
