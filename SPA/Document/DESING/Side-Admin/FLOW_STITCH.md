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
  - Primary Action: `+ Create Booking` opens a centered staff-assisted modal. Staff selects today, a future date, or a historical financial record while preserving the queue/calendar context behind the modal. Historical mode records immutable service subtotal, optional Admin discount, net service amount, separate optional tip, and gross total while skipping capacity reservation and customer notification. Tip input is available only in historical mode. An erroneous historical record can be cancelled from Booking detail with a required reason; cancellation excludes its financial total without changing Capacity or notifying the customer.
  - Date Filter Bar: Interactive Date Picker with quick buttons (`Today`, `Tomorrow`, `This Week`).
  - View Switcher Toggle: `Timeline Grid View` (Rooms vs Time) vs `Data Table View`.
  - Search & Filter: Server-side search by Booking ID/name/phone and status filter (`All`, `Pending`, `Confirmed`, `In-Service`). Changing either returns to page 1.
- **Main View A: Timeline Grid View (Gantt style):**
  - X-Axis: Time Slots (10:00 to 21:00).
  - Y-Axis: Rooms / Beds (Room 1, Room 2, Couple Room, Foot Area).
  - Booking Blocks: Color-coded cards showing Customer Name, Course, and Health Alert Tag (`⚠️`).
- **Main View B: Data Table View:**
  - Default order is newest appointment to oldest (`startAt DESC`), with 25 rows per page and selectable 50/100 row sizes.
  - Signed cursor pagination provides Previous/Next controls and stores query, status, page size, page number, and cursor in URL/history.
  - Columns: Booking Time, Customer Name & Phone, Service Course, Duration, Pax, Health Warning Tag, Assigned Therapist, Status Badge, Quick Actions.
  - **Quick Action Column:** One-click status dropdown (`Confirmed` -> `In-Service` -> `Completed`), plus `Call Customer` button.
  - **Booking Detail:** Row action opens a centered modal. A `CONFIRMED` Booking exposes one therapist selector per participant and saves assignment in place. Two-person Bookings require different active therapists. The Start action becomes available only after the assignment response succeeds. Historical records route therapist/pay/tip attribution through Settlement rather than operational assignment.
  - **Start-service Review and Discount:** `Start service` opens a second focused centered confirmation above Booking Detail. It shows assigned therapist, regular price, shop discount, and net service before status changes. `ADMIN` may add/update/remove a whole-THB discount with an audit reason; `STAFF` sees the amount read-only. Saving the financial change and transitioning to `IN_SERVICE` is one atomic command.
  - **Payment Recovery:** For an unpaid `COMPLETED` Booking, the centered modal retains an ADMIN-only correction control before payment for a missed or incorrect discount. Paid Bookings and active/unresolved Beam attempts are read-only; a changed post-service discount makes any earlier Settlement stale for review.

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
  - **Primary CTA:** Top right `+ Add New Service` button (opens creation modal). The duration-and-price section starts with one row and exposes `+ Add duration`, allowing multiple unique options such as 30/60 or 60/120 minutes before publishing.
  - **Existing Service Editor:** The duration-and-price section lists every current variant and provides an inline `Add duration option` control so staff can add a missing duration without recreating the service.

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
- **Access:** `ADMIN` only. `STAFF` does not see the navigation item and the API independently returns `403`.
- **Date Range Header:** Explicit start/end local dates with an Apply action; default is the latest 30 days.
- **Financial Summary Strip:** Net service revenue after shop discount, verified collected payment, historical-record gross, outstanding payment, therapist pay/tip, and allocated shop share. These values are labelled separately and never collapsed into one ambiguous revenue number.
- **Attention State:** Highlights completed/historical Bookings still awaiting allocation, stale tip allocations, and negative shop service shares.
- **Revenue Trend:** Daily service revenue and tip bars for the chosen range.
- **Top Services Table:** Ranked by participant count, sessions, duration variant, gross price, allocated discount, and net service revenue.
- **Peak Hours:** Separate scheduled-start and actual-service-start bars. Historical rows without an actual start timestamp are omitted from the actual series rather than inferred.
- **Therapist Performance Table:** Sessions, service minutes, fixed Admin-entered therapist pay, and therapist tip share. It is an operational allocation report, not an automated payroll engine.

## 7.1 Detailed Insight Workspace

- **Access:** `ADMIN` only in both navigation and API authorization.
- **Purpose:** Keep Dashboard concise while allowing detailed analysis of revenue, service variants, therapists, and serviced Bookings.
- **Filters:** Local service-date range, Booking channel/admin entry mode, service and duration variant, therapist, Booking/Payment/Settlement status, discount/tip presence, and scheduled hour.
- **Views:** Revenue by date, Services, Therapists, and serviced Booking rows. Every view uses server-side filtering and pagination.
- **CSV Export:** Export the active view with the applied filters. Revenue/Booking values are not repeated across participant-level therapist rows. Export excludes health details and full contact information, uses UTF-8 CSV for Thai text, and appends an audit event.

## 8. Completed/Historical Booking Financial Allocation

- Finishing an active Booking or creating a `RECORDED` history row may open a centered `ADMIN` settlement dialog; Admin may close it and return later without blocking service completion.
- Each participant row shows the immutable service snapshot and accepts therapist, fixed therapist pay in whole THB, and therapist tip share. Two-person Packages retain independent rows and values.
- The footer continuously reconciles customer net service amount, total therapist pay, shop service remainder, received tip, therapist tip, and shop tip remainder.
- Shop promotion discount never reduces the entered therapist pay automatically. A negative shop service remainder remains saveable but requires a prominent warning and final confirmation.
- Saving is version-checked, audited, and available again from Booking detail for correction. If a later Payment changes the received tip, the UI requires tip reallocation.
