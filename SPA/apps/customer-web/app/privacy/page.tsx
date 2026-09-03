import Link from "next/link";

export default function PrivacyPage() {
  return <main className="status-page"><article className="status-card legal-card">
    <p className="eyebrow">DRAFT • PRIVACY NOTICE v3</p>
    <h1>นโยบายความเป็นส่วนตัว / Privacy Notice</h1>
    <p>SPA49 ใช้ชื่อเล่น เบอร์โทร ข้อมูลการจอง และข้อมูลสุขภาพเพื่อจัดการการจองและให้บริการอย่างปลอดภัย รายละเอียดสุขภาพอาจแสดงใน Registered Admin LINE Group ซึ่งจำกัดสมาชิกเฉพาะผู้ปฏิบัติงานที่ได้รับอนุญาตและมีหน้าที่รักษาความลับ เพื่อให้ร้านเตรียมบริการและยืนยันการจองได้</p>
    <p>สำหรับแคมเปญ LINE ร้านเก็บวันเดือนปีเกิด โดยรับปีเกิดเป็น พ.ศ. และจัดเก็บเป็นปี ค.ศ. เพื่อความถูกต้องของข้อมูล หากลูกค้ายินยอมด้านการตลาด ร้านอาจใช้วันเดือนปีเกิดร่วมกับประวัติการใช้บริการเพื่อวิเคราะห์ช่วงวัย ออกแบบสิทธิประโยชน์ และสื่อสารการตลาด ลูกค้ายังรับคูปองได้แม้ไม่ให้ความยินยอมด้านการตลาด</p>
    <p>ข้อมูลสุขภาพเก็บเป็นเวลา 3 ปีนับจากการรับบริการหรือการปรับปรุงข้อมูลสุขภาพครั้งล่าสุด จากนั้นระบบจะลบหรือทำให้ไม่สามารถระบุตัวตนได้ตามกระบวนการของร้าน</p>
    <p>SPA49 uses nickname, phone, booking information, and health information to manage appointments and provide services safely. Health details may appear in the registered Admin LINE Group, whose membership is restricted to authorized operators bound by confidentiality obligations, so the spa can prepare and confirm the service. Health information is retained for three years after the latest service or health update.</p>
    <p>For LINE campaigns, SPA49 collects the full date of birth. The customer enters the year in Buddhist Era format and the system stores the Gregorian year. With optional marketing consent, SPA49 may combine date of birth with service history for age-group analysis, benefit design, and marketing communications. Declining marketing consent does not prevent coupon issuance.</p>
    <p>หากต้องการถอนความยินยอมหรือขอลบข้อมูล กรุณาติดต่อ Admin ที่ 064-365-4949 การถอนความยินยอมไม่กระทบการใช้ข้อมูลที่ชอบด้วยกฎหมายก่อนการถอน</p>
    <p><strong>เอกสารนี้เป็นฉบับร่างและต้องได้รับการตรวจสอบทางกฎหมายก่อนเปิด Production สำหรับลูกค้าจริง</strong></p>
    <Link href="/">กลับหน้าจอง / Back</Link>
  </article></main>;
}
