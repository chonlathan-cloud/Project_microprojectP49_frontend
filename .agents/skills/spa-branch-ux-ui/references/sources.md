# Spa Branch UX/UI Sources

Load only the source set relevant to the requested surface. Never query an unapproved Stitch project.

## Shared Product Boundary

- Application root: `SPA/`
- Do not use the existing root-level `frontend/` as the Spa application.
- Stitch access is read-only.
- Future approved business requirements, HLD, TTD, and LLD govern product behavior and technical decisions.

## Admin Sources

- Local visual system: `SPA/Document/DESING/Side-Admin/DESIGN.md`
- Local journey and screen intent: `SPA/Document/DESING/Side-Admin/FLOW_STITCH.md`
- Stitch project: `SPA-Admin-Views`
- Project ID: `4396310542632779378`
- Intended surface: desktop operations for reception and branch management.
- Target design viewports: `1440x900` and `1920x1080`; also inspect at a practical minimum desktop width of `1280px`.

Current Admin Stitch screens include:

- Booking Calendar
- Customer CRM
- Slot Management
- Service Menu
- Therapist Roster
- Analytics Dashboard

Stitch reports high-resolution `2560x2048` screen assets. Treat these as source-image dimensions, not mandatory browser viewports.

## Customer Sources

- Local visual system: `SPA/Document/DESING/Side-Customer/DESIGN.md`
- Local journey and screen intent: `SPA/Document/DESING/Side-Customer/FLOW_STITCH.md`
- Stitch project: `SPA-Customer-Views`
- Project ID: `16425235465563176187`
- Intended surface: mobile-first customer discovery and booking with responsive expansion.
- Target mobile viewports: `360x800`, `390x844`, and `430x932`.
- Inspect a wider responsive state only when required by approved requirements.

Current Customer Stitch screens include:

- Digital Menu
- Booking Step 1: Review Services
- Booking Step 2: Select Time
- Booking Step 3: Customer Details
- Booking Step 4: Confirmation
- My Spa Bookings
- Daily Room Schedule

The current Stitch project marks its visual canvases as desktop. Preserve its visual composition and content intent while adapting interaction and layout to the approved mobile-first product direction. Flag any feature that cannot be adapted without a product decision.

## Known Discrepancies to Re-check

Do not resolve these differences by inference. Re-check them against approved requirements and record the decision:

- Admin status names and colors differ across `DESIGN.md`, `FLOW_STITCH.md`, and Stitch. In particular, Confirmed/Pending and In-Service do not have one consistent color mapping.
- Customer Stitch screens contain illustrative treatments, prices, discounts, dates, step labels, and payment concepts that do not consistently match `FLOW_STITCH.md`.
- Customer Stitch includes non-THB sample pricing in places. Never treat it as canonical pricing or currency behavior.
- Customer Step 3 in Stitch does not show every field named by the local flow, including email.
- Several literal status, accent, and muted-text token combinations may not reach WCAG AA for small text. Verify contrast and propose accessible variants; do not silently approve failing combinations.

## Source Authority by Dimension

| Dimension | Primary source | Secondary source |
| --- | --- | --- |
| Business behavior and acceptance | Approved requirements | `FLOW_STITCH.md` |
| Architecture and contracts | Approved HLD/TTD/LLD | Existing `SPA/` code |
| Visual identity and tokens | Relevant `DESIGN.md` | Matching Stitch project |
| Screen composition | Matching Stitch screen | Relevant `FLOW_STITCH.md` |
| Existing implementation behavior | Approved artifacts | Existing `SPA/` code |
