import Link from "next/link";

export default function PrivacyPage() {
  return <main className="status-page"><article className="status-card legal-card">
    <p className="eyebrow">DRAFT • PRIVACY NOTICE v1</p>
    <h1>นโยบายความเป็นส่วนตัว / Privacy Notice</h1>
    <p>SPA49 ใช้ชื่อเล่น เบอร์โทร ข้อมูลการจอง และข้อมูลสุขภาพเพื่อจัดการการจองและให้บริการอย่างปลอดภัย โดยจำกัดการเข้าถึงข้อมูลสุขภาพเฉพาะผู้ดูแลที่ได้รับสิทธิ์</p>
    <p>ข้อมูลสุขภาพเก็บเป็นเวลา 3 ปีนับจากการรับบริการหรือการปรับปรุงข้อมูลสุขภาพครั้งล่าสุด จากนั้นระบบจะลบหรือทำให้ไม่สามารถระบุตัวตนได้ตามกระบวนการของร้าน</p>
    <p>SPA49 uses nickname, phone, booking information, and health information to manage appointments and provide services safely. Health information is restricted to authorized operational users and retained for three years after the latest service or health update.</p>
    <p>หากต้องการถอนความยินยอมหรือขอลบข้อมูล กรุณาติดต่อ Admin ที่ 064-365-4949 การถอนความยินยอมไม่กระทบการใช้ข้อมูลที่ชอบด้วยกฎหมายก่อนการถอน</p>
    <p><strong>เอกสารนี้เป็นฉบับร่างและต้องได้รับการตรวจสอบทางกฎหมายก่อนเปิด Production สำหรับลูกค้าจริง</strong></p>
    <Link href="/">กลับหน้าจอง / Back</Link>
  </article></main>;
}
