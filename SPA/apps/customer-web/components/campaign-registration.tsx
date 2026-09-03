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
  eligibility?: { requiresFollowing?: boolean };
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
    birthday: "วัน/เดือน/ปีเกิด",
    birthdayHint: "กรอกปีเกิดเป็น พ.ศ. เพื่อใช้วิเคราะห์ช่วงวัยและออกแบบสิทธิประโยชน์ เมื่อคุณยินยอมด้านการตลาด",
    day: "วัน",
    month: "เดือน",
    yearBuddhist: "ปีเกิด (พ.ศ.)",
    yearPlaceholder: "เช่น 2535",
    gender: "เพศ (ไม่บังคับ)",
    genderPlaceholder: "ไม่ระบุ",
    female: "หญิง",
    male: "ชาย",
    nonBinary: "นอนไบนารี / อื่น ๆ",
    preferNot: "ไม่ประสงค์ระบุ",
    privacy: "ฉันรับทราบการเก็บและใช้ข้อมูลเพื่อดำเนินการออกคูปองตาม",
    privacyLink: "ประกาศความเป็นส่วนตัว",
    marketing: "ยินยอมให้ใช้วันเดือนปีเกิดและประวัติการใช้บริการ เพื่อวิเคราะห์ช่วงวัย ออกแบบสิทธิประโยชน์ และส่งข่าวสารการตลาด (ไม่บังคับ)",
    marketingHint: "ไม่เลือกข้อนี้ก็ยังรับคูปองได้",
    submit: "ยืนยันรับสิทธิ์ 50 บาท",
    submitting: "กำลังออกคูปอง…",
    required: "จำเป็น",
    lineLoading: "กำลังเชื่อมต่อบัญชี LINE…",
    campaignLoading: "กำลังโหลดสิทธิพิเศษ…",
    loginRedirect: "กำลังพาไปยืนยันตัวตนกับ LINE…",
    configError: "ไม่สามารถเปิดสิทธิพิเศษนี้ได้ กรุณาลองใหม่จาก Rich Menu",
    friendshipTitle: "เพิ่มเพื่อน SPA 49 ก่อนรับสิทธิ์",
    friendshipBody: "คูปองนี้สำหรับเพื่อน LINE OA ของ SPA 49 กรุณาเพิ่มเพื่อนแล้วกลับมาตรวจสอบอีกครั้ง",
    friendshipAction: "เพิ่มเพื่อนและตรวจสอบ",
    friendshipChecking: "กำลังตรวจสอบสถานะเพื่อน…",
    friendshipError: "ตรวจสอบสถานะเพื่อน LINE ไม่สำเร็จ กรุณาเปิดใหม่จาก Rich Menu",
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
    birthday: "Date of birth",
    birthdayHint: "Enter the Buddhist Era year. With marketing consent, it helps us analyze age groups and design relevant benefits.",
    day: "Day",
    month: "Month",
    yearBuddhist: "Birth year (B.E.)",
    yearPlaceholder: "e.g. 2535",
    gender: "Gender (optional)",
    genderPlaceholder: "Not specified",
    female: "Female",
    male: "Male",
    nonBinary: "Non-binary / other",
    preferNot: "Prefer not to say",
    privacy: "I acknowledge the collection and use of my data to issue this coupon under the",
    privacyLink: "Privacy Notice",
    marketing: "I consent to the use of my date of birth and service history for age-group analysis, benefit design, and marketing (optional).",
    marketingHint: "You can receive the coupon without selecting this.",
    submit: "Confirm and get THB 50",
    submitting: "Issuing coupon…",
    required: "required",
    lineLoading: "Connecting to LINE…",
    campaignLoading: "Loading offer…",
    loginRedirect: "Redirecting to LINE login…",
    configError: "This offer cannot be opened. Please try again from the Rich Menu.",
    friendshipTitle: "Add SPA 49 as a friend",
    friendshipBody: "This coupon is for SPA 49 LINE OA friends. Add the account, then check again.",
    friendshipAction: "Add friend and check",
    friendshipChecking: "Checking LINE friendship…",
    friendshipError: "We could not verify your LINE friendship. Please reopen this offer from the Rich Menu.",
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

function daysInMonth(month: number, year: number) {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export function CampaignRegistration({ campaignCode }: { campaignCode: string }) {
  const router = useRouter();
  const [locale, setLocale] = useState<Locale>("th");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [lineToken, setLineToken] = useState<string | null>(null);
  const [liffClient, setLiffClient] = useState<LiffClient | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "redirecting" | "ready" | "error">("loading");
  const [friendshipState, setFriendshipState] = useState<"not-required" | "checking" | "following" | "required" | "requesting" | "error">("checking");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [birthDay, setBirthDay] = useState("");
  const [birthMonth, setBirthMonth] = useState("");
  const [birthYearBuddhist, setBirthYearBuddhist] = useState("");
  const [gender, setGender] = useState("");
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false);
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<CouponResult | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const t = copy[locale];
  const currentGregorianYear = Number(new Intl.DateTimeFormat("en-US", { year: "numeric", timeZone: "Asia/Bangkok" }).format(new Date()));
  const currentBuddhistYear = currentGregorianYear + 543;
  const birthYearGregorian = Number(birthYearBuddhist) - 543;
  const validBirthYear = /^\d{4}$/.test(birthYearBuddhist) && birthYearGregorian >= 1900 && birthYearGregorian <= currentGregorianYear;
  const calendarYear = validBirthYear ? birthYearGregorian : 2000;
  const maximumDay = birthMonth ? daysInMonth(Number(birthMonth), calendarYear) : 31;
  const validBirthDate = Boolean(birthDay) && Boolean(birthMonth) && Number(birthDay) <= maximumDay;
  const valid = fullName.trim().length >= 2 && /^0[0-9\s-]{8,}$/.test(phone.trim()) && validBirthDate && validBirthYear && privacyAcknowledged;

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
    ]).then(async ([campaignPayload, line]) => {
      if (!active || !line) return;
      setCampaign(campaignPayload);
      setLiffClient(line.liff);
      setLineToken(line.token);
      if (campaignPayload.eligibility?.requiresFollowing) {
        try {
          const friendship = await line.liff.getFriendship();
          if (!active) return;
          setFriendshipState(friendship.friendFlag ? "following" : "required");
        } catch {
          if (!active) return;
          setFriendshipState("error");
        }
      } else {
        setFriendshipState("not-required");
      }
      setLoadState("ready");
    }).catch(() => active && setLoadState("error"));
    return () => { active = false; };
  }, [campaignCode]);

  async function requestFriendship() {
    if (!liffClient?.requestFriendship) {
      setFriendshipState("error");
      return;
    }
    setFriendshipState("requesting");
    try {
      await liffClient.requestFriendship();
      const friendship = await liffClient.getFriendship();
      setFriendshipState(friendship.friendFlag ? "following" : "required");
    } catch {
      setFriendshipState("error");
    }
  }

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
          birthYear: birthYearGregorian,
          gender: gender || null,
          privacyAcknowledged,
          birthdayMarketingConsent: marketingConsent,
          lineFriendshipConfirmed: friendshipState === "following",
          lineIdToken: lineToken
        })
      });
      if (!response.ok) {
        const problem = await response.json().catch(() => null) as { code?: string } | null;
        if (problem?.code === "LINE_FRIENDSHIP_REQUIRED") {
          setFriendshipState("required");
          throw new Error("LINE_FRIENDSHIP_REQUIRED");
        }
        throw new Error("Claim failed");
      }
      setResult(await response.json() as CouponResult);
    } catch (error) {
      setSubmitError(error instanceof Error && error.message === "LINE_FRIENDSHIP_REQUIRED" ? t.friendshipBody : t.submitError);
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
      {campaign.eligibility?.requiresFollowing && friendshipState !== "following" ? (
        <section className="friendship-gate" aria-live="polite">
          <div className="friendship-mark" aria-hidden="true">LINE</div>
          <h2>{t.friendshipTitle}</h2>
          <p>{friendshipState === "error" ? t.friendshipError : t.friendshipBody}</p>
          {friendshipState === "error" ? (
            <button className="primary-button" type="button" onClick={() => window.location.reload()}>{t.retry}</button>
          ) : (
            <button className="primary-button" type="button" disabled={friendshipState === "requesting" || friendshipState === "checking"} onClick={requestFriendship}>
              {friendshipState === "requesting" || friendshipState === "checking" ? t.friendshipChecking : t.friendshipAction}
            </button>
          )}
        </section>
      ) : (
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
          <fieldset className="birthday-fieldset" aria-describedby="campaign-birthday-hint">
            <legend>{t.birthday} <span className="required-mark">* <span className="sr-only">{t.required}</span></span></legend>
            <p id="campaign-birthday-hint">{t.birthdayHint}</p>
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
                  if (nextMonth && Number(birthDay) > daysInMonth(Number(nextMonth), calendarYear)) setBirthDay("");
                }} aria-invalid={showValidation && !birthMonth}>
                  <option value="">--</option>
                  {monthLabels[locale].map((month, index) => <option key={month} value={index + 1}>{month}</option>)}
                </select>
              </label>
              <label htmlFor="campaign-birth-year">{t.yearBuddhist}
                <input id="campaign-birth-year" type="number" inputMode="numeric" min="2443" max={currentBuddhistYear} step="1" value={birthYearBuddhist} onChange={(event) => {
                  const nextYear = event.target.value;
                  const nextGregorianYear = Number(nextYear) - 543;
                  setBirthYearBuddhist(nextYear);
                  if (/^\d{4}$/.test(nextYear) && nextGregorianYear >= 1900 && nextGregorianYear <= currentGregorianYear && birthMonth && Number(birthDay) > daysInMonth(Number(birthMonth), nextGregorianYear)) setBirthDay("");
                }} aria-invalid={showValidation && !validBirthYear} placeholder={t.yearPlaceholder} />
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
      )}
    </main>
  );
}

function LanguageSwitch({ locale, setLocale }: { locale: Locale; setLocale: (locale: Locale) => void }) {
  return <div className="language-switch" aria-label="Language"><button type="button" aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button><button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button></div>;
}
