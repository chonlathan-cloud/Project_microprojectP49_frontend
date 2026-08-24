import type { Metadata } from "next";

import { CampaignRegistration } from "@/components/campaign-registration";

export const metadata: Metadata = {
  title: "รับส่วนลด 50 บาท | SPA 49",
  description: "ลงทะเบียนผ่าน LINE เพื่อรับคูปองส่วนลด SPA 49"
};

export default async function CampaignPage({
  params
}: {
  params: Promise<{ campaignCode: string }>;
}) {
  const { campaignCode } = await params;
  return <CampaignRegistration campaignCode={campaignCode} />;
}
