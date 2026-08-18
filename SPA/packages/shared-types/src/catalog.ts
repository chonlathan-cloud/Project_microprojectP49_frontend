import type { Service } from "./index";

export const INITIAL_SERVICE_CATALOG: Service[] = [
  {
    id: "complete-relaxation",
    category: "SIGNATURE",
    nameTh: "แพ็กเกจผ่อนคลายครบสูตร",
    nameEn: "Complete Relaxation Ritual",
    descriptionTh: "โปรแกรมผ่อนคลายแบบครบขั้นตอนในคอร์สเดียว เหมาะกับวันที่อยากพักและดูแลร่างกายอย่างเต็มที่",
    descriptionEn: "A complete relaxation ritual in one session, ideal when you want unhurried, full-body care.",
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
    descriptionTh: "ช่วงเวลาพักผ่อนสำหรับสองท่าน ให้คุณได้ผ่อนคลายพร้อมกันในนัดหมายเดียว",
    descriptionEn: "A shared relaxation session for two guests who want to unwind together.",
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
    descriptionTh: "เน้นฝ่าเท้าและช่วงขา เหมาะกับผู้ที่เมื่อยล้าจากการยืน เดิน หรือใช้งานขามาทั้งวัน",
    descriptionEn: "Focused care for tired feet and lower legs after long periods of standing or walking.",
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
    descriptionTh: "ผสานการกดและยืดเหยียดตามแบบแผนไทย เหมาะกับผู้ที่ชอบแรงสัมผัสชัดเจน",
    descriptionEn: "Traditional pressure and assisted stretching for guests who prefer a firmer treatment.",
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
    descriptionTh: "นวดด้วยน้ำมันในจังหวะลื่นไหลและนุ่มนวล เหมาะกับการพักผ่อนแบบสบายตัว",
    descriptionEn: "Smooth, flowing oil massage for a gentle and deeply comfortable way to unwind.",
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
    descriptionTh: "เน้นดูแลบริเวณที่ตึงเมื่อยเป็นพิเศษ พร้อมปรับน้ำหนักตามความเหมาะสมของแต่ละท่าน",
    descriptionEn: "Focused attention for areas of tension, with pressure adjusted to your comfort.",
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
    descriptionTh: "นวดน้ำมันพร้อมกลิ่นอโรม่า ช่วยสร้างบรรยากาศสงบสำหรับการพักกายและใจ",
    descriptionEn: "Aromatic oil massage designed to create a calm setting for body and mind.",
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
    descriptionTh: "ผสานการนวดกับลูกประคบสมุนไพรอุ่น เหมาะกับผู้ที่ชอบความอบอุ่นและการคลายความตึง",
    descriptionEn: "Massage paired with a warm herbal compress for guests who enjoy soothing heat.",
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
    descriptionTh: "ดูแลผิวกายด้วยการสครับอย่างอ่อนโยน เพื่อสัมผัสผิวที่เรียบเนียนและสดชื่น",
    descriptionEn: "A gentle body exfoliation treatment that leaves the skin feeling smooth and refreshed.",
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
    descriptionTh: "อบไอน้ำสมุนไพรอุ่น ๆ ให้ร่างกายได้พักและผ่อนคลายในช่วงเวลาสั้น ๆ",
    descriptionEn: "A short warm herbal steam session for a quiet, comforting pause.",
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
    descriptionTh: "ประคบร้อนเฉพาะจุดบริเวณคอ บ่า ไหล่ และหลัง เหมาะกับความล้าจากการนั่งหรือใช้งานนาน",
    descriptionEn: "Targeted warmth for the neck, shoulders, and back after long periods of sitting or activity.",
    active: true,
    displayOrder: 110,
    variants: [
      { id: "hot-compress-neck-shoulder-back-20", durationMinutes: 20, priceSatang: 19000, pricingMode: "PER_PARTICIPANT", requiredPax: 1 }
    ]
  }
];
