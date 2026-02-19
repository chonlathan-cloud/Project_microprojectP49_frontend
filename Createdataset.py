import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

# ตั้งค่าจำนวนแถว
NUM_ROWS = 100

# ฟังก์ชันสุ่มวันที่ในเดือนปัจจุบัน
def random_date(start_date, end_date):
    delta = end_date - start_date
    int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
    random_second = random.randrange(int_delta)
    return start_date + timedelta(seconds=random_second)

start = datetime(2023, 10, 1)
end = datetime(2023, 10, 31)

# ==========================================
# 1. สร้างไฟล์ CSV แบบมาตรฐาน (Standard)
# ==========================================
data_std = {
    "date": [random_date(start, end).strftime("%Y-%m-%d %H:%M:%S") for _ in range(NUM_ROWS)],
    "receipt_no": [f"REC-{1000+i}" for i in range(NUM_ROWS)], # Column เกิน (Noise)
    "amount": [round(random.uniform(50, 3000), 2) for _ in range(NUM_ROWS)],
    "payment_method": [random.choice(["CASH", "TRANSFER", "CREDIT_CARD", "QR"]) for _ in range(NUM_ROWS)],
    "cashier": [random.choice(["Staff A", "Staff B", "Manager"]) for _ in range(NUM_ROWS)], # Column เกิน
    "status": ["Completed"] * NUM_ROWS # Column เกิน
}
df_std = pd.DataFrame(data_std)
df_std.to_csv("pos_large_test.csv", index=False)
print(f"✅ Created 'pos_large_test.csv' with {NUM_ROWS} rows.")

# ==========================================
# 2. สร้างไฟล์ Excel แบบซับซ้อน (Complex / Real-world)
# ==========================================
# จำลองไฟล์จากเครื่อง POS จริงที่มี Column เยอะๆ และชื่อไทย
data_complex = {
    "ลำดับ": range(1, NUM_ROWS + 1),
    "วันที่ขาย": [random_date(start, end) for _ in range(NUM_ROWS)], # Target: date
    "เลขที่ใบเสร็จ": [f"INV-2023-{1000+i}" for i in range(NUM_ROWS)],
    "โต๊ะ": [random.choice(["T1", "T2", "A1", "Takeaway", "-"]) for _ in range(NUM_ROWS)],
    "ลูกค้า": [random.choice(["General", "Member", "VIP"]) for _ in range(NUM_ROWS)],
    "ประเภทการขาย": ["Dine-in"] * NUM_ROWS,
    "จำนวนสินค้า": [random.randint(1, 10) for _ in range(NUM_ROWS)],
    "ราคาเต็ม (Gross)": [round(random.uniform(100, 5000), 2) for _ in range(NUM_ROWS)],
    "ส่วนลด (Discount)": [round(random.uniform(0, 100), 2) for _ in range(NUM_ROWS)],
    "Vat 7%": [round(random.uniform(5, 200), 2) for _ in range(NUM_ROWS)],
    "Service Charge 10%": [round(random.uniform(10, 300), 2) for _ in range(NUM_ROWS)],
    "ยอดขายสุทธิ (Net Sales)": [], # Target: amount (จะคำนวณข้างล่าง)
    "ช่องทางชำระ (Payment Type)": [random.choice(["เงินสด", "Cash", "โอนเงิน", "KPlus", "SCB", "Credit Card", "ShopeePay"]) for _ in range(NUM_ROWS)], # Target: payment_method
    "พนักงานขาย": [random.choice(["สมชาย", "สมหญิง", "Admin"]) for _ in range(NUM_ROWS)],
    "สาขา": ["Branch 001"] * NUM_ROWS,
    "หมายเหตุ": ["-"] * NUM_ROWS,
    "สถานะ": ["Paid"] * NUM_ROWS,
    "Void By": ["-"] * NUM_ROWS,
    "Shift ID": [random.randint(1, 3) for _ in range(NUM_ROWS)],
    "Terminal ID": ["POS-01"] * NUM_ROWS
}

# คำนวณยอดสุทธิให้สมจริง
for i in range(NUM_ROWS):
    net = data_complex["ราคาเต็ม (Gross)"][i] - data_complex["ส่วนลด (Discount)"][i]
    data_complex["ยอดขายสุทธิ (Net Sales)"].append(round(net, 2))

df_complex = pd.DataFrame(data_complex)
df_complex.to_excel("pos_complex_test.xlsx", index=False)
print(f"✅ Created 'pos_complex_test.xlsx' with {NUM_ROWS} rows and {len(df_complex.columns)} columns.")