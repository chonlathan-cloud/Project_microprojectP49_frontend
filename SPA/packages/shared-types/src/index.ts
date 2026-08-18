export type Locale = "th" | "en";

export type BookingStatus =
  | "PENDING"
  | "CONFIRMED"
  | "IN_SERVICE"
  | "COMPLETED"
  | "CANCELLED"
  | "NO_SHOW";

export type PricingMode = "PER_PARTICIPANT" | "PER_BOOKING";

export type ServiceVariant = {
  id: string;
  durationMinutes: number;
  priceSatang: number;
  pricingMode: PricingMode;
  requiredPax: 1 | 2;
};

export type Service = {
  id: string;
  category: "SIGNATURE" | "MASSAGE" | "STANDALONE";
  nameTh: string;
  nameEn: string;
  descriptionTh: string;
  descriptionEn: string;
  active: boolean;
  displayOrder: number;
  imageVersion?: string | null;
  variants: ServiceVariant[];
};

export type BookingDraft = {
  branchId: string;
  participants: Array<{
    nickname: string;
    serviceVariantId: string;
    health: { hasInformation: boolean; details?: string };
    healthConsent: { accepted: boolean; version: string };
  }>;
  startLocal?: string;
  phone?: string;
  bookingPrivacyAcknowledgement?: {
    accepted: boolean;
    version: string;
  };
  secondParticipantAuthorization?: {
    accepted: boolean;
    version: string;
  };
};

export type PreviewBooking = {
  bookingId: string;
  startLocal: string;
  customerName: string;
  customerPhoneMasked: string;
  serviceName: string;
  durationMinutes: number;
  pax: number;
  status: BookingStatus;
  healthAlert: boolean;
  therapistName?: string;
  version: number;
};

export { INITIAL_SERVICE_CATALOG } from "./catalog";
