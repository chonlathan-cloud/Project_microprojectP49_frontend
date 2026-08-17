import Link from "next/link";

export default function TermsPage() {
  return <main className="status-page"><article className="status-card legal-card">
    <p className="eyebrow">DRAFT • BOOKING TERMS v1</p>
    <h1>เงื่อนไขการจอง / Booking Terms</h1>
    <p>คำขอจองมีสถานะรอยืนยันจนกว่า SPA49 จะยืนยัน ลูกค้าชำระเงินที่ร้าน และราคาที่แสดงรวม VAT แล้ว</p>
    <p>ต้องการยกเลิกหรือแก้ไขการจอง กรุณาติดต่อร้านล่วงหน้าอย่างน้อย 24 ชั่วโมง หากเหลือน้อยกว่า 24 ชั่วโมงให้โทร 064-365-4949</p>
    <p>หากลูกค้าไม่มาภายใน 15 นาทีหลังเวลานัด Admin อาจบันทึกสถานะเป็น No-show การเปลี่ยนแปลงวันเปิดบริการหรือวันหยุดพิเศษจะแจ้งผ่าน Facebook Page ของร้าน</p>
    <p>A request remains pending until confirmed by SPA49. Payment is collected at the store. Displayed prices include VAT. Contact the store at least 24 hours before cancellation or amendment. A booking may be marked no-show 15 minutes after its start time.</p>
    <p><strong>เอกสารนี้เป็นฉบับร่างและต้องได้รับการตรวจสอบทางกฎหมายก่อนเปิด Production สำหรับลูกค้าจริง</strong></p>
    <Link href="/">กลับหน้าจอง / Back</Link>
  </article></main>;
}
