import type { PaymentAttempt } from "@/lib/payment-api";

const PAYMENT_ATTEMPT_STORAGE_KEY = "spa49.payment.redirect.v1";

export type StoredPaymentAttempt = {
  bookingId: string;
  attempt: PaymentAttempt;
};

export function readStoredPaymentAttempt(): StoredPaymentAttempt | null {
  try {
    const raw = window.sessionStorage.getItem(PAYMENT_ATTEMPT_STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as StoredPaymentAttempt;
    if (!value?.bookingId || !value.attempt?.attemptId || !value.attempt.statusToken) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

export function storePaymentAttempt(value: StoredPaymentAttempt) {
  window.sessionStorage.setItem(PAYMENT_ATTEMPT_STORAGE_KEY, JSON.stringify(value));
}

export function clearStoredPaymentAttempt() {
  window.sessionStorage.removeItem(PAYMENT_ATTEMPT_STORAGE_KEY);
}
