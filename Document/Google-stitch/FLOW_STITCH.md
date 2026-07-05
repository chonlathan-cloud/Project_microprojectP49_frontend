# UI/UX Interaction Flow: Receipt Validation & Sync

## 1. Navigation Structure
- **Global Layout:** Sidebar Navigation on the left, Main Content Area on the right.
- **Sidebar Menu Items:**
  - Dashboard
  - Upload Receipt (Active State)
  - Expense History
  - Settings

## 2. Screen-by-Screen Layout & Interactions

### Screen 1: Upload Receipt Page (`/dashboard/upload-receipt`)
- **Header:** Title "Upload Receipt for FlowAccount Sync" with a badge showing user role (`Admin` or `Executive`).
- **Form Component:**
  - **Store/Branch Dropdown:** Selection required before uploading.
  - **Drag & Drop Zone:** Large dashed-border area supporting Image/PDF uploads. 
- **Interaction:** Dragging a file turns the border to Primary Blue. Dropping a file triggers a micro-loading animation, then automatically redirects the user to Screen 2.

### Screen 2: Receipt Validation Page (`/dashboard/receipt-validation/[id]`)
- **Layout:** Split-Screen View (50% Left / 50% Right)
  - **Left Pane:** Sticky Sticky Receipt Document Viewer (Image Zoom/Pan features).
  - **Right Pane:** Scrollable Validation Form broken down into explicit sections/cards:

#### Section A: Line Items & Totals Check
- Editable data table displaying line items, categories, and adjustments extracted by OCR.
- Grand Total prominent display at the bottom of the table.

#### Section B: Dealer Details Card
- **Dealer Name:** Text input.
- **Tax ID:** Text input. *Validation rule:* Must be exactly 13 digits. If not, show inline warning: `"Dealer tax ID must contain 13 digits for purchasing tax invoice sync."`
- **Branch:** Text input (Prefilled with "สำนักงานใหญ่").

#### Section C: Purchasing Tax Invoice Details Card
- **Tax Invoice Number:** Text input (Asterisk indicating Required). *Validation rule:* If empty, show inline warning: `"Purchasing tax invoice number is required before syncing to FlowAccount."`
- **Tax Form:** Read-only dropdown fixed to "P.P.30".

#### Section D: FlowAccount Payment Config Card
- **Payment Method Toggle:** Segmented control button selector between `Cash` and `Transfer`.
- **Bank Account Dropdown:** Conditional Field. Appears ONLY if `Transfer` is selected. *Validation rule:* If left unselected when Transfer is active, show inline warning: `"Please select a transfer bank account before syncing to FlowAccount."`

#### Section E: Bottom Action Bar
- Sticky bar at the bottom containing the primary action button: `Verify, Save & Sync to FlowAccount`.

---

## 3. Key Modal Dialogs & Feedback States

### Case A: Duplicate Sync Warning (Modal)
- **Trigger:** Clicking Sync when the system detects the receipt has been synced before.
- **UI Element:** A Warning Modal titled "Duplicate Document Detected".
- **Message:** `"Receipt already synced to FlowAccount. Confirm before creating another FlowAccount document."`
- **Actions:** `Cancel` (Dismisses modal) | `Confirm & Create Duplicate` (Proceeds with sync action).

### Case B: Successful Sync State
- **UI Element:** The validation page reloads into a read-only confirmation state showing a success alert banner.
- **Status Components:**
  - Green Success Badge: `Synced to FlowAccount`
  - Meta Info Row 1: `Document: [FlowAccount expense serial] - Attachment: synced`
  - Meta Info Row 2: `Purchasing Tax Invoice Details: synced - [tax invoice number]`

### Case C: Partial Success State (Supplier Invoice Failure)
- **UI Element:** A split feedback banner at the top of the page.
- **Banner 1 (Success):** Expense document successfully created in FlowAccount.
- **Banner 2 (Danger):** `"Failed to attach Purchasing Tax Invoice Details: [Error Message Details]"` (Allows user to retry just the tax section without duplicating the expense).