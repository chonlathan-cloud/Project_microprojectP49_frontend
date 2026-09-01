import type { BeamPaymentMethod } from "@/lib/payment-api";

export const PAYMENT_METHOD_DETAILS: Record<BeamPaymentMethod, {
  th: string;
  en: string;
  thHint: string;
  enHint: string;
  logoSrc: string | null;
}> = {
  KPLUS: { th: "K PLUS", en: "K PLUS", thHint: "ธนาคารกสิกรไทย", enHint: "Kasikornbank", logoSrc: "/images/payment-methods/kplus.jpg" },
  SCB_EASY: { th: "SCB EASY", en: "SCB EASY", thHint: "ธนาคารไทยพาณิชย์", enHint: "Siam Commercial Bank", logoSrc: "/images/payment-methods/scb-easy.jpg" },
  KRUNGSRI_APP: { th: "Krungsri App", en: "Krungsri App", thHint: "ธนาคารกรุงศรีอยุธยา", enHint: "Bank of Ayudhya", logoSrc: "/images/payment-methods/krungsri.jpg" },
  BANGKOK_BANK_APP: { th: "Bangkok Bank", en: "Bangkok Bank", thHint: "โมบายแบงก์กิ้ง จากธนาคารกรุงเทพ", enHint: "Bangkok Bank Mobile Banking", logoSrc: "/images/payment-methods/bangkok-bank.jpg" },
  QR_PROMPT_PAY: { th: "PromptPay QR", en: "PromptPay QR", thHint: "สแกนด้วยแอปธนาคาร", enHint: "Scan with any supported banking app", logoSrc: null }
};
