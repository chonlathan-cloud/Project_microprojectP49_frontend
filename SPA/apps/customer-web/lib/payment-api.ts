export type PaymentStatus =
  | "UNAVAILABLE"
  | "DUE"
  | "PAYMENT_PENDING"
  | "PAYMENT_REVIEW"
  | "PAID"
  | "REFUND_PENDING"
  | "PARTIALLY_REFUNDED"
  | "REFUNDED";

export type BeamPaymentMethod =
  | "KPLUS"
  | "SCB_EASY"
  | "KRUNGSRI_APP"
  | "BANGKOK_BANK_APP"
  | "QR_PROMPT_PAY";

export type BeamDeviceType = "IOS" | "ANDROID" | "WEB";

export type PaymentOptions = {
  bookingId: string;
  paymentId: string;
  status: PaymentStatus;
  source: "BEAM" | "CASH" | null;
  serviceAmountSatang: number;
  currency: "THB";
  eligible: boolean;
  reason: string | null;
  tipPresetsSatang: number[];
  customTipMaxSatang: number | null;
  methods: BeamPaymentMethod[];
  version: number;
};

export type PaymentAttempt = {
  attemptId: string;
  paymentId: string;
  status: string;
  paymentMethod: BeamPaymentMethod;
  actionRequired: "NONE" | "REDIRECT" | "ENCODED_IMAGE";
  expiresAt: string | null;
  statusToken: string;
  imageBase64: string | null;
  redirectUrl: string | null;
};

export type ResolvedPayment = {
  paymentId: string;
  bookingId: string;
  status: PaymentStatus;
  source: "BEAM" | "CASH" | null;
  serviceAmountSatang: number;
  tipAmountSatang: number;
  grossAmountSatang: number;
  paidAt: string | null;
};

export type CustomerPaymentResult = ResolvedPayment & {
  attemptId: string;
  paymentMethod: BeamPaymentMethod;
};

export class PaymentApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) {
    super(code);
  }
}

async function post<T>(
  path: string,
  body: object,
  options: { idempotencyKey?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
  const response = await fetch(`/api/spa${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
    signal: options.signal,
  });
  const payload = await response.json().catch(() => null) as Record<string, unknown> | null;
  if (!response.ok) {
    throw new PaymentApiError(
      String(payload?.code ?? payload?.detail ?? "PAYMENT_UNAVAILABLE"),
      response.status,
    );
  }
  return payload as T;
}

export function getPaymentOptions(
  bookingId: string,
  lineIdToken: string,
  deviceType: BeamDeviceType,
  signal?: AbortSignal,
) {
  return post<PaymentOptions>(
    `/api/v1/public/bookings/${encodeURIComponent(bookingId)}/payment-options`,
    { lineIdToken, deviceType },
    { signal },
  );
}

export function createPaymentAttempt(
  bookingId: string,
  lineIdToken: string,
  tipAmountSatang: number,
  paymentMethod: BeamPaymentMethod,
  deviceType: BeamDeviceType,
  idempotencyKey: string,
) {
  return post<PaymentAttempt>(
    `/api/v1/public/bookings/${encodeURIComponent(bookingId)}/payment-attempts`,
    { lineIdToken, tipAmountSatang, paymentMethod, deviceType },
    { idempotencyKey },
  );
}

export function detectBeamDeviceType(): BeamDeviceType {
  const userAgent = navigator.userAgent;
  const isIPadOS = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  if (/iPhone|iPad|iPod/i.test(userAgent) || isIPadOS) return "IOS";
  if (/Android/i.test(userAgent)) return "ANDROID";
  return "WEB";
}

export function resolvePaymentStatus(statusToken: string, signal?: AbortSignal) {
  return post<ResolvedPayment>(
    "/api/v1/public/payment-status:resolve",
    { statusToken },
    { signal },
  );
}

export function resolveCustomerPaymentAttempt(
  attemptId: string,
  lineIdToken: string,
  signal?: AbortSignal,
) {
  return post<CustomerPaymentResult>(
    `/api/v1/public/payment-attempts/${encodeURIComponent(attemptId)}:resolve`,
    { lineIdToken },
    { signal },
  );
}
