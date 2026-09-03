"use client";

import type { Locale } from "@spa/shared-types";
import type { User } from "firebase/auth";
import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { adminApi } from "@/lib/admin-api";

type Candidate = {
  paymentId: string;
  bookingId: string;
  customerName: string;
  paidAt: string;
  grossAmountSatang: number;
  version: number;
};

type Deposit = {
  depositId: string;
  status: string;
  version: number;
  totalAmountSatang: number;
  allocationCount: number;
  allocations: Array<{ paymentId: string; bookingId: string; amountSatang: number }>;
  evidence?: { status: string; contentType: string; sizeBytes: number };
  reviewReason?: string | null;
  attempt?: {
    attemptId: string;
    status: string;
    imageBase64?: string | null;
    expiresAt?: string | null;
    providerChargeId?: string | null;
  };
};

type Props = {
  locale: Locale;
  user: User;
  initialDepositId?: string | null;
  initialPaymentId?: string | null;
  onClose: () => void;
  onChanged: () => Promise<void>;
};

const terminal = new Set(["COMPLETED", "FAILED", "EXPIRED", "REVIEW", "CANCELLED"]);

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", {
    style: "currency",
    currency: "THB",
    minimumFractionDigits: 2,
  }).format(value / 100);
}

function dateTime(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Bangkok",
  }).format(new Date(value));
}

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export function CashDepositWorkflow({ locale, user, initialDepositId, initialPaymentId, onClose, onChanged }: Props) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set(initialPaymentId ? [initialPaymentId] : []));
  const [confirmedBaht, setConfirmedBaht] = useState("");
  const [deposit, setDeposit] = useState<Deposit | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const loadDeposit = useCallback(async (depositId: string) => {
    const result = await adminApi<Deposit>(user, `/cash-deposits/${depositId}`);
    setDeposit(result);
    return result;
  }, [user]);

  useEffect(() => {
    let active = true;
    queueMicrotask(async () => {
      try {
        if (initialDepositId) {
          await loadDeposit(initialDepositId);
        } else {
          const result = await adminApi<{ items: Candidate[] }>(user, "/cash-payments/unsettled?branchId=branch_001");
          if (active) {
            setCandidates(result.items);
            if (initialPaymentId && !result.items.some((item) => item.paymentId === initialPaymentId)) {
              setError(locale === "th" ? "รายการเงินสดนี้ถูกจัดสรรแล้ว กรุณาโหลดหน้ารายการใหม่" : "This cash payment is already allocated. Reload the list.");
            }
          }
        }
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Cash deposit unavailable");
      } finally {
        if (active) setLoading(false);
      }
    });
    return () => { active = false; };
  }, [initialDepositId, initialPaymentId, loadDeposit, locale, user]);

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = Array.from(drawerRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), a[href]'
      ));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [onClose]);

  useEffect(() => {
    if (!deposit || deposit.status !== "QR_ACTIVE") return;
    const timer = window.setInterval(async () => {
      try {
        const current = await loadDeposit(deposit.depositId);
        if (terminal.has(current.status)) {
          window.clearInterval(timer);
          await onChanged();
        }
      } catch { /* Keep the durable QR visible; Admin can reconcile manually. */ }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [deposit, loadDeposit, onChanged]);

  const selectedRows = useMemo(() => candidates.filter((item) => selected.has(item.paymentId)), [candidates, selected]);
  const totalSatang = useMemo(() => selectedRows.reduce((sum, item) => sum + item.grossAmountSatang, 0), [selectedRows]);
  const confirmedSatang = Math.round(Number(confirmedBaht) * 100);
  const totalMatches = totalSatang > 0 && Number.isFinite(confirmedSatang) && totalSatang === confirmedSatang;

  const createDraft = async () => {
    if (!totalMatches) return;
    setBusy(true); setError("");
    try {
      const result = await adminApi<Deposit>(user, "/cash-deposits", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          branchId: "branch_001",
          allocations: selectedRows.slice(0, 100).map((item) => ({ paymentId: item.paymentId, expectedVersion: item.version })),
          expectedTotalSatang: totalSatang,
        }),
      });
      setDeposit(result);
      await onChanged();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not create cash deposit"); }
    finally { setBusy(false); }
  };

  const uploadEvidence = async () => {
    if (!deposit || !file) return;
    setBusy(true); setError("");
    try {
      const checksum = await sha256(file);
      const authorization = await adminApi<{ uploadUrl: string }>(user, `/cash-deposits/${deposit.depositId}/evidence-upload:authorize`, {
        method: "POST",
        body: JSON.stringify({ contentType: file.type, sizeBytes: file.size, sha256: checksum }),
      });
      const upload = await fetch(authorization.uploadUrl, { method: "PUT", headers: { "Content-Type": file.type }, body: file });
      if (!upload.ok) throw new Error(`Evidence upload failed (${upload.status})`);
      const generation = Number(upload.headers.get("x-goog-generation"));
      if (!Number.isSafeInteger(generation) || generation <= 0) throw new Error("GCS generation header is unavailable; verify bucket CORS exposeHeaders");
      setDeposit(await adminApi<Deposit>(user, `/cash-deposits/${deposit.depositId}/evidence:confirm`, {
        method: "POST",
        body: JSON.stringify({ generation }),
      }));
      notify({ tone: "success", title: locale === "th" ? "ตรวจสอบหลักฐานแล้ว" : "Evidence verified" });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Evidence upload failed"); }
    finally { setBusy(false); }
  };

  const createQr = async () => {
    if (!deposit) return;
    const confirmation = await requestConfirmation({
      title: locale === "th" ? "ยืนยันสร้าง Beam QR?" : "Create Beam QR?",
      message: locale === "th" ? `${deposit.allocationCount} รายการ รวม ${baht(deposit.totalAmountSatang, locale)} • การชำระสำเร็จจะเปลี่ยนทุกรายการเป็น SETTLED และไม่สร้างยอดขายบัญชีซ้ำ` : `${deposit.allocationCount} payments totaling ${baht(deposit.totalAmountSatang, locale)}. Success settles all allocations without creating another sale export.`,
      confirmLabel: locale === "th" ? "ยืนยันสร้าง QR" : "Create QR",
      cancelLabel: locale === "th" ? "กลับไปตรวจ" : "Review",
    });
    if (!confirmation.confirmed) return;
    setBusy(true); setError("");
    try {
      setDeposit(await adminApi<Deposit>(user, `/cash-deposits/${deposit.depositId}/attempts`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ expectedVersion: deposit.version }),
      }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not create Beam QR"); }
    finally { setBusy(false); }
  };

  const reconcile = async () => {
    if (!deposit?.attempt) return;
    setBusy(true); setError("");
    try {
      setDeposit(await adminApi<Deposit>(user, `/cash-deposit-attempts/${deposit.attempt.attemptId}:reconcile`, { method: "POST" }));
      await onChanged();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Reconciliation failed"); }
    finally { setBusy(false); }
  };

  const saveQr = () => {
    if (!deposit?.attempt?.imageBase64) return;
    const anchor = document.createElement("a");
    anchor.href = `data:image/png;base64,${deposit.attempt.imageBase64.replace(/^data:image\/png;base64,/, "")}`;
    anchor.download = `${deposit.depositId}-beam-qr.png`;
    anchor.click();
  };

  return <>
    <div className="accounting-scrim" aria-hidden="true" onClick={onClose} />
    <aside ref={drawerRef} className="detail-drawer cash-deposit-drawer" role="dialog" aria-modal="true" aria-labelledby="cash-deposit-title">
      <div className="drawer-header cash-deposit-header"><div><p className="eyebrow">TREASURY • BEAM</p><h2 id="cash-deposit-title">{locale === "th" ? "นำเงินสดเข้าบัญชี" : "Deposit cash"}</h2><p>{deposit ? (locale === "th" ? "ตรวจสอบยอดและสถานะการนำเงินเข้าบัญชี" : "Review the total and deposit status") : (locale === "th" ? "เลือกเฉพาะรายการ UNSETTLED" : "Select UNSETTLED cash payments")}</p></div><button ref={closeRef} type="button" aria-label={locale === "th" ? "ปิด" : "Close"} onClick={onClose}>×</button></div>
      {error && <div className="cash-deposit-alert" role="alert">{error}</div>}
      {loading && <div className="cash-deposit-loading" role="status">{locale === "th" ? "กำลังโหลด…" : "Loading…"}</div>}

      {!loading && !deposit && <div className="cash-deposit-body">
        <section><div className="cash-step-heading"><span>1</span><div><strong>{locale === "th" ? "เลือกรายการเงินสด" : "Select cash payments"}</strong><small>{candidates.length} UNSETTLED</small></div></div>
          <div className="cash-candidate-list">{candidates.map((item) => <label key={item.paymentId}><input type="checkbox" checked={selected.has(item.paymentId)} disabled={!selected.has(item.paymentId) && selected.size >= 100} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(item.paymentId)) next.delete(item.paymentId); else if (next.size < 100) next.add(item.paymentId); return next; })} /><span><strong>{item.bookingId} · {item.customerName}</strong><small>{dateTime(item.paidAt, locale)}</small></span><b>{baht(item.grossAmountSatang, locale)}</b></label>)}{!candidates.length && <p className="cash-empty">{locale === "th" ? "ไม่มีเงินสดที่รอนำเข้าบัญชี" : "No unsettled cash payments"}</p>}</div>
        </section>
        <section className="cash-confirm-total"><div><span>{locale === "th" ? "ยอดรวมที่เลือก" : "Selected total"}</span><strong>{baht(totalSatang, locale)}</strong></div><label>{locale === "th" ? "นับเงินจริงได้ (บาท)" : "Counted cash (THB)"}<input inputMode="decimal" value={confirmedBaht} onChange={(event) => setConfirmedBaht(event.target.value)} placeholder="0.00" /></label>{confirmedBaht && !totalMatches && <small role="alert">{locale === "th" ? "ยอดนับจริงต้องเท่ากับยอดที่เลือกทุกสตางค์" : "Counted cash must exactly match selected allocations."}</small>}</section>
        <div className="cash-deposit-actions"><button type="button" onClick={onClose}>{locale === "th" ? "ยกเลิก" : "Cancel"}</button><button className="primary" type="button" disabled={!totalMatches || busy} onClick={() => { void createDraft(); }}>{locale === "th" ? "ล็อกรายการและไปต่อ" : "Lock allocations"}</button></div>
      </div>}

      {!loading && deposit && <div className="cash-deposit-body">
        <div className={`cash-deposit-state state-${deposit.status.toLowerCase()}`}><span>{deposit.status}</span><strong>{baht(deposit.totalAmountSatang, locale)}</strong><small>{deposit.allocationCount} {locale === "th" ? "รายการ" : "payments"}</small></div>
        <section><div className="cash-step-heading"><span>2</span><div><strong>{locale === "th" ? "หลักฐานการนับเงิน" : "Cash-count evidence"}</strong><small>{deposit.evidence?.status || (locale === "th" ? "ยังไม่ได้แนบ" : "Not attached")}</small></div></div>
          {!deposit.evidence || deposit.evidence.status !== "READY" ? <div className="cash-evidence-upload"><label>{locale === "th" ? "รูปเงินสด (JPEG, PNG, HEIC ไม่เกิน 10 MB)" : "Cash photo (JPEG, PNG, HEIC; max 10 MB)"}<input type="file" accept="image/jpeg,image/png,image/heic,image/heif" onChange={(event) => setFile(event.target.files?.[0] || null)} /></label><button type="button" disabled={!file || busy} onClick={() => { void uploadEvidence(); }}>{busy ? (locale === "th" ? "กำลังตรวจ…" : "Verifying…") : (locale === "th" ? "อัปโหลดและตรวจหลักฐาน" : "Upload and verify")}</button></div> : <p className="cash-evidence-ready">✓ {locale === "th" ? "ไฟล์ผ่านการตรวจสอบ checksum และชนิดไฟล์แล้ว" : "File type and checksum verified"}</p>}
        </section>
        <section><div className="cash-step-heading"><span>3</span><div><strong>{locale === "th" ? "ชำระยอดเข้าบัญชี" : "Fund merchant account"}</strong><small>{locale === "th" ? "Beam PromptPay QR อายุ 30 นาที" : "30-minute Beam PromptPay QR"}</small></div></div>
          {deposit.status === "READY_FOR_QR" && <button className="cash-create-qr" type="button" disabled={busy} onClick={() => { void createQr(); }}>{locale === "th" ? "ตรวจยอดและสร้าง Beam QR" : "Review and create Beam QR"}</button>}
          {deposit.attempt?.imageBase64 && deposit.status === "QR_ACTIVE" && <div className="cash-qr"><Image unoptimized width={170} height={170} alt={locale === "th" ? "Beam PromptPay QR สำหรับนำเงินสดเข้าบัญชี" : "Beam PromptPay QR for cash deposit"} src={`data:image/png;base64,${deposit.attempt.imageBase64.replace(/^data:image\/png;base64,/, "")}`} /><div><strong>{locale === "th" ? "สแกนเพื่อชำระยอดรวม" : "Scan the exact total"}</strong><span>{baht(deposit.totalAmountSatang, locale)}</span><small>{locale === "th" ? "ห้ามแก้ยอดในแอปธนาคาร" : "Do not edit the amount in the bank app"}</small></div><button type="button" onClick={saveQr}>{locale === "th" ? "บันทึก QR" : "Save QR"}</button></div>}
          {deposit.status === "QR_ACTIVE" && !deposit.attempt?.imageBase64 && <div className="cash-review"><strong>{locale === "th" ? "QR ถูกสร้างแล้ว" : "QR is already active"}</strong><span>{locale === "th" ? "เพื่อความปลอดภัยระบบไม่เก็บรูป QR กรุณาตรวจผลกับ Beam ห้ามสร้างชุดใหม่ซ้ำ" : "For security, the QR image is not stored. Reconcile with Beam; do not create another batch."}</span></div>}
          {deposit.attempt && ["QR_CREATING", "QR_ACTIVE", "REVIEW", "FAILED", "EXPIRED"].includes(deposit.status) && <button className="cash-reconcile" type="button" disabled={busy} onClick={() => { void reconcile(); }}>{locale === "th" ? "ตรวจสอบสถานะกับ Beam" : "Reconcile with Beam"}</button>}
          {deposit.status === "COMPLETED" && <div className="cash-success" role="status"><strong>✓ {locale === "th" ? "เงินสดเข้าบัญชีแล้ว" : "Cash settled"}</strong><span>{locale === "th" ? "ทุกรายการเปลี่ยนเป็น SETTLED โดยไม่สร้าง FlowAccount ซ้ำ" : "All allocations are SETTLED; no duplicate FlowAccount sale was created."}</span></div>}
          {deposit.status === "REVIEW" && <div className="cash-review" role="alert"><strong>{locale === "th" ? "ต้องตรวจสอบก่อนดำเนินการต่อ" : "Manual review required"}</strong><span>{deposit.reviewReason || "CASH_DEPOSIT_REVIEW"}</span></div>}
          {["FAILED", "EXPIRED"].includes(deposit.status) && <button className="cash-create-qr" type="button" disabled={busy} onClick={() => { void createQr(); }}>{locale === "th" ? "สร้าง QR ใหม่หลังตรวจสอบแล้ว" : "Create a new QR after reconciliation"}</button>}
        </section>
        <details className="cash-allocation-summary"><summary>{locale === "th" ? "ดูรายการที่รวมยอด" : "View allocations"}</summary>{deposit.allocations.map((item) => <div key={item.paymentId}><span>{item.bookingId}</span><strong>{baht(item.amountSatang, locale)}</strong></div>)}</details>
      </div>}
    </aside>
  </>;
}
