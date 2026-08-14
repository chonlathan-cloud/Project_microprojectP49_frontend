import type { Service } from "./index";

export const INITIAL_SERVICE_CATALOG: Service[] = [
  {
    id: "complete-relaxation",
    category: "SIGNATURE",
    nameTh: "แพ็กเกจผ่อนคลายครบสูตร",
    nameEn: "Complete Relaxation Ritual",
    active: true,
    displayOrder: 10,
    variants: [
      { id: "complete-relaxation-105", durationMinutes: 105, priceSatang: 59000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "couple-relaxation",
    category: "SIGNATURE",
    nameTh: "แพ็กเกจผ่อนคลายสำหรับสองท่าน",
    nameEn: "Couple Relaxation Package",
    active: true,
    displayOrder: 20,
    variants: [
      { id: "couple-relaxation-90", durationMinutes: 90, priceSatang: 119000, pricingMode: "PER_BOOKING", requiredPax: 2 }
    ]
  },
  {
    id: "foot-reflexology",
    category: "MASSAGE",
    nameTh: "นวดเท้า",
    nameEn: "Reflexology Foot Massage",
    active: true,
    displayOrder: 30,
    variants: [
      { id: "foot-reflexology-60", durationMinutes: 60, priceSatang: 35000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 },
      { id: "foot-reflexology-120", durationMinutes: 120, priceSatang: 65000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "traditional-thai",
    category: "MASSAGE",
    nameTh: "นวดแผนไทย",
    nameEn: "Traditional Thai Massage",
    active: true,
    displayOrder: 40,
    variants: [
      { id: "traditional-thai-60", durationMinutes: 60, priceSatang: 30000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 },
      { id: "traditional-thai-120", durationMinutes: 120, priceSatang: 60000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "lamenatt-oil",
    category: "MASSAGE",
    nameTh: "นวดออย / น้ำมัน",
    nameEn: "Lamenatt Oil Massage",
    active: true,
    displayOrder: 50,
    variants: [
      { id: "lamenatt-oil-60", durationMinutes: 60, priceSatang: 45000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 },
      { id: "lamenatt-oil-120", durationMinutes: 120, priceSatang: 85000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "tendon-relief",
    category: "MASSAGE",
    nameTh: "นวดแก้อาการ",
    nameEn: "Tendon Relief Massage",
    active: true,
    displayOrder: 60,
    variants: [
      { id: "tendon-relief-60", durationMinutes: 60, priceSatang: 45000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 },
      { id: "tendon-relief-120", durationMinutes: 120, priceSatang: 90000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "aroma-therapy",
    category: "MASSAGE",
    nameTh: "นวดน้ำมันอโรม่า",
    nameEn: "Aroma Therapy",
    active: true,
    displayOrder: 70,
    variants: [
      { id: "aroma-therapy-60", durationMinutes: 60, priceSatang: 60000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 },
      { id: "aroma-therapy-120", durationMinutes: 120, priceSatang: 120000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "herbal-compress",
    category: "MASSAGE",
    nameTh: "นวดประคบสมุนไพร",
    nameEn: "Herbal Compress Massage",
    active: true,
    displayOrder: 80,
    variants: [
      { id: "herbal-compress-60", durationMinutes: 60, priceSatang: 60000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 },
      { id: "herbal-compress-120", durationMinutes: 120, priceSatang: 110000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "body-scrub",
    category: "MASSAGE",
    nameTh: "สครับผิวกาย",
    nameEn: "Body Scrub",
    active: true,
    displayOrder: 90,
    variants: [
      { id: "body-scrub-60", durationMinutes: 60, priceSatang: 60000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "herbal-steam",
    category: "MASSAGE",
    nameTh: "อบสมุนไพร",
    nameEn: "Herbal Steam",
    active: true,
    displayOrder: 100,
    variants: [
      { id: "herbal-steam-30", durationMinutes: 30, priceSatang: 30000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  },
  {
    id: "hot-compress-neck-shoulder-back",
    category: "STANDALONE",
    nameTh: "ประคบร้อน คอ บ่า ไหล่",
    nameEn: "Hot Compress — Neck, Shoulder & Back",
    active: true,
    displayOrder: 110,
    variants: [
      { id: "hot-compress-neck-shoulder-back-20", durationMinutes: 20, priceSatang: 19000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  }
];
