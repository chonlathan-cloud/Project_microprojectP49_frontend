# App Flow: Spa 49 Admin Desktop Web Application

## 1. Global Navigation Architecture
- **Desktop Collapsible Left Sidebar:** Persistent menu for switching screens.
- **Desktop Top Control Header:** 
  - Left: Active Page Title & Branch Selector ("Sukhumvit Branch").
  - Center: Global Search Bar (Quick search by Customer Name, Phone, or Booking ID).
  - Right: Quick Notification Bell (Real-time online booking alerts) & Staff Profile ("Khun Pha - Manager").

---

## 2. Screen 1: Booking Calendar & List View (Main Screen)
- **Top Control Bar:**
  - Date Filter Bar: Interactive Date Picker with quick buttons (`Today`, `Tomorrow`, `This Week`).
  - View Switcher Toggle: `Timeline Grid View` (Rooms vs Time) vs `Data Table View`.
  - Search & Filter: Filter by status (`All`, `Pending`, `In-Service`, `Completed`).
- **Main View A: Timeline Grid View (Gantt style):**
  - X-Axis: Time Slots (10:00 to 21:00).
  - Y-Axis: Rooms / Beds (Room 1, Room 2, Couple Room, Foot Area).
  - Booking Blocks: Color-coded cards showing Customer Name, Course, and Health Alert Tag (`⚠️`).
- **Main View B: Data Table View:**
  - Columns: Booking Time, Customer Name & Phone, Service Course, Duration, Pax, Health Warning Tag, Assigned Therapist, Status Badge, Quick Actions.
  - **Quick Action Column:** One-click status dropdown (`Confirmed` -> `In-Service` -> `Completed`), plus `Call Customer` button.

---

## 3. Screen 3: Customer Directory & CRM (Split-Screen Layout)
- **Left Panel (Customer Directory Table - 60% Width):**
  - Search input (Name / Phone / Member Tier).
  - Data Columns: Name, Phone, Lifetime Visits, Total Spend, Birthday Month Badge, Loyalty Level (`VIP` / `Regular`).
  - Row Click Event: Loads selected customer into the Right Detail Panel.
- **Right Panel (Customer Slide-Over Detail Panel - 40% Width):**
  - **Header:** Customer Avatar, Full Name, Phone Number, LINE Contact status.
  - **Editable Health Profile:** Text area for medical notes, allergies, and massage preferences (Editable with `Save Notes` button).
  - **Visit History List:** Chronological log of previous visits, chosen treatments, assigned therapists, and total spent.
  - **Phase 2 CRM Tools:**
    - Loyalty Counter: "7 / 10 Visits completed" progress bar.
    - Action Buttons: `Send Birthday Coupon` / `Send Special LINE Voucher`.

---

## 4. Screen 3: Slot & Capacity Management
- **Top Rules Configuration Bar (Horizontal Cards):**
  - **Minimum Lead Time Setting:** Dropdown selector (`6 Hours`, `12 Hours`, `1 Day`, `2 Days`).
  - **Max Bed Capacity Setting:** Counter input for maximum simultaneous beds (`Max 6 Beds`).
- **Daily Time Slot Control Grid (Multi-Column Layout):**
  - Displays all operating slots for selected date (10:00, 11:30, 13:00, 14:30, 16:00, 17:30, 19:00, 20:30).
  - Each slot card shows: Slot Time, Capacity Progress Bar (e.g., "4/6 Beds Booked"), List of booked customers in that slot.
  - **Emergency Block Toggle Switch:** Switch on any slot to instantly block emergency bookings (disables LINE booking for that slot immediately).

---

## 5. Screen 4: Service & Menu Management
- **Category Tabs Header:** `Signature Packages`, `Massage Menu`, `Add-On Services`.
- **Service Management Data Table:**
  - Columns: Category, Service Name (Thai & English), Duration & Pricing Variants, Active Status Switch, Actions.
  - Example Rows:
    - *Traditional Thai Massage* | Variants: `60m - 300 ฿`, `120m - 600 ฿` | Active Toggle: `ON`
    - *Body Scrub* | Variant: `60m - 600 ฿` | Active Toggle: `ON`
  - **Active / Inactive Toggle Switch:** Instantly hide/show course on the customer-facing LINE menu (e.g., if specific massage oil is out of stock).
  - **Primary CTA:** Top right `+ Add New Service` button (opens creation modal).

---

## 6. Screen 5: Therapist Roster & Assignment (Dispatch Board)
- **Split-Screen Layout:**
  - **Left Board (Daily Staff Roster - 40% Width):**
    - Cards of working therapists today: Photo, Name, Current Status (`Available`, `In-Session - Ends 15:30`, `On Break`).
  - **Right Board (Unassigned Bookings Queue - 60% Width):**
    - Table/Cards of incoming bookings lacking assigned therapists.
    - **Dispatch Control:** Dropdown inside each booking row to select and assign an available therapist from today's roster.
    - Saves therapist ID for future commission reporting.

---

## 7. Screen 6: Store Dashboard & Analytics
- **Top Row (4 Horizontal KPI Metrics Cards):**
  1. `Today's Bookings`: Count & breakdown (`Completed`, `Upcoming`, `Cancelled`).
  2. `Estimated Revenue`: Today's Total (`฿`).
  3. `Weekly Revenue`: Current Week Total (`฿`).
  4. `Active Therapists`: On-duty count vs total staff.
- **Main Analytics Grid (2-Column Charts):**
  - **Left Panel (Peak Hours Bar Chart):** Visualizes popular booking time slots throughout the day.
  - **Right Panel (Top Services Donut Chart):** Distribution of top-selling treatment courses.
- **Time Range Filter Pill Bar:** Top right filter (`Daily`, `Weekly`, `Monthly`).