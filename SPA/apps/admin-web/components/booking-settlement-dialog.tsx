"use client";

import type { User } from "firebase/auth";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { adminApi } from "@/lib/admin-api";
import { parseSettlementAmountDraft, settlementAmountDraft } from "@/lib/settlement-amount";
import type { Locale } from "@spa/shared-types";

type Therapist = { therapistId: string; displayName: string; active: boolean };
type Allocation = {
  participantId: string;
  bookingLineItemId: string;
  participantSequence: number;
  participantName: string;
  serviceNameTh: string;
  serviceNameEn: string;
  durationMinutes: number;
  therapistId: string | null;
  therapistName: string | null;
  therapistPaySatang: number;
  tipShareSatang: number;
};
type Settlement = {
  bookingId: string;
  bookingStatus: string;
  eligible: boolean;
  settled: boolean;
  requiresTipReallocation: boolean;
  requiresFinancialReallocation: boolean;
  version: number;
  subtotalAmountSatang: number;
  discountAmountSatang: number;
  netServiceAmountSatang: number;
  tipAmountSatang: number;
  grossAmountSatang: number;
  therapistPaySatang: number;
  therapistTipSatang: number;
  shopServiceAmountSatang: number;
  shopTipSatang: number;
  shopTotalSatang: number;
  negativeShopServiceAmount: boolean;
  allocations: Allocation[];
};
type AllocationDraft = Omit<Allocation, "therapistPaySatang" | "tipShareSatang"> & {
  therapistPayBaht: string;
  tipShareBaht: string;
};

function allocationDraft(allocation: Allocation): AllocationDraft {
  const { therapistPaySatang, tipShareSatang, ...details } = allocation;
  return {
    ...details,
    therapistPayBaht: settlementAmountDraft(therapistPaySatang),
    tipShareBaht: settlementAmountDraft(tipShareSatang),
  };
}

function baht(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-GB", { style: "currency", currency: "THB", maximumFractionDigits: 0 }).format(value / 100);
}

export function BookingSettlementDialog({ bookingId, locale, user, onClose, onSaved }: { bookingId: string; locale: Locale; user: User; onClose: () => void; onSaved: () => void }) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const [settlement, setSettlement] = useState<Settlement | null>(null);
  const [therapists, setTherapists] = useState<Therapist[]>([]);
  const [allocations, setAllocations] = useState<AllocationDraft[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "saving" | "error">("loading");
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      adminApi<Settlement>(user, `/bookings/${encodeURIComponent(bookingId)}/settlement`),
      adminApi<{ items: Therapist[] }>(user, "/therapists"),
    ]).then(([payload, roster]) => {
      if (!active) return;
      setSettlement(payload);
      setAllocations(payload.allocations.map(allocationDraft));
      setTherapists(roster.items);
      setState("ready");
    }).catch((caught) => {
      if (!active) return;
      setError(caught instanceof Error ? caught.message : "Settlement unavailable");
      setState("error");
    });
    return () => { active = false; };
  }, [bookingId, user]);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && state !== "saving") onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled])'));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, [onClose, state]);

  const parsedAllocations = useMemo(() => allocations.map((item) => ({
    ...item,
    therapistPaySatang: parseSettlementAmountDraft(item.therapistPayBaht),
    tipShareSatang: parseSettlementAmountDraft(item.tipShareBaht),
  })), [allocations]);

  const invalidAmount = parsedAllocations.some((item) => item.therapistPaySatang === null || item.tipShareSatang === null);

  const totals = useMemo(() => {
    const therapistPay = parsedAllocations.reduce((sum, item) => sum + (item.therapistPaySatang ?? 0), 0);
    const therapistTip = parsedAllocations.reduce((sum, item) => sum + (item.tipShareSatang ?? 0), 0);
    const net = settlement?.netServiceAmountSatang ?? 0;
    const tip = settlement?.tipAmountSatang ?? 0;
    const shopService = net - therapistPay;
    const shopTip = tip - therapistTip;
    return { therapistPay, therapistTip, shopService, shopTip, shopTotal: shopService + shopTip };
  }, [parsedAllocations, settlement]);

  const invalidTip = totals.shopTip < 0;
  const missingTherapist = parsedAllocations.some((item) => ((item.therapistPaySatang ?? 0) > 0 || (item.tipShareSatang ?? 0) > 0) && !item.therapistId);

  const update = (bookingLineItemId: string, change: Partial<AllocationDraft>) => setAllocations((current) => current.map((item) => item.bookingLineItemId === bookingLineItemId ? { ...item, ...change } : item));

  async function save() {
    if (!settlement || state === "saving" || invalidAmount || invalidTip || missingTherapist) return;
    const confirmation = await requestConfirmation({
      title: locale === "th" ? "ยืนยันสรุปรายได้รายการนี้?" : "Confirm this service settlement?",
      message: locale === "th"
        ? `ค่าหมอ ${baht(totals.therapistPay, locale)} • ทิปหมอ ${baht(totals.therapistTip, locale)} • ส่วนร้าน ${baht(totals.shopTotal, locale)} การแก้ไขภายหลังจะถูกบันทึกใน Audit Log`
        : `Therapist pay ${baht(totals.therapistPay, locale)} • therapist tips ${baht(totals.therapistTip, locale)} • shop share ${baht(totals.shopTotal, locale)}. Later edits remain audited.`,
      confirmLabel: locale === "th" ? "ยืนยันบันทึก" : "Save settlement",
      cancelLabel: locale === "th" ? "กลับไปตรวจ" : "Review again",
    });
    if (!confirmation.confirmed) return;
    setState("saving");
    try {
      const saved = await adminApi<Settlement>(user, `/bookings/${encodeURIComponent(bookingId)}/settlement`, {
        method: "PUT",
        body: JSON.stringify({
          expectedVersion: settlement.version,
          allocations: parsedAllocations.map((item) => ({ bookingLineItemId: item.bookingLineItemId, participantId: item.participantId, therapistId: item.therapistId || null, therapistPaySatang: item.therapistPaySatang ?? 0, tipShareSatang: item.tipShareSatang ?? 0 })),
        }),
      });
      setSettlement(saved);
      setAllocations(saved.allocations.map(allocationDraft));
      setState("ready");
      notify({ tone: "success", title: locale === "th" ? "บันทึกค่าหมอและส่วนร้านแล้ว" : "Service settlement saved", message: bookingId });
      onSaved();
      onClose();
    } catch (caught) {
      setState("error");
      setError(caught instanceof Error ? caught.message : "Settlement save failed");
    }
  }

  return <div className="modal-backdrop settlement-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && state !== "saving") onClose(); }}>
    <div ref={dialogRef} className="settlement-dialog" role="dialog" aria-modal="true" aria-labelledby="settlement-title" aria-describedby="settlement-description">
      <div className="drawer-header"><div><p className="eyebrow">SERVICE SETTLEMENT • {bookingId}</p><h2 id="settlement-title">{locale === "th" ? "สรุปรายได้และค่าหมอ" : "Service revenue settlement"}</h2></div><button ref={closeRef} type="button" disabled={state === "saving"} aria-label={locale === "th" ? "ปิดหน้าต่าง" : "Close dialog"} onClick={onClose}>×</button></div>
      <p id="settlement-description" className="settlement-description">{locale === "th" ? "ส่วนลดเป็น Promotion ของร้านและไม่ลดค่าหมอ ทิปที่ไม่ได้แบ่งให้หมอจะเป็นส่วนของร้านอัตโนมัติ" : "Shop promotions do not reduce therapist pay. Unallocated tips remain with the shop."}</p>
      {state === "loading" && <div className="module-state" role="status">{locale === "th" ? "กำลังโหลดข้อมูลบริการ…" : "Loading service details…"}</div>}
      {error && <div className="drawer-feedback error" role="alert">{error}</div>}
      {settlement && <>
        {settlement.requiresFinancialReallocation && <div className="settlement-warning" role="alert">{settlement.requiresTipReallocation ? (locale === "th" ? "ยอดทิปเปลี่ยนหลังการสรุปครั้งก่อน กรุณาตรวจและแบ่งทิปใหม่" : "The received tip changed after the last settlement. Review and reallocate the tip.") : (locale === "th" ? "ส่วนลดหรือยอดค่าบริการเปลี่ยนหลังการสรุปครั้งก่อน กรุณาตรวจส่วนร้านและบันทึกใหม่" : "The discount or net service amount changed after the last settlement. Review the shop share and save again.")}</div>}
        <dl className="settlement-financial-strip"><div><dt>{locale === "th" ? "ราคาปกติ" : "Regular price"}</dt><dd>{baht(settlement.subtotalAmountSatang, locale)}</dd></div><div><dt>{locale === "th" ? "ส่วนลดร้าน" : "Shop promotion"}</dt><dd>−{baht(settlement.discountAmountSatang, locale)}</dd></div><div><dt>{locale === "th" ? "ค่าบริการสุทธิ" : "Net service"}</dt><dd>{baht(settlement.netServiceAmountSatang, locale)}</dd></div><div><dt>{locale === "th" ? "ทิปทั้งหมด" : "Total tip"}</dt><dd>{baht(settlement.tipAmountSatang, locale)}</dd></div></dl>
        <div className="settlement-allocation-list">{allocations.map((item) => <section key={item.bookingLineItemId} className="settlement-allocation-row" aria-labelledby={`allocation-${item.bookingLineItemId}`}>
          <div className="settlement-service"><strong id={`allocation-${item.bookingLineItemId}`}>{item.participantName}</strong><span>{locale === "th" ? item.serviceNameTh : item.serviceNameEn} • {item.durationMinutes} {locale === "th" ? "นาที" : "min"}</span></div>
          <label><span>{locale === "th" ? "หมอนวด" : "Therapist"}</span><select value={item.therapistId ?? ""} onChange={(event) => update(item.bookingLineItemId, { therapistId: event.target.value || null })}><option value="">— {locale === "th" ? "ไม่ระบุ" : "Not assigned"} —</option>{therapists.map((therapist) => <option value={therapist.therapistId} key={therapist.therapistId}>{therapist.displayName}{therapist.active ? "" : locale === "th" ? " (ปิดใช้งาน)" : " (inactive)"}</option>)}</select></label>
          <label><span>{locale === "th" ? "ค่าหมอ (บาท)" : "Therapist pay (THB)"}</span><input type="number" min="0" step="1" inputMode="numeric" placeholder="0" value={item.therapistPayBaht} aria-invalid={parseSettlementAmountDraft(item.therapistPayBaht) === null} aria-describedby={invalidAmount ? "settlement-amount-warning" : undefined} onChange={(event) => update(item.bookingLineItemId, { therapistPayBaht: event.target.value })} /></label>
          <label><span>{locale === "th" ? "แบ่งทิปให้หมอ (บาท)" : "Therapist tip (THB)"}</span><input type="number" min="0" step="1" inputMode="numeric" placeholder="0" value={item.tipShareBaht} aria-invalid={parseSettlementAmountDraft(item.tipShareBaht) === null} aria-describedby={invalidAmount ? "settlement-amount-warning" : undefined} onChange={(event) => update(item.bookingLineItemId, { tipShareBaht: event.target.value })} /></label>
        </section>)}</div>
        {invalidAmount && <p id="settlement-amount-warning" className="settlement-warning" role="alert">{locale === "th" ? "ค่าหมอและทิปต้องเป็นจำนวนเต็มตั้งแต่ 0 บาทขึ้นไป" : "Therapist pay and tips must be non-negative whole baht."}</p>}
        {missingTherapist && <p className="settlement-warning" role="alert">{locale === "th" ? "ต้องเลือกหมอนวดสำหรับแถวที่มีค่าหมอหรือทิป" : "Select a therapist for every row with pay or tip."}</p>}
        {invalidTip && <p className="settlement-warning" role="alert">{locale === "th" ? "ยอดแบ่งทิปให้หมอมากกว่าทิปที่ได้รับ" : "Therapist tip shares exceed the received tip."}</p>}
        <dl className="settlement-result"><div><dt>{locale === "th" ? "ค่าหมอรวม" : "Therapist pay"}</dt><dd>{baht(totals.therapistPay, locale)}</dd></div><div><dt>{locale === "th" ? "ทิปหมอรวม" : "Therapist tips"}</dt><dd>{baht(totals.therapistTip, locale)}</dd></div><div><dt>{locale === "th" ? "ทิปส่วนร้าน" : "Shop tip"}</dt><dd>{baht(totals.shopTip, locale)}</dd></div><div className={totals.shopService < 0 ? "negative" : ""}><dt>{locale === "th" ? "ส่วนร้านจากค่าบริการ" : "Shop service share"}</dt><dd>{baht(totals.shopService, locale)}</dd></div><div className="settlement-shop-total"><dt>{locale === "th" ? "ส่วนร้านรวม" : "Total shop share"}</dt><dd>{baht(totals.shopTotal, locale)}</dd></div></dl>
        {totals.shopService < 0 && <p className="settlement-loss-warning" role="alert">{locale === "th" ? "ส่วนร้านจากค่าบริการติดลบ ระบบอนุญาตให้บันทึกเพราะส่วนลดเป็น Promotion ของร้าน" : "The shop service share is negative. Saving is allowed because the promotion is borne by the shop."}</p>}
        <div className="dialog-actions settlement-actions"><button type="button" disabled={state === "saving"} onClick={onClose}>{locale === "th" ? "ไว้กรอกภายหลัง" : "Save later"}</button><button type="button" className="confirm-button" disabled={state === "saving" || invalidAmount || invalidTip || missingTherapist} onClick={() => { void save(); }}>{state === "saving" ? (locale === "th" ? "กำลังบันทึก…" : "Saving…") : settlement.settled ? (locale === "th" ? "บันทึกการแก้ไข" : "Save revision") : (locale === "th" ? "ยืนยันสรุปรายได้" : "Save settlement")}</button></div>
      </>}
    </div>
  </div>;
}
