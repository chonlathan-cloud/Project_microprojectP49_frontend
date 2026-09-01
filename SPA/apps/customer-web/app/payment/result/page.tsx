import type { Metadata } from "next";

import { PaymentResult } from "@/components/payment-result";

export const metadata: Metadata = {
  title: "ผลการชำระเงิน | SPA 49",
  description: "ตรวจสอบผลการชำระเงินสำหรับการจอง SPA 49",
};

type PaymentResultPageProps = {
  searchParams: Promise<{ attempt?: string | string[] }>;
};

export default async function PaymentResultPage({ searchParams }: PaymentResultPageProps) {
  const params = await searchParams;
  const attemptId = typeof params.attempt === "string" ? params.attempt : null;

  return <PaymentResult attemptId={attemptId} />;
}
