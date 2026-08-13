# Design System: Spa 49 Admin Desktop Web

## 1. Visual Identity & Vibe
- **Vibe:** Efficient, High-Density, Operational, Professional Hospitality Desktop Management Dashboard.
- **Target Platform:** Desktop Web Browsers (1920x1080 / 1440x900 resolution for Reception Desk & Store Manager Laptops).
- **Style:** Clean multi-column card grid, high-contrast data tables, collapsible sidebar navigation, slide-over detail panels, and visible alert badges.
- **Shapes:** Rounded corners (`8px` to `12px` for desktop panels), full pill shapes (`999px`) for status tags and toggles.

## 2. Color Palette
Maintains Spa 49 brand identity optimized for desktop operational dashboards:

*   **Primary Brand (Forest Green):** `#4E6148` - Sidebar navigation, active navigation items, and primary CTA buttons.
*   **Accent Brand (Spa Gold):** `#C3A36C` - Metric highlights, VIP customer badges, and border highlights.
*   **Background (Light Slate / Warm Off-White):** `#F4F5F2` - Main desktop dashboard backdrop.
*   **Surface / Panel Background:** `#FFFFFF` - High-contrast white panels, cards, and data table containers.
*   **Text Primary (Dark Charcoal):** `#1F2937` - Main table text, customer names, prices, and times.
*   **Text Secondary (Muted Slate):** `#6B7280` - Subtitles, table headers, and form labels.

### Operational Status Palette
*   **Confirmed / Pending (Amber):** `#D97706` text on `#FEF3C7` pill background.
*   **In-Service (Blue):** `#2563EB` text on `#DBEAFE` pill background.
*   **Completed (Green):** `#16A34A` text on `#DCFCE7` pill background.
*   **Cancelled / Closed (Red):** `#DC2626` text on `#FEE2E2` pill background.
*   **Health Alert Warning Tag:** Bold `#B91C1C` text on `#FEE2E2` background with warning icon (`⚠️`).

## 3. Typography
- **Headings & Metrics:** Sans-Serif (*Prompt* / *Sarabun* for TH, *Inter* for EN). Bold weights (`600` / `700`) for data visualization and KPI headers.
- **Data Tables & Forms:** High-density Sans-Serif (`13px` - `14px`), optimized for reading multi-column tables on desktop screens.

## 4. UI Components & Desktop Layout Elements
- **Desktop Collapsible Left Sidebar:** Persistent navigation menu containing branch indicator ("Spa 49 - Sukhumvit"), staff avatar, and 6 main navigation links:
  1. `Booking Calendar`
  2. `Customer CRM`
  3. `Slot Management`
  4. `Service & Menu`
  5. `Therapist Roster`
  6. `Analytics Dashboard`
- **Slide-Over Detail Panel (Right Drawer):** `380px` width slide-over panel for displaying detailed customer history or booking information without leaving the main grid.
- **Data Table:** Sticky header row, zebra striping on hover, inline quick-action buttons (`Change Status`, `Call`), and health alert tags.