"use client";

import type { Locale } from "@spa/shared-types";
import type { User } from "firebase/auth";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { useAdminFeedback } from "@/components/admin-feedback";
import { adminApi, adminDownload } from "@/lib/admin-api";

type Permissions = { manageCampaigns: boolean; viewPii: boolean; exportCrm: boolean; searchCoupons: boolean; redeemCoupons: boolean; voidCoupons: boolean };
type Context = { role: "ADMIN" | "STAFF"; roleLabel: string; branchIds: string[]; permissions: Permissions };
type CampaignStatus = "DRAFT" | "ACTIVE" | "PAUSED" | "ENDED";
type Campaign = { code: string; branchId: string; nameTh: string; nameEn: string; descriptionTh?: string; descriptionEn?: string; status: CampaignStatus; amountSatang: number; startsAt?: string; endsAt?: string; couponExpiresAt?: string; version: number };
type Customer = { customerId: string; displayName: string; phoneMasked: string; friendStatus: string; campaignCode: string; claimedAt?: string; birthdayMarketingStatus: string };
type Pii = { fullName?: string; phoneE164?: string; birthDay?: number; birthMonth?: number; gender?: string };
type Coupon = { couponId: string; code: string; campaignCode: string; campaignName?: string; customerDisplayName?: string; customerPhoneMasked?: string; status: string; effectiveStatus: string; amountSatang: number; currency: string; expiresAt?: string; version: number };
type Tab = "crm" | "campaigns" | "coupons";

const defaultPermissions: Permissions = { manageCampaigns: false, viewPii: false, exportCrm: false, searchCoupons: false, redeemCoupons: false, voidCoupons: false };

function dateTimeLocal(value?: string): string {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Bangkok" }).formatToParts(new Date(value));
  const get = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

function isoBangkok(value: FormDataEntryValue | null): string | null {
  const text = String(value ?? "");
  return text ? `${text}:00+07:00` : null;
}

function formattedDate(value: string | undefined, locale: Locale): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok" }).format(new Date(value));
}

function Status({ value }: { value: string }) {
  return <span className={`campaign-status campaign-status-${value.toLowerCase()}`}>{value}</span>;
}

export function CampaignOperations({ user, locale }: { user: User; locale: Locale }) {
  const { notify, requestConfirmation } = useAdminFeedback();
  const [tab, setTab] = useState<Tab>("crm");
  const [context, setContext] = useState<Context | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [pii, setPii] = useState<Pii | null>(null);
  const [coupon, setCoupon] = useState<Coupon | null>(null);
  const [campaignFilter, setCampaignFilter] = useState("");
  const [customerQuery, setCustomerQuery] = useState("");
  const [couponCode, setCouponCode] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const branchId = context?.branchIds[0] ?? "";
  const permissions = context?.permissions ?? defaultPermissions;

  const loadCampaigns = useCallback(async (branch: string) => {
    const result = await adminApi<{ items: Campaign[] }>(user, `/campaigns?branchId=${encodeURIComponent(branch)}`);
    setCampaigns(result.items);
  }, [user]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const result = await adminApi<Context>(user, "/me");
        if (!active) return;
        setContext(result);
        await loadCampaigns(result.branchIds[0]);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Unable to load campaign workspace");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [loadCampaigns, user]);

  const loadCustomers = useCallback(async () => {
    if (!branchId) return;
    setBusy(true);
    try {
      const params = new URLSearchParams({ branchId, limit: "200" });
      if (campaignFilter) params.set("campaignCode", campaignFilter);
      if (customerQuery.trim()) params.set("query", customerQuery.trim());
      const result = await adminApi<{ items: Customer[] }>(user, `/campaign-customers?${params}`);
      setCustomers(result.items);
    } catch (caught) {
      notify({ tone: "error", title: locale === "th" ? "โหลดข้อมูล CRM ไม่สำเร็จ" : "CRM data unavailable", message: caught instanceof Error ? caught.message : undefined });
    } finally { setBusy(false); }
  }, [branchId, campaignFilter, customerQuery, locale, notify, user]);

  useEffect(() => {
    if (tab !== "crm" || !branchId) return;
    queueMicrotask(() => void loadCustomers());
  }, [branchId, campaignFilter, loadCustomers, tab]);

  async function revealPii(customer: Customer) {
    const confirmation = await requestConfirmation({
      title: locale === "th" ? "เปิดดูข้อมูลส่วนบุคคล?" : "Reveal personal data?",
      message: locale === "th" ? "การเปิดดูครั้งนี้จะถูกบันทึกใน Audit Log" : "This access will be recorded in the audit log.",
      confirmLabel: locale === "th" ? "ยืนยันเปิดดู" : "Reveal data", cancelLabel: locale === "th" ? "ยกเลิก" : "Cancel",
      input: { label: locale === "th" ? "เหตุผลที่จำเป็นต้องเปิดดู" : "Business reason", required: true, maxLength: 300 }
    });
    if (!confirmation.confirmed) return;
    try {
      const result = await adminApi<Pii>(user, `/campaign-customers/${encodeURIComponent(customer.customerId)}/pii-access`, { method: "POST", body: JSON.stringify({ branchId, reason: confirmation.inputValue }) });
      setSelectedCustomer(customer); setPii(result);
    } catch (caught) { notify({ tone: "error", title: locale === "th" ? "เปิดข้อมูลไม่สำเร็จ" : "PII access failed", message: caught instanceof Error ? caught.message : undefined }); }
  }

  async function exportCsv() {
    if (!branchId) return;
    const confirmation = await requestConfirmation({ title: locale === "th" ? "ส่งออกข้อมูล CRM?" : "Export CRM data?", message: locale === "th" ? "ไฟล์จะมีเฉพาะผู้ที่ยินยอม BIRTHDAY_MARKETING และการส่งออกจะถูก Audit" : "Only BIRTHDAY_MARKETING consented customers are included. The export is audited.", confirmLabel: locale === "th" ? "ดาวน์โหลด CSV" : "Download CSV", cancelLabel: locale === "th" ? "ยกเลิก" : "Cancel" });
    if (!confirmation.confirmed) return;
    try {
      await adminDownload(user, "/campaign-customers:export", { method: "POST", body: JSON.stringify({ branchId, campaignCode: campaignFilter || null }) });
      notify({ tone: "success", title: locale === "th" ? "ดาวน์โหลด CSV แล้ว" : "CSV downloaded" });
    } catch (caught) { notify({ tone: "error", title: locale === "th" ? "Export ไม่สำเร็จ" : "Export failed", message: caught instanceof Error ? caught.message : undefined }); }
  }

  async function saveCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedCampaign) return;
    const data = new FormData(event.currentTarget); setBusy(true);
    try {
      const updated = await adminApi<Campaign>(user, `/campaigns/${encodeURIComponent(selectedCampaign.code)}`, { method: "PATCH", body: JSON.stringify({ expectedVersion: selectedCampaign.version, nameTh: data.get("nameTh"), nameEn: data.get("nameEn"), descriptionTh: data.get("descriptionTh"), descriptionEn: data.get("descriptionEn"), startsAt: isoBangkok(data.get("startsAt")), endsAt: isoBangkok(data.get("endsAt")), couponExpiresAt: isoBangkok(data.get("couponExpiresAt")), ...(selectedCampaign.status === "DRAFT" ? { amountSatang: Math.round(Number(data.get("amountBaht")) * 100) } : {}) }) });
      setSelectedCampaign(updated); setCampaigns((items) => items.map((item) => item.code === updated.code ? updated : item));
      notify({ tone: "success", title: locale === "th" ? "บันทึก Campaign แล้ว" : "Campaign saved" });
    } catch (caught) { notify({ tone: "error", title: locale === "th" ? "บันทึกไม่สำเร็จ" : "Save failed", message: caught instanceof Error ? caught.message : undefined }); }
    finally { setBusy(false); }
  }

  async function changeCampaignStatus(targetStatus: "ACTIVE" | "PAUSED" | "ENDED") {
    if (!selectedCampaign) return;
    const confirmation = await requestConfirmation({ title: locale === "th" ? `เปลี่ยนสถานะเป็น ${targetStatus}?` : `Change status to ${targetStatus}?`, message: locale === "th" ? "ระบบจะบันทึกผู้ดำเนินการและเวลาใน Audit Log" : "Actor and time will be recorded in the audit log.", confirmLabel: locale === "th" ? "ยืนยัน" : "Confirm", cancelLabel: locale === "th" ? "ยกเลิก" : "Cancel", tone: targetStatus === "ENDED" ? "danger" : "default" });
    if (!confirmation.confirmed) return;
    try {
      const updated = await adminApi<Campaign>(user, `/campaigns/${encodeURIComponent(selectedCampaign.code)}:transition`, { method: "POST", body: JSON.stringify({ targetStatus, expectedVersion: selectedCampaign.version, commandId: crypto.randomUUID() }) });
      setSelectedCampaign(updated); setCampaigns((items) => items.map((item) => item.code === updated.code ? updated : item));
      notify({ tone: "success", title: locale === "th" ? "อัปเดตสถานะแล้ว" : "Status updated" });
    } catch (caught) { notify({ tone: "error", title: locale === "th" ? "เปลี่ยนสถานะไม่สำเร็จ" : "Transition failed", message: caught instanceof Error ? caught.message : undefined }); }
  }

  async function findCoupon(event: FormEvent) {
    event.preventDefault(); if (!couponCode.trim() || !branchId) return; setBusy(true); setCoupon(null);
    try { setCoupon(await adminApi<Coupon>(user, `/coupons:search?branchId=${encodeURIComponent(branchId)}&code=${encodeURIComponent(couponCode.trim())}`)); }
    catch (caught) { notify({ tone: "error", title: locale === "th" ? "ไม่พบคูปอง" : "Coupon unavailable", message: caught instanceof Error ? caught.message : undefined }); }
    finally { setBusy(false); }
  }

  async function couponAction(action: "redeem" | "void") {
    if (!coupon || !branchId) return;
    const confirmation = await requestConfirmation({ title: action === "redeem" ? (locale === "th" ? "ยืนยันใช้คูปอง?" : "Redeem this coupon?") : (locale === "th" ? "ยกเลิกคูปองนี้?" : "Void this coupon?"), message: `${coupon.code} • ${coupon.customerDisplayName ?? "—"} • ${(coupon.amountSatang / 100).toLocaleString()} THB`, confirmLabel: action === "redeem" ? (locale === "th" ? "ยืนยัน Redeem" : "Confirm redeem") : (locale === "th" ? "ยืนยัน Void" : "Confirm void"), cancelLabel: locale === "th" ? "กลับ" : "Go back", tone: action === "void" ? "danger" : "default", ...(action === "void" ? { input: { label: locale === "th" ? "เหตุผลในการ Void" : "Void reason", required: true, maxLength: 300 } } : {}) });
    if (!confirmation.confirmed) return;
    try {
      const result = await adminApi<{ status: string; version: number }>(user, `/coupons/${encodeURIComponent(coupon.couponId)}:${action}`, { method: "POST", body: JSON.stringify({ branchId, expectedVersion: coupon.version, commandId: crypto.randomUUID(), reason: confirmation.inputValue || null }) });
      setCoupon({ ...coupon, status: result.status, effectiveStatus: result.status, version: result.version });
      notify({ tone: "success", title: action === "redeem" ? (locale === "th" ? "Redeem สำเร็จ" : "Coupon redeemed") : (locale === "th" ? "Void สำเร็จ" : "Coupon voided") });
    } catch (caught) { notify({ tone: "error", title: locale === "th" ? "ดำเนินการไม่สำเร็จ" : "Action failed", message: caught instanceof Error ? caught.message : undefined }); }
  }

  const nextStatuses = useMemo(() => selectedCampaign?.status === "DRAFT" ? ["ACTIVE"] : selectedCampaign?.status === "ACTIVE" ? ["PAUSED", "ENDED"] : selectedCampaign?.status === "PAUSED" ? ["ACTIVE", "ENDED"] : [], [selectedCampaign]);

  if (loading) return <main className="dashboard-content"><div className="module-state" role="status">{locale === "th" ? "กำลังโหลดพื้นที่ CRM…" : "Loading CRM workspace…"}</div></main>;
  if (error || !context) return <main className="dashboard-content"><div className="module-state error" role="alert">{error}</div></main>;

  return <main className="dashboard-content campaign-operations">
    <div className="module-heading"><p className="eyebrow">CUSTOMER OPERATIONS • {context.roleLabel}</p><h1>{locale === "th" ? "ลูกค้า แคมเปญ และคูปอง" : "Customers, campaigns & coupons"}</h1><p>{locale === "th" ? "จัดการข้อมูลจาก LINE Campaign ภายใต้สิทธิ์และ Audit Log" : "Operate LINE campaign data with role controls and audit trails"}</p></div>
    <nav className="campaign-tabs" aria-label={locale === "th" ? "เมนู CRM" : "CRM sections"}>{(["crm", "campaigns", "coupons"] as Tab[]).map((item) => <button key={item} aria-current={tab === item ? "page" : undefined} onClick={() => { setTab(item); setPii(null); setSelectedCustomer(null); }}>{item === "crm" ? "CRM" : item === "campaigns" ? (locale === "th" ? "แคมเปญ" : "Campaigns") : (locale === "th" ? "คูปอง" : "Coupons")}</button>)}</nav>

    {tab === "crm" && <section className="module-panel">
      <div className="campaign-toolbar"><div><h2>{locale === "th" ? "ลูกค้าจาก Campaign" : "Campaign customers"}</h2><p>{customers.length} {locale === "th" ? "รายการ • ข้อมูลถูก masked โดยค่าเริ่มต้น" : "records • masked by default"}</p></div><div className="campaign-toolbar-actions"><select aria-label="Campaign" value={campaignFilter} onChange={(event) => setCampaignFilter(event.target.value)}><option value="">{locale === "th" ? "ทุก Campaign" : "All campaigns"}</option>{campaigns.map((item) => <option value={item.code} key={item.code}>{item.nameTh || item.nameEn}</option>)}</select>{permissions.exportCrm && <button className="primary-compact-button" onClick={exportCsv}>{locale === "th" ? "Export CSV" : "Export CSV"}</button>}</div></div>
      <form className="campaign-search" onSubmit={(event) => { event.preventDefault(); void loadCustomers(); }}><label><span className="sr-only">{locale === "th" ? "ค้นหาลูกค้า" : "Search customers"}</span><input value={customerQuery} onChange={(event) => setCustomerQuery(event.target.value)} placeholder={locale === "th" ? "ค้นหาชื่อ Customer ID หรือเบอร์ที่ masked" : "Search name, customer ID, or masked phone"} /></label><button disabled={busy}>{locale === "th" ? "ค้นหา" : "Search"}</button></form>
      <div className="table-scroll"><table><thead><tr><th>{locale === "th" ? "ลูกค้า" : "Customer"}</th><th>{locale === "th" ? "แคมเปญ" : "Campaign"}</th><th>LINE</th><th>BIRTHDAY MARKETING</th><th>{locale === "th" ? "รับสิทธิ์เมื่อ" : "Claimed"}</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{customers.map((item) => <tr key={`${item.campaignCode}-${item.customerId}`}><td><strong>{item.displayName}</strong><small>{item.phoneMasked} • {item.customerId}</small></td><td>{item.campaignCode}</td><td><Status value={item.friendStatus} /></td><td><Status value={item.birthdayMarketingStatus} /></td><td>{formattedDate(item.claimedAt, locale)}</td><td>{permissions.viewPii && <button className="row-action" onClick={() => revealPii(item)} aria-label={locale === "th" ? `เปิดข้อมูลส่วนบุคคล ${item.displayName}` : `Reveal PII for ${item.displayName}`}>→</button>}</td></tr>)}</tbody></table></div>
      {!customers.length && <div className="empty-state">{locale === "th" ? "ยังไม่มีลูกค้าที่ตรงกับตัวกรอง" : "No customers match these filters"}</div>}
    </section>}

    {tab === "campaigns" && <section className="module-panel"><div className="panel-title"><div><h2>{locale === "th" ? "รายการ Campaign" : "Campaign list"}</h2><small>{permissions.manageCampaigns ? (locale === "th" ? "เลือก Campaign เพื่อแก้ไขหรือเปลี่ยนสถานะ" : "Select a campaign to edit or transition") : (locale === "th" ? "สิทธิ์อ่านอย่างเดียว" : "Read-only access")}</small></div></div><div className="table-scroll"><table><thead><tr><th>Campaign</th><th>{locale === "th" ? "ส่วนลด" : "Benefit"}</th><th>{locale === "th" ? "ช่วงเวลา" : "Window"}</th><th>{locale === "th" ? "สถานะ" : "Status"}</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{campaigns.map((item) => <tr key={item.code}><td><strong>{locale === "th" ? item.nameTh : item.nameEn}</strong><small>{item.code}</small></td><td>{(item.amountSatang / 100).toLocaleString()} THB</td><td><small>{formattedDate(item.startsAt, locale)}</small><small>{formattedDate(item.endsAt, locale)}</small></td><td><Status value={item.status} /></td><td>{permissions.manageCampaigns && <button className="row-action" onClick={() => setSelectedCampaign(item)}>→</button>}</td></tr>)}</tbody></table></div></section>}

    {tab === "coupons" && <section className="coupon-workspace"><form className="coupon-search-panel" onSubmit={findCoupon}><p className="eyebrow">EXACT CODE SEARCH</p><h2>{locale === "th" ? "ค้นหาคูปอง" : "Find coupon"}</h2><p>{locale === "th" ? "กรอกรหัสเต็มเพื่อตรวจสอบก่อน Redeem" : "Enter the full code to validate it before redemption."}</p><label>{locale === "th" ? "Coupon code" : "Coupon code"}<input autoCapitalize="characters" value={couponCode} onChange={(event) => setCouponCode(event.target.value.toUpperCase())} placeholder="W50-XXXXXXXXXX" /></label><button disabled={busy || !couponCode.trim()}>{busy ? (locale === "th" ? "กำลังค้นหา…" : "Searching…") : (locale === "th" ? "ตรวจสอบคูปอง" : "Check coupon")}</button></form>{coupon && <article className="coupon-result" aria-live="polite"><div className="coupon-result-heading"><div><p className="eyebrow">{coupon.campaignCode}</p><h2>{coupon.code}</h2></div><Status value={coupon.effectiveStatus} /></div><dl><div><dt>{locale === "th" ? "ลูกค้า" : "Customer"}</dt><dd>{coupon.customerDisplayName ?? "—"}<small>{coupon.customerPhoneMasked}</small></dd></div><div><dt>{locale === "th" ? "สิทธิ์" : "Benefit"}</dt><dd>{(coupon.amountSatang / 100).toLocaleString()} THB</dd></div><div><dt>{locale === "th" ? "หมดอายุ" : "Expires"}</dt><dd>{formattedDate(coupon.expiresAt, locale)}</dd></div></dl><div className="coupon-actions"><button className="confirm-button" disabled={coupon.effectiveStatus !== "ISSUED" || !permissions.redeemCoupons} onClick={() => couponAction("redeem")}>{locale === "th" ? "ยืนยัน Redeem" : "Confirm redeem"}</button>{permissions.voidCoupons && <button className="cancel-button" disabled={coupon.effectiveStatus !== "ISSUED"} onClick={() => couponAction("void")}>Void coupon</button>}</div></article>}</section>}

    {selectedCampaign && <div className="drawer-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedCampaign(null); }}><aside className="campaign-drawer" role="dialog" aria-modal="true" aria-labelledby="campaign-editor-title"><div className="service-drawer-title"><div><strong id="campaign-editor-title">{locale === "th" ? "แก้ไข Campaign" : "Edit campaign"}</strong><span>{selectedCampaign.code} • v{selectedCampaign.version}</span></div><button aria-label="Close" onClick={() => setSelectedCampaign(null)}>×</button></div><form className="campaign-editor" onSubmit={saveCampaign}><label>{locale === "th" ? "ชื่อภาษาไทย" : "Thai name"}<input name="nameTh" defaultValue={selectedCampaign.nameTh} required /></label><label>{locale === "th" ? "ชื่อภาษาอังกฤษ" : "English name"}<input name="nameEn" defaultValue={selectedCampaign.nameEn} required /></label><label>{locale === "th" ? "คำอธิบายภาษาไทย" : "Thai description"}<textarea name="descriptionTh" defaultValue={selectedCampaign.descriptionTh} /></label><label>{locale === "th" ? "คำอธิบายภาษาอังกฤษ" : "English description"}<textarea name="descriptionEn" defaultValue={selectedCampaign.descriptionEn} /></label><div className="campaign-editor-grid"><label>{locale === "th" ? "เริ่ม" : "Starts"}<input type="datetime-local" name="startsAt" defaultValue={dateTimeLocal(selectedCampaign.startsAt)} required /></label><label>{locale === "th" ? "สิ้นสุด" : "Ends"}<input type="datetime-local" name="endsAt" defaultValue={dateTimeLocal(selectedCampaign.endsAt)} required /></label></div><label>{locale === "th" ? "คูปองหมดอายุ" : "Coupon expiry"}<input type="datetime-local" name="couponExpiresAt" defaultValue={dateTimeLocal(selectedCampaign.couponExpiresAt)} required /></label><label>{locale === "th" ? "ส่วนลด (บาท)" : "Discount (THB)"}<input type="number" name="amountBaht" min="0.01" step="0.01" defaultValue={selectedCampaign.amountSatang / 100} disabled={selectedCampaign.status !== "DRAFT"} /></label><p className="campaign-rule">{locale === "th" ? "จำนวนส่วนลดแก้ได้เฉพาะสถานะ DRAFT" : "Benefit amount is editable only while DRAFT."}</p><button className="primary-compact-button" disabled={busy}>{locale === "th" ? "บันทึกการแก้ไข" : "Save changes"}</button></form>{nextStatuses.length > 0 && <div className="campaign-transitions"><strong>{locale === "th" ? "เปลี่ยนสถานะ" : "Change status"}</strong>{nextStatuses.map((status) => <button key={status} className={status === "ENDED" ? "danger-link" : ""} onClick={() => changeCampaignStatus(status as "ACTIVE" | "PAUSED" | "ENDED")}>{status}</button>)}</div>}</aside></div>}

    {selectedCustomer && pii && <div className="drawer-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) { setSelectedCustomer(null); setPii(null); } }}><aside className="campaign-drawer pii-drawer" role="dialog" aria-modal="true" aria-labelledby="pii-title"><div className="service-drawer-title"><div><strong id="pii-title">{locale === "th" ? "ข้อมูลส่วนบุคคล" : "Personal data"}</strong><span>{selectedCustomer.customerId}</span></div><button aria-label="Close" onClick={() => { setSelectedCustomer(null); setPii(null); }}>×</button></div><div className="pii-warning">{locale === "th" ? "การเปิดดูข้อมูลนี้ถูกบันทึกใน Audit Log แล้ว" : "This access has been recorded in the audit log."}</div><dl className="pii-detail"><div><dt>{locale === "th" ? "ชื่อ-นามสกุล" : "Full name"}</dt><dd>{pii.fullName ?? "—"}</dd></div><div><dt>{locale === "th" ? "เบอร์โทรศัพท์" : "Phone"}</dt><dd>{pii.phoneE164 ?? "—"}</dd></div><div><dt>{locale === "th" ? "วัน/เดือนเกิด" : "Day/month of birth"}</dt><dd>{pii.birthDay && pii.birthMonth ? `${pii.birthDay}/${pii.birthMonth}` : "—"}</dd></div><div><dt>{locale === "th" ? "เพศ" : "Gender"}</dt><dd>{pii.gender ?? "—"}</dd></div></dl></aside></div>}
  </main>;
}
