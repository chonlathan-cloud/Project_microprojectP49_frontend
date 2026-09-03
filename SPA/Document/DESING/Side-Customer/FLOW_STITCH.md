# App Flow: Spa 49 Booking & Room Management Application

## 1. Global Navigation & Header
- **Top Bar:** 
  - Left: "Spa 49" Lotus Logo & Branch Title ("Spa 49 - Sukhumvit").
  - Right: View Toggle ("Menu View" vs "Room Matrix View"), Language Switcher (`TH/EN`), and My Bookings Icon with active badge count.
- **Sticky Bottom Cart Bar:** Appears automatically when 1 or more services/add-ons are selected. Displays total duration (e.g., "110 mins"), total item count, total price (e.g., `฿780`), and "Proceed to Book" CTA button.

## 2. Screen 1: Digital Menu & Complete Item Catalog (Landing)
- **Hero Banner:** Spa 49 Logo with tagline "Relax • Renew • Revive" and subtle botanical corner illustrations.
- **Category Navigation Tabs:** `Signature Packages`, `Massage Menu`, and `Add-On Services`.

### Exact Menu Catalog Data (Must be rendered in UI):

#### A. Signature Packages (แพ็กเกจพิเศษ)
1. **Complete Relaxation Ritual (แพ็กเกจผ่อนคลายครบสูตร)**
   - Duration: 105 mins | Price: 590 ฿ | Action: `+ Add`
2. **Couple Relaxation Package (แพ็กเกจผ่อนคลายสำหรับสองท่าน)**
   - Duration: 90 mins | Price: 1,190 ฿ | Action: `+ Add`

#### B. Massage Menu (รายการนวด & สปา)
1. **Reflexology Foot Massage (นวดเท้า)**
   - Duration Options: [60 min - 350 ฿] | [120 min - 650 ฿] | Action: `+ Add`
2. **Traditional Thai Massage (นวดแผนไทย)**
   - Duration Options: [60 min - 300 ฿] | [120 min - 600 ฿] | Action: `+ Add`
3. **Lamenatt Oil Massage (นวดออย / น้ำมัน)**
   - Duration Options: [60 min - 450 ฿] | [120 min - 850 ฿] | Action: `+ Add`
4. **Tendon Relief Massage (นวดแก้อาการ / Tendon)**
   - Duration Options: [60 min - 450 ฿] | [120 min - 900 ฿] | Action: `+ Add`
5. **Aroma Therapy (นวดน้ำมันอโรม่า)**
   - Duration Options: [60 min - 600 ฿] | [120 min - 1,200 ฿] | Action: `+ Add`
6. **Herbal Compress Massage (นวดประคบสมุนไพร)**
   - Duration Options: [60 min - 600 ฿] | [120 min - 1,100 ฿] | Action: `+ Add`
7. **Body Scrub (สครับผิวกาย)**
   - Duration: 60 min | Price: 600 ฿ | Action: `+ Add`
8. **Herbal Steam (อบสมุนไพร 30 นาที)**
   - Duration: 30 min | Price: 300 ฿ / session | Action: `+ Add`

#### C. Add-On Services (บริการเสริม)
1. **Hot Compress - Neck, Shoulder & Back (ประคบร้อน คอ บ่า ไหล่)**
   - Duration: 20 mins | Price: 190 ฿ | Action: `+ Add`

#### D. Menu Footer Notes (หมายเหตุ)
- Advance booking required to reserve queue.
- Prices include 7% VAT.
- Please arrive 10-15 minutes prior to appointment time.
- Please inform staff of any underlying health conditions or pain areas before treatment.

## 3. Screen 2: Multi-Step Booking Wizard (Modal Overlay)
Triggered by clicking "Proceed to Book" from the Floating Cart Bar.

- **Step 1: Review Selected Items & Guest Count (Pax)**
  - Itemized list of selected main massages and add-ons with remove buttons.
  - Total calculated duration and price display.
  - Guest Count Selector: [1 Person] / [2 Persons (Couple)].
- **Step 2: Date & Time Slot Picker**
  - Interactive full-month calendar.
  - Available Time Slot Grid (e.g., 10:00, 11:30, 13:00, 14:30...). Auto-filters slots based on total cart duration.
- **Step 3: Customer Info & Auto Queue Notice**
  - Form Fields: Full Name, Phone Number, Email, Special Requests / Health Conditions.
  - Information Banner: "Therapist and private massage room will be automatically allocated upon arrival."
- **Step 4: Reservation Summary & Confirmation**
  - Itemized summary card, date/time confirmation, VAT notice.
  - Primary CTA Button: "Confirm Spa Reservation".

## 4. Screen 3: Daily Room Schedule Matrix View
Accessible via top bar toggle ("Room Matrix View").

- **Top Bar Controls:** Date Picker ("10 August 2026"), Left/Right Navigation, and Filter by Room Type (Single Room, Couple Room, Foot Area).
- **Schedule Matrix Grid:**
  - **X-Axis (Columns):** Massage Rooms / Beds (e.g., Room 1 [Single], Room 2 [Single], Room 3 [Couple], Foot Area 1).
  - **Y-Axis (Rows):** Time Slots (09:00 to 22:00 in 30-minute increments).
  - **Real-Time Line:** Prominent horizontal red indicator representing current time.
  - **Slot Status Blocks:**
    - `Available`: Clickable slot to directly start a booking for that room.
    - `Occupied`: Forest Green card showing Service Name, Customer Name, Duration ("105 MINS"), and Auto-Assigned Therapist ID.
    - `Cleaning / Buffer`: Soft yellow block representing 15-minute room sanitization interval.
    - `Closed`: Diagonal grey striped block indicating off-hours.

## 5. Screen 4: My Bookings ("การจองของฉัน")
- **Header:** Title "My Spa Bookings" with back navigation arrow.
- **Segmented Control Tabs:** `Upcoming` vs `Completed`.
- **Booking Detail Cards:**
  - Spa 49 Logo, Booking Reference ID (e.g., `#SPA260801`).
  - Date & Time, Selected Treatment Items (Main + Add-ons list).
  - Guest Count, Total Price (`฿590`), Status Badge ("✔ Confirmed / Paid").
  - Action Buttons: "Reschedule", "Cancel Reservation", "View Guidelines".

## 6. Information Modals
- **Spa Policies Modal:** Footer link trigger displaying early arrival advice, VAT details, and health disclosure guidelines.

## 7. LINE Campaign Registration (`welcome-50`)
- Collect full name, phone, day/month of birth, and a required birth year entered as Buddhist Era (`พ.ศ.`); validate the year and convert it to Gregorian before submission.
- Explain why birth year is collected next to the field. Keep the separate marketing consent optional and state that age-group analysis may combine date of birth with service history only when that consent is granted.
- Do not persist a fixed Generation label. Store the canonical Gregorian birth year and derive cohort labels when CRM or Insight rules are executed so boundaries can change without rewriting customer profiles.
