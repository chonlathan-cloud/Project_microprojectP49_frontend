"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { loadLiff } from "@/lib/line-liff";
import {
  PaymentApiError,
  resolveCustomerPaymentAttempt,
  type CustomerPaymentResult,
} from "@/lib/payment-api";
import { PAYMENT_METHOD_DETAILS } from "@/lib/payment-methods";
import { clearStoredPaymentAttempt } from "@/lib/payment-return";

type Locale = "th" | "en";
type ResultState =
  | "authenticating"
  | "verifying"
  | "paid"
  | "delayed"
  | "failed"
  | "review"
  | "error"
  | "missing";

const ATTEMPT_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const POLL_DELAYS_MS = [0, 1_500, 2_500, 4_000, 6_500, 10_000] as const;

const COPY = {
  th: {
    eyebrow: "PAYMENT RESULT",
    authenticatingTitle: "กำลังยืนยันบัญชี LINE",
    authenticatingBody: "ระบบกำลังยืนยันตัวตนเพื่อดูผลการชำระเงินอย่างปลอดภัย",
    verifyingTitle: "กำลังตรวจสอบการชำระเงิน",
    verifyingBody: "กำลังรอผลยืนยันจากผู้ให้บริการชำระเงิน กรุณาอย่าชำระซ้ำ",
    paidTitle: "ชำระเงินเรียบร้อย",
    paidBody: "ขอบคุณที่ใช้บริการ SPA 49 ยอดชำระของคุณได้รับการยืนยันแล้ว",
    delayedTitle: "กำลังรอการยืนยัน",
    delayedBody: "ธนาคารอาจรับรายการแล้ว แต่ผลยังส่งกลับมาไม่ครบ กรุณาอย่าชำระซ้ำและตรวจสอบอีกครั้งในอีกสักครู่",
    failedTitle: "ยังไม่สำเร็จการชำระเงิน",
    failedBody: "รายการนี้ไม่ได้รับการยืนยันว่าชำระสำเร็จ คุณสามารถกลับไปเลือกวิธีชำระเงินอีกครั้งได้",
    reviewTitle: "กำลังตรวจสอบรายการ",
    reviewBody: "ผลจากผู้ให้บริการไม่ตรงกับสถานะล่าสุด ระบบพักรายการไว้ให้ Admin ตรวจสอบ กรุณาอย่าชำระซ้ำ",
    errorTitle: "ตรวจสอบผลไม่ได้ในขณะนี้",
    errorBody: "ระบบเชื่อมต่อผลการชำระเงินไม่ได้ชั่วคราว กรุณาลองตรวจสอบอีกครั้ง",
    missingTitle: "ไม่พบรายการชำระเงิน",
    missingBody: "ลิงก์นี้ไม่มีข้อมูลอ้างอิงที่ถูกต้อง กรุณาเปิดรายการจากหน้าการจองของฉัน",
    serviceAmount: "ค่าบริการ",
    tip: "ทิป",
    total: "ยอดชำระทั้งหมด",
    method: "วิธีชำระเงิน",
    booking: "เลขที่การจอง",
    paidAt: "ยืนยันเมื่อ",
    myBookings: "ดูการจองของฉัน",
    recheck: "ตรวจสอบอีกครั้ง",
    close: "ปิด",
    contact: "หากยอดถูกตัดแต่สถานะยังไม่เปลี่ยน โปรดติดต่อ SPA 49",
  },
  en: {
    eyebrow: "PAYMENT RESULT",
    authenticatingTitle: "Verifying your LINE account",
    authenticatingBody: "We are confirming your identity before showing this payment result.",
    verifyingTitle: "Checking your payment",
    verifyingBody: "Waiting for confirmation from the payment provider. Please do not pay again.",
    paidTitle: "Payment completed",
    paidBody: "Thank you for choosing SPA 49. Your payment has been confirmed.",
    delayedTitle: "Confirmation is taking longer",
    delayedBody: "Your bank may have accepted the payment, but confirmation is still pending. Please do not pay again and check shortly.",
    failedTitle: "Payment not completed",
    failedBody: "This payment was not confirmed. You may return to your booking and choose a payment method again.",
    reviewTitle: "Payment under review",
    reviewBody: "The provider result does not match the latest status. An Admin will review it. Please do not pay again.",
    errorTitle: "Unable to check payment",
    errorBody: "The payment result service is temporarily unavailable. Please try again.",
    missingTitle: "Payment not found",
    missingBody: "This link has no valid payment reference. Open the payment from My bookings.",
    serviceAmount: "Service amount",
    tip: "Tip",
    total: "Total paid",
    method: "Payment method",
    booking: "Booking reference",
    paidAt: "Confirmed at",
    myBookings: "View my bookings",
    recheck: "Check again",
    close: "Close",
    contact: "If your account was charged but the status has not changed, contact SPA 49.",
  },
} as const;

function delay(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

function formatMoney(amountSatang: number, locale: Locale) {
  return new Intl.NumberFormat(locale === "th" ? "th-TH" : "en-US", {
    style: "currency",
    currency: "THB",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amountSatang / 100);
}

function formatPaidAt(value: string, locale: Locale) {
  return new Intl.DateTimeFormat(locale === "th" ? "th-TH" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Bangkok",
  }).format(new Date(value));
}

function stateForPayment(result: CustomerPaymentResult): ResultState | null {
  if (result.status === "PAID") return "paid";
  if (result.status === "DUE" || result.status === "UNAVAILABLE") return "failed";
  if (
    result.status === "PAYMENT_REVIEW"
    || result.status === "REFUND_PENDING"
    || result.status === "PARTIALLY_REFUNDED"
    || result.status === "REFUNDED"
    || result.status === "VOIDED"
  ) return "review";
  return null;
}

export function PaymentResult({ attemptId }: { attemptId: string | null }) {
  const router = useRouter();
  const validAttemptId = attemptId && ATTEMPT_ID_PATTERN.test(attemptId) ? attemptId : null;
  const [locale, setLocale] = useState<Locale>("th");
  const [state, setState] = useState<ResultState>(validAttemptId ? "authenticating" : "missing");
  const [lineIdToken, setLineIdToken] = useState<string | null>(null);
  const [result, setResult] = useState<CustomerPaymentResult | null>(null);
  const [canClose, setCanClose] = useState(false);
  const [retryGeneration, setRetryGeneration] = useState(0);
  const copy = COPY[locale];

  useEffect(() => {
    if (!validAttemptId) return;
    let cancelled = false;
    async function authenticate() {
      setState("authenticating");
      try {
        const configResponse = await fetch("/api/config", { cache: "no-store" });
        if (!configResponse.ok) throw new Error("LIFF configuration unavailable");
        const config = await configResponse.json() as { lineLiffId?: string | null };
        if (!config.lineLiffId) throw new Error("LIFF is not configured");
        const liff = await loadLiff();
        await liff.init({ liffId: config.lineLiffId });
        if (!liff.isLoggedIn()) {
          liff.login({ redirectUri: window.location.href });
          return;
        }
        const token = liff.getIDToken();
        if (!token) throw new Error("LINE ID token unavailable");
        if (!cancelled) {
          setCanClose(liff.isInClient() && typeof liff.closeWindow === "function");
          setLineIdToken(token);
          setState("verifying");
        }
      } catch {
        if (!cancelled) setState("error");
      }
    }
    void authenticate();
    return () => { cancelled = true; };
  }, [validAttemptId]);

  useEffect(() => {
    if (!validAttemptId || !lineIdToken) return;
    const currentAttemptId = validAttemptId;
    const currentLineIdToken = lineIdToken;
    const controller = new AbortController();

    async function verify() {
      setState("verifying");
      let receivedPendingStatus = false;
      for (const waitMs of POLL_DELAYS_MS) {
        try {
          await delay(waitMs, controller.signal);
          const payment = await resolveCustomerPaymentAttempt(
            currentAttemptId,
            currentLineIdToken,
            controller.signal,
          );
          setResult(payment);
          const terminalState = stateForPayment(payment);
          if (terminalState) {
            clearStoredPaymentAttempt();
            setState(terminalState);
            return;
          }
          receivedPendingStatus = true;
        } catch (error) {
          if (controller.signal.aborted) return;
          if (error instanceof PaymentApiError && [401, 403, 404].includes(error.status)) {
            setState("error");
            return;
          }
        }
      }
      setState(receivedPendingStatus ? "delayed" : "error");
    }

    void verify();
    return () => controller.abort();
  }, [lineIdToken, retryGeneration, validAttemptId]);

  const stateCopy = useMemo(() => {
    const key = `${state}Title` as keyof typeof copy;
    const bodyKey = `${state}Body` as keyof typeof copy;
    return { title: copy[key], body: copy[bodyKey] };
  }, [copy, state]);

  async function closeLiff() {
    try {
      const liff = await loadLiff();
      liff.closeWindow?.();
    } catch {
      router.push("/my-bookings");
    }
  }

  const showRetry = state === "delayed" || state === "error";
  const isLoading = state === "authenticating" || state === "verifying";
  const method = result ? PAYMENT_METHOD_DETAILS[result.paymentMethod] : null;

  return (
    <main className={`payment-result-shell payment-result-${state}`}>
      <header className="my-bookings-header">
        <Link href="/" className="spa-logo-link" aria-label="SPA 49 booking">
          <Image src="/spa49-logo.png" alt="SPA 49" width={140} height={112} priority />
        </Link>
        <div className="language-switch" aria-label="Language">
          <button type="button" aria-pressed={locale === "th"} onClick={() => setLocale("th")}>TH</button>
          <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
        </div>
      </header>

      <section className="payment-result-content" aria-live="polite" aria-busy={isLoading}>
        <p className="eyebrow">{copy.eyebrow}</p>
        <div className="payment-result-mark" aria-hidden="true">
          {isLoading ? <span className="loading-mark" /> : state === "paid" ? "✓" : state === "failed" ? "×" : "!"}
        </div>
        <h1>{stateCopy.title}</h1>
        <p className="payment-result-lead">{stateCopy.body}</p>

        {result && (
          <dl className="payment-result-details">
            <div>
              <dt>{copy.serviceAmount}</dt>
              <dd>{formatMoney(result.serviceAmountSatang, locale)}</dd>
            </div>
            <div>
              <dt>{copy.tip}</dt>
              <dd>{formatMoney(result.tipAmountSatang, locale)}</dd>
            </div>
            <div className="payment-result-total">
              <dt>{copy.total}</dt>
              <dd>{formatMoney(result.grossAmountSatang, locale)}</dd>
            </div>
            <div>
              <dt>{copy.method}</dt>
              <dd>{method?.[locale] ?? result.paymentMethod}</dd>
            </div>
            <div>
              <dt>{copy.booking}</dt>
              <dd>{result.bookingId}</dd>
            </div>
            {result.paidAt && (
              <div>
                <dt>{copy.paidAt}</dt>
                <dd><time dateTime={result.paidAt}>{formatPaidAt(result.paidAt, locale)}</time></dd>
              </div>
            )}
          </dl>
        )}

        {(state === "delayed" || state === "review") && (
          <p className="payment-result-caution">{copy.contact}</p>
        )}

        <div className="payment-result-actions">
          {showRetry && (
            <button
              type="button"
              className="secondary-button"
              onClick={() => setRetryGeneration((value) => value + 1)}
            >
              {copy.recheck}
            </button>
          )}
          <Link className="primary-button" href="/my-bookings">{copy.myBookings}</Link>
          {canClose && (
            <button type="button" className="payment-result-close" onClick={() => void closeLiff()}>
              {copy.close}
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
