"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { loadLiff, type LiffClient } from "@/lib/line-liff";

type Locale = "th" | "en";
type Campaign = {
  code: string;
  nameTh: string;
  nameEn: string;
  descriptionTh?: string | null;
  descriptionEn?: string | null;
  benefit: { amountSatang: number; currency: string };
  endsAt?: string | null;
};
type CouponResult = {
  alreadyClaimed: boolean;
  coupon: {
    code: string;
    status: string;
    amountSatang: number;
    currency: string;
    issuedAt: string;
    expiresAt?: string | null;
  };
};

const copy = {
  th: {
    eyebrow: "สิทธิพิเศษสำหรับเพื่อน LINE",
    defaultTitle: "รับส่วนลด 50 บาท",
    lead: "กรอกข้อมูลให้ครบ แล้วรับคูปองดิจิทัลได้ทันที",
    fullName: "ชื่อ-นามสกุล",
    phone: "เบอร์โทรศัพท์",
    birthday: "วัน/เดือนเกิด",
    birthdayHint: "เราไม่เก็บปีเกิดสำหรับแคมเปญนี้",
    day: "วัน",
    month: "เดือน",
    gender: "เพศ (ไม่บังคับ)",
    genderPlaceholder: "ไม่ระบุ",
    female: "หญิง",
    male: "ชาย",
    nonBinary: "นอนไบนารี / อื่น ๆ",
    preferNot: "ไม่ประสงค์ระบุ",
    privacy: "ฉันรับทราบการเก็บและใช้ข้อมูลเพื่อดำเนินการออกคูปองตาม",
    privacyLink: "ประกาศความเป็นส่วนตัว",
    marketing: "ยินยอมให้ใช้วัน/เดือนเกิดเพื่อส่งสิทธิพิเศษวันเกิดและข่าวสารการตลาด (ไม่บังคับ)",
    marketingHint: "ไม่เลือกข้อนี้ก็ยังรับคูปองได้",
    submit: "ยืนยันรับสิทธิ์ 50 บาท",
    submitting: "กำลังออกคูปอง…",
    required: "จำเป็น",
    lineLoading: "กำลังเชื่อมต่อบัญชี LINE…",
    campaignLoading: "กำลังโหลดสิทธิพิเศษ…",
    loginRedirect: "กำลังพาไปยืนยันตัวตนกับ LINE…",
    configError: "ไม่สามารถเปิดสิทธิพิเศษนี้ได้ กรุณาลองใหม่จาก Rich Menu",
    formError: "กรุณาตรวจสอบข้อมูลที่จำเป็นให้ครบถ้วน",
    submitError: "ยังออกคูปองไม่ได้ กรุณาลองอีกครั้ง",
    success: "รับคูปองเรียบร้อยแล้ว",
    already: "คุณเคยรับสิทธิ์นี้แล้ว นี่คือคูปองของคุณ",
    couponLabel: "คูปองส่วนลด",
    expires: "ใช้ได้ถึง",
    staffNote: "แสดงหน้าจอนี้ให้พนักงานก่อนชำระเงิน กรุณาอย่าเผยแพร่รหัสคูปอง",
    close: "กลับไปที่ LINE",
    retry: "ลองอีกครั้ง"
  },
  en: {
    eyebrow: "LINE FRIEND EXCLUSIVE",
    defaultTitle: "Get THB 50 off",
    lead: "Complete the form to receive your digital coupon instantly.",
    fullName: "Full name",
    phone: "Phone number",
    birthday: "Birth day/month",
    birthdayHint: "We do not collect your birth year for this campaign.",
    day: "Day",
    month: "Month",
    gender: "Gender (optional)",
    genderPlaceholder: "Not specified",
    female: "Female",
    male: "Male",
    nonBinary: "Non-binary / other",
    preferNot: "Prefer not to say",
    privacy: "I acknowledge the collection and use of my data to issue this coupon under the",
    privacyLink: "Privacy Notice",
    marketing: "I consent to using my birth day/month for birthday offers and marketing (optional).",
    marketingHint: "You can receive the coupon without selecting this.",
    submit: "Confirm and get THB 50",
    submitting: "Issuing coupon…",
    required: "required",
    lineLoading: "Connecting to LINE…",
    campaignLoading: "Loading offer…",
    loginRedirect: "Redirecting to LINE login…",
    configError: "This offer cannot be opened. Please try again from the Rich Menu.",
    formError: "Please complete all required information.",
    submitError: "We could not issue the coupon. Please try again.",
    success: "Your coupon is ready",
    already: "You have already claimed this offer. Here is your coupon.",
    couponLabel: "Discount coupon",
    expires: "Valid until",
    staffNote: "Show this screen to staff before payment. Do not share your coupon code.",
    close: "Back to LINE",
    retry: "Try again"
  }
} as const;

const monthLabels = {
  th: ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
};

function amountLabel(amountSatang: number, locale: Locale) {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-TH", {
    style: "currency",
    currency: "THB",
    currencyDisplay: "narrowSymbol",
    maximumFractionDigits: 0
  }).format(amountSatang / 100);
}

function expirationLabel(value: string, locale: Locale) {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    dateStyle: "medium",
    timeZone: "Asia/Bangkok"
  }).format(new Date(value));
}

function daysInMonth(month: number) {
  return month === 2 ? 29 : [4, 6, 9, 11].includes(month) ? 30 : 31;
}

export function CampaignRegistration({ campaignCode }: { campaignCode: string }) {
  const router = useRouter();
  const [locale, setLocale] = useState<Locale>("th");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [lineToken, setLineToken] = useState<string | null>(null);
  const [liffClient, setLiffClient] = useState<LiffClient | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "redirecting" | "ready" | "error">("loading");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [birthDay, setBirthDay] = useState("");
  const [birthMonth, setBirthMonth] = useState("");
  const [gender, setGender] = useState("");
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false);
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<CouponResult | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const t = copy[locale];
  const maximumDay = birthMonth ? daysInMonth(Number(birthMonth)) : 31;
  const valid = fullName.trim().length >= 2 && /^0[0-9\s-]{8,}$/.test(phone.trim()) && Boolean(birthDay) && Boolean(birthMonth) && privacyAcknowledged;

  useEffect(() => { document.documentElement.lang = locale; }, [locale]);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`/api/spa/api/v1/public/campaigns/${encodeURIComponent(campaignCode)}`, { cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error("Campaign unavailable");
        return response.json() as Promise<Campaign>;
      }),
      fetch("/api/config", { cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error("LIFF config unavailable");
        const config = await response.json() as { lineCampaignV1LiffId?: string };
        if (!config.lineCampaignV1LiffId) throw new Error("Campaign v1 LIFF is not configured");
        const liff = await loadLiff();
        await liff.init({ liffId: config.lineCampaignV1LiffId });
        if (!liff.isLoggedIn()) {
          if (active) setLoadState("redirecting");
          liff.login({ redirectUri: window.location.href });
          return null;
        }
        const token = liff.getIDToken();
        if (!token) throw new Error("LINE ID token unavailable");
        return { liff, token };
      })
    ]).then(([campaignPayload, line]) => {
      if (!active || !line) return;
      setCampaign(campaignPayload);
      setLiffClient(line.liff);
      setLineToken(line.token);
      setLoadState("ready");
    }).catch(() => active && setLoadState("error"));
    return () => { active = false; };
  }, [campaignCode]);

  const idempotencyKey = useMemo(() => {
    if (typeof window === "undefined") return "";
    const storageKey = `spa49-campaign-idempotency:${campaignCode}`;
    const existing = window.sessionStorage.getItem(storageKey);
    if (existing) return existing;
    const created = crypto.randomUUID();
    window.sessionStorage.setItem(storageKey, created);
    return created;
  }, [campaignCode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShowValidation(true);
    setSubmitError(null);
    if (!valid || !lineToken) {
      queueMicrotask(() => errorRef.current?.focus());
      return;
    }
    setIsSubmitting(true);
    try {
      const response = await fetch(`/api/spa/api/v1/public/campaigns/${encodeURIComponent(campaignCode)}/claims`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey
        },
        body: JSON.stringify({
          fullName,
          phone,
          birthDay: Number(birthDay),
          birthMonth: Number(birthMonth),
          gender: gender || null,
          privacyAcknowledged,
          birthdayMarketingConsent: marketingConsent,
          lineIdToken: lineToken
        })
      });
      if (!response.ok) throw new Error("Claim failed");
      setResult(await response.json() as CouponResult);
    } catch {
      setSubmitError(t.submitError);
      queueMicrotask(() => errorRef.current?.focus());
    } finally {
      setIsSubmitting(false);
    }
  }

  function closeLiff() {
    if (liffClient?.isInClient() && liffClient.closeWindow) liffClient.closeWindow();
    else router.push("/");
  }

  if (loadState !== "ready" || !campaign) {
    const message = loadState === "error" ? t.configError : loadState === "redirecting" ? t.loginRedirect : t.campaignLoading;
    return (
      <main className="campaign-state" id="main-content">
        <div className="campaign-state-mark" aria-hidden="true">49</div>
        <p role={loadState === "error" ? "alert" : "status"}>{message}</p>
        {loadState === "error" && <button className="primary-button" type="button" onClick={() => window.location.reload()}>{t.retry}</button>}
      </main>
    );
  }

  if (result) {
    return (
      <main className="campaign-shell campaign-success" id="main-content">
        <header className="campaign-header">
          <a className="brand" href="#main-content"><span><strong>SPA 49</strong><small>RELAX · RENEW · REVIVE</small></span></a>
          <LanguageSwitch locale={locale} setLocale={setLocale} />
        </header>
        <section className="coupon-result" aria-live="polite">
          <div className="success-mark" aria-hidden="true">✓</div>
          <p className="eyebrow">{t.eyebrow}</p>
          <h1>{t.success}</h1>
          <p>{result.alreadyClaimed ? t.already : t.lead}</p>
          <div className="digital-coupon">
            <span>{t.couponLabel}</span>
            <strong>{amountLabel(result.coupon.amountSatang, locale)}</strong>
            <code>{result.coupon.code}</code>
            {result.coupon.expiresAt && <small>{t.expires} {expirationLabel(result.coupon.expiresAt, locale)}</small>}
          </div>
          <p className="staff-note">{t.staffNote}</p>
          <button className="primary-button coupon-close" type="button" onClick={closeLiff}>{t.close}</button>
        </section>
      </main>
    );
  }

  return (
    <main className="campaign-shell" id="main-content">
      <header className="campaign-header">
        <a className="brand" href="#main-content"><span><strong>SPA 49</strong><small>RELAX · RENEW · REVIVE</small></span></a>
        <LanguageSwitch locale={locale} setLocale={setLocale} />
      </header>
      <section className="campaign-offer">
        <div>
          <p className="eyebrow">{t.eyebrow}</p>
          <h1>{locale === "th" ? campaign.nameTh : campaign.nameEn}</h1>
          <p>{(locale === "th" ? campaign.descriptionTh : campaign.descriptionEn) || t.lead}</p>
        </div>
        <div className="offer-amount" aria-label={`${amountLabel(campaign.benefit.amountSatang, locale)} discount`}>
          <span>{locale === "th" ? "ลด" : "OFF"}</span>
          <strong>{amountLabel(campaign.benefit.amountSatang, locale)}</strong>
        </div>
      </section>
      <form className="campaign-form" onSubmit={submit} noValidate>
        {showValidation && !valid && <div className="validation-summary" role="alert" tabIndex={-1} ref={errorRef}>{t.formError}</div>}
        {submitError && <div className="validation-summary" role="alert" tabIndex={-1} ref={errorRef}>{submitError}</div>}
        <div className="campaign-form-section">
          <label className="field">{t.fullName} <span className="required-mark">* <span className="sr-only">{t.required}</span></span>
            <input type="text" autoComplete="name" value={fullName} onChange={(event) => setFullName(event.target.value)} aria-invalid={showValidation && fullName.trim().length < 2} placeholder={locale === "th" ? "เช่น มณี สุขใจ" : "e.g. Manee Sukjai"} />
          </label>
          <label className="field">{t.phone} <span className="required-mark">* <span className="sr-only">{t.required}</span></span>
            <input type="tel" inputMode="tel" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} aria-invalid={showValidation && !/^0[0-9\s-]{8,}$/.test(phone.trim())} placeholder="08x-xxx-xxxx" />
          </label>
          <fieldset className="birthday-fieldset">
            <legend>{t.birthday} <span className="required-mark">* <span className="sr-only">{t.required}</span></span></legend>
            <p>{t.birthdayHint}</p>
            <div className="birthday-grid">
              <label htmlFor="campaign-birth-day">{t.day}
                <select id="campaign-birth-day" value={birthDay} onChange={(event) => setBirthDay(event.target.value)} aria-invalid={showValidation && !birthDay}>
                  <option value="">--</option>
                  {Array.from({ length: maximumDay }, (_, index) => index + 1).map((day) => <option key={day} value={day}>{day}</option>)}
                </select>
              </label>
              <label htmlFor="campaign-birth-month">{t.month}
                <select id="campaign-birth-month" value={birthMonth} onChange={(event) => {
                  const nextMonth = event.target.value;
                  setBirthMonth(nextMonth);
                  if (nextMonth && Number(birthDay) > daysInMonth(Number(nextMonth))) setBirthDay("");
                }} aria-invalid={showValidation && !birthMonth}>
                  <option value="">--</option>
                  {monthLabels[locale].map((month, index) => <option key={month} value={index + 1}>{month}</option>)}
                </select>
              </label>
            </div>
          </fieldset>
          <label className="field">{t.gender}
            <select value={gender} onChange={(event) => setGender(event.target.value)}>
              <option value="">{t.genderPlaceholder}</option>
              <option value="FEMALE">{t.female}</option>
              <option value="MALE">{t.male}</option>
              <option value="NON_BINARY">{t.nonBinary}</option>
              <option value="PREFER_NOT_TO_SAY">{t.preferNot}</option>
            </select>
          </label>
        </div>
        <div className="consent-section">
          <label className="consent campaign-consent">
            <input type="checkbox" checked={privacyAcknowledged} onChange={(event) => setPrivacyAcknowledged(event.target.checked)} aria-invalid={showValidation && !privacyAcknowledged} />
            <span>{t.privacy} <Link href="/privacy" target="_blank">{t.privacyLink}</Link> <span className="required-mark">*</span></span>
          </label>
          <label className="consent campaign-consent optional-consent">
            <input type="checkbox" checked={marketingConsent} onChange={(event) => setMarketingConsent(event.target.checked)} />
            <span>{t.marketing}<small>{t.marketingHint}</small></span>
          </label>
        </div>
        <button className="primary-button campaign-submit" type="submit" disabled={isSubmitting || !lineToken}>{isSubmitting ? t.submitting : t.submit}</button>
      </form>
    </main>
  );
}

function LanguageSwitch({ locale, setLocale }: { locale: Locale; setLocale: (locale: Locale) => void }) {
  return <div className="language-switch" aria-label="Language"><button type="button" aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button><button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button></div>;
}
