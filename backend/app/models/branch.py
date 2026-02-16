from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from enum import Enum

from app.models.receipt import BusinessType


# --- Category Models ---
# Reference: BusinessLogic V2.0 (Section 2)

class ExpenseCategory(BaseModel):
    """A single expense category definition."""
    id: str                                  # e.g., "C1", "F1"
    name: str                                # e.g., "COGS (วัตถุดิบ)"
    keywords: List[str] = []                 # Keywords for rule-based matching


# --- Branch Models ---
# Reference: TDD Section 1.1 (branches collection)

class BranchBase(BaseModel):
    """Base fields for a branch."""
    name: str                                # e.g., "Siam Square One"
    type: BusinessType                       # COFFEE or RESTAURANT


class BranchCreate(BranchBase):
    """Schema for creating a new branch."""
    pass


class BranchInDB(BranchBase):
    """Schema representing a branch stored in Firestore."""
    id: str                                  # e.g., "branch_001"
    created_at: datetime


# --- Predefined Category Lists ---
# Reference: BusinessLogic V2.0 (Section 2)

COFFEE_CATEGORIES: List[ExpenseCategory] = [
    ExpenseCategory(
        id="C1", name="COGS (วัตถุดิบ)",
        keywords=["เมล็ดกาแฟ", "นม", "ไซรัป", "ผงชง", "น้ำแข็ง", "เบเกอรี่", "ผลไม้", "Topping"]
    ),
    ExpenseCategory(
        id="C2", name="Labor (ค่าแรง)",
        keywords=["เงินเดือน", "OT"]
    ),
    ExpenseCategory(
        id="C3", name="Rent & Place (สถานที่)",
        keywords=["ค่าเช่า", "ส่วนกลาง", "ที่จอดรถ"]
    ),
    ExpenseCategory(
        id="C4", name="Utilities (สาธารณูปโภค)",
        keywords=["ไฟฟ้า", "ประปา", "เน็ต", "โทรศัพท์", "internet", "wifi"]
    ),
    ExpenseCategory(
        id="C5", name="Equip & Maint (อุปกรณ์)",
        keywords=["ซ่อม", "อะไหล่", "แก้ว", "หลอด", "ทิชชู่"]
    ),
    ExpenseCategory(
        id="C6", name="System & Sales (ระบบ)",
        keywords=["POS", "GP Delivery", "ค่าธรรมเนียม"]
    ),
    ExpenseCategory(
        id="C7", name="Marketing (การตลาด)",
        keywords=["Ads", "Influencer", "ออกแบบ", "ส่วนลด", "โปรโมชั่น"]
    ),
    ExpenseCategory(
        id="C8", name="Admin (ทั่วไป)",
        keywords=["เครื่องเขียน", "ทำความสะอาด", "ภาษี", "บัญชี"]
    ),
    ExpenseCategory(
        id="C9", name="Reserve (สำรองจ่าย)",
        keywords=["ฉุกเฉิน", "ของเสีย", "หมดอายุ", "เงินหาย"]
    ),
]

RESTAURANT_CATEGORIES: List[ExpenseCategory] = [
    ExpenseCategory(
        id="F1", name="Main Ingredients (วัตถุดิบหลัก)",
        keywords=["เนื้อ", "หมู", "ไก่", "ผัก", "ไข่", "ข้าว", "เส้น", "เครื่องปรุง", "กะทิ"]
    ),
    ExpenseCategory(
        id="F2", name="Labor (ค่าแรง)",
        keywords=["เงินเดือน", "OT"]
    ),
    ExpenseCategory(
        id="F3", name="Fuel (เชื้อเพลิง)",
        keywords=["แก๊ส", "ถ่าน"]
    ),
    ExpenseCategory(
        id="F4", name="Containers (ภาชนะ)",
        keywords=["กล่องโฟม", "ถุงแกง", "ช้อนส้อม", "หนังยาง", "ทิชชู่"]
    ),
    ExpenseCategory(
        id="F5", name="Water & Ice (น้ำ)",
        keywords=["น้ำดื่ม", "น้ำแข็ง", "น้ำอัดลม"]
    ),
    ExpenseCategory(
        id="F6", name="Daily Waste (ของเสีย)",
        keywords=["อาหารเหลือ", "เน่า", "ตักเกิน", "หก"]
    ),
    ExpenseCategory(
        id="F7", name="Daily Misc (เบ็ดเตล็ด)",
        keywords=["ค่าเช่ารายวัน", "ที่จอดรถ", "ค่าขยะ", "ทำความสะอาด"]
    ),
]


def get_categories_for_type(business_type: BusinessType) -> List[ExpenseCategory]:
    """Return the category list for a given business type."""
    if business_type == BusinessType.COFFEE:
        return COFFEE_CATEGORIES
    return RESTAURANT_CATEGORIES
