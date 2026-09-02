import type { Metadata } from "next";

import { MyBookings } from "@/components/my-bookings";

// LIFF WebViews can retain a statically generated HTML shell across Cloud Run
// revisions. Render this authenticated entry point per request so it always
// references the assets from the currently serving revision.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "การจองของฉัน | SPA 49",
  description: "ดูรายการจอง SPA 49 ที่เชื่อมกับบัญชี LINE ของคุณ"
};

export default function MyBookingsPage() {
  return <MyBookings />;
}
