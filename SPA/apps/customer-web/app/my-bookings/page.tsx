import type { Metadata } from "next";

import { MyBookings } from "@/components/my-bookings";

export const metadata: Metadata = {
  title: "การจองของฉัน | SPA 49",
  description: "ดูรายการจอง SPA 49 ที่เชื่อมกับบัญชี LINE ของคุณ"
};

export default function MyBookingsPage() {
  return <MyBookings />;
}
