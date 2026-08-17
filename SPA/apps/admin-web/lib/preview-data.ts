import type { PreviewBooking } from "@spa/shared-types";

export const PREVIEW_BOOKINGS: PreviewBooking[] = [
  {
    bookingId: "BK-20260815-001",
    startLocal: "2026-08-15T10:00:00+07:00",
    customerName: "คุณมุก",
    customerPhoneMasked: "081-***-5678",
    serviceName: "นวดแผนไทย • 60 นาที",
    durationMinutes: 60,
    pax: 1,
    status: "PENDING",
    healthAlert: true,
    version: 1
  },
  {
    bookingId: "BK-20260815-002",
    startLocal: "2026-08-15T11:30:00+07:00",
    customerName: "คุณแอน",
    customerPhoneMasked: "089-***-2041",
    serviceName: "Couple Relaxation Package • 90 นาที",
    durationMinutes: 90,
    pax: 2,
    status: "CONFIRMED",
    healthAlert: false,
    version: 1
  },
  {
    bookingId: "BK-20260815-003",
    startLocal: "2026-08-15T13:00:00+07:00",
    customerName: "คุณนิชา",
    customerPhoneMasked: "086-***-7190",
    serviceName: "Aroma Therapy • 120 นาที",
    durationMinutes: 120,
    pax: 1,
    status: "CONFIRMED",
    healthAlert: false,
    version: 1,
    therapistName: "พี่น้อย"
  },
  {
    bookingId: "BK-20260815-004",
    startLocal: "2026-08-15T14:30:00+07:00",
    customerName: "คุณบี",
    customerPhoneMasked: "095-***-8812",
    serviceName: "นวดเท้า • 60 นาที",
    durationMinutes: 60,
    pax: 1,
    status: "IN_SERVICE",
    healthAlert: false,
    version: 1,
    therapistName: "พี่ฝน"
  }
];
