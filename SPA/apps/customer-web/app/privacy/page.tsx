import Link from "next/link";

export default function PrivacyPage() {
  return <main className="status-page"><article className="status-card legal-card">
    <p className="eyebrow">DRAFT • PRIVACY NOTICE v2</p>
    <h1>นโยบายความเป็นส่วนตัว / Privacy Notice</h1>
    <p>SPA49 ใช้ชื่อเล่น เบอร์โทร ข้อมูลการจอง และข้อมูลสุขภาพเพื่อจัดการการจองและให้บริการอย่างปลอดภัย รายละเอียดสุขภาพอาจแสดงใน Registered Admin LINE Group ซึ่งจำกัดสมาชิกเฉพาะผู้ปฏิบัติงานที่ได้รับอนุญาตและมีหน้าที่รักษาความลับ เพื่อให้ร้านเตรียมบริการและยืนยันการจองได้</p>
    <p>ข้อมูลสุขภาพเก็บเป็นเวลา 3 ปีนับจากการรับบริการหรือการปรับปรุงข้อมูลสุขภาพครั้งล่าสุด จากนั้นระบบจะลบหรือทำให้ไม่สามารถระบุตัวตนได้ตามกระบวนการของร้าน</p>
    <p>SPA49 uses nickname, phone, booking information, and health information to manage appointments and provide services safely. Health details may appear in the registered Admin LINE Group, whose membership is restricted to authorized operators bound by confidentiality obligations, so the spa can prepare and confirm the service. Health information is retained for three years after the latest service or health update.</p>
    <p>หากต้องการถอนความยินยอมหรือขอลบข้อมูล กรุณาติดต่อ Admin ที่ 064-365-4949 การถอนความยินยอมไม่กระทบการใช้ข้อมูลที่ชอบด้วยกฎหมายก่อนการถอน</p>
    <p><strong>เอกสารนี้เป็นฉบับร่างและต้องได้รับการตรวจสอบทางกฎหมายก่อนเปิด Production สำหรับลูกค้าจริง</strong></p>
    <Link href="/">กลับหน้าจอง / Back</Link>
  </article></main>;
}
