import Link from "next/link";
import { BarChart3, FileUp, Sparkles, WalletCards } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardWelcomePage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Welcome to The 49 Smart P&amp;L</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-slate-600">
            หน้านี้คือจุดเริ่มต้นการใช้งานระบบ โดยมีงานหลัก 3 อย่าง:
            <span className="font-medium text-slate-800"> อัปโหลดใบเสร็จค่าใช้จ่าย</span>,
            <span className="font-medium text-slate-800"> นำเข้ารายได้จาก POS</span> และ
            <span className="font-medium text-slate-800"> ดูผลกำไรขาดทุน (P&amp;L)</span>.
          </p>
          <p className="text-sm text-slate-600">
            ถ้าเพิ่งเริ่มใช้งาน แนะนำให้ทำตามลำดับ
            <span className="font-medium text-slate-800"> 1 → 2 → 3</span> ด้านล่าง
            เพื่อให้ข้อมูลครบและ dashboard แม่นยำ
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href="/dashboard/upload-receipt">
              <Button type="button">
                <FileUp className="mr-2 h-4 w-4" />
                ไปหน้าอัปโหลดใบเสร็จ
              </Button>
            </Link>
            <Link href="/dashboard/pos-import">
              <Button type="button" variant="outline">
                <WalletCards className="mr-2 h-4 w-4" />
                ไปหน้า Import POS
              </Button>
            </Link>
            <Link href="/dashboard">
              <Button type="button" variant="outline">
                <BarChart3 className="mr-2 h-4 w-4" />
                ไปหน้า Dashboard
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="space-y-2 p-5">
            <FileUp className="h-5 w-5 text-slate-700" />
            <h2 className="text-base font-semibold text-slate-900">1) Upload Receipt (อัปโหลดใบเสร็จ)</h2>
            <p className="text-sm text-slate-600">
              ใช้เมื่อมีบิลค่าใช้จ่ายจากร้าน เช่น วัตถุดิบ ของใช้ หรือบริการต่างๆ
            </p>
            <p className="text-sm text-slate-600">
              ผลลัพธ์ที่ควรได้: ระบบจะสร้างรายการแบบ Draft ให้ตรวจ แก้ไขหมวดหมู่ และกด
              Verify &amp; Save
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 p-5">
            <WalletCards className="h-5 w-5 text-slate-700" />
            <h2 className="text-base font-semibold text-slate-900">2) Import POS Revenue (นำเข้ารายได้)</h2>
            <p className="text-sm text-slate-600">
              อัปโหลดไฟล์ขายจาก POS (CSV/XLSX) เพื่อส่งข้อมูลรายได้เข้า BigQuery
            </p>
            <p className="text-sm text-slate-600">
              ผลลัพธ์ที่ควรได้: ขึ้นข้อความ Success พร้อมจำนวนรายการที่นำเข้า (rows inserted)
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 p-5">
            <Sparkles className="h-5 w-5 text-slate-700" />
            <h2 className="text-base font-semibold text-slate-900">3) Analyze &amp; Act (วิเคราะห์และตัดสินใจ)</h2>
            <p className="text-sm text-slate-600">
              ดู KPI สำคัญ เช่น Revenue, Expense, Net Profit และกราฟสัดส่วนค่าใช้จ่าย
            </p>
            <p className="text-sm text-slate-600">
              ผลลัพธ์ที่ควรได้: เห็นภาพรวมผลประกอบการรายสาขา และถาม AI Insight เพื่อรับคำแนะนำ
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
