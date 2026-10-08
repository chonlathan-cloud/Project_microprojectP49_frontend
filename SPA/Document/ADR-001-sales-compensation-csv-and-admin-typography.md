# ADR-001: Thai sales and therapist-compensation CSV exports

- **Status:** Accepted
- **Date:** 2026-10-08
- **Decision owner:** Product owner
- **Applies to:** SPA API and SPA Admin Web

## Context

The Admin Insight workspace already exports UTF-8 CSV data, but it exposes internal English field
names and raw satang values. Its therapist view includes service allocations only, so it cannot be
used as the authoritative amount to pay a therapist because attendance-based hand guarantees,
shop-funded adjustments, prior payouts, and outstanding amounts belong to the therapist
compensation ledger.

The operational users need Thai, spreadsheet-readable exports covering sales, daily therapist
earnings, and the amount payable per therapist. They also reported that Admin Web text is too small
for continuous front-desk use.

## Decision

### Export boundaries

The product exports three independent CSV files instead of placing multiple row grains in one CSV:

1. **Sales:** one row per eligible `COMPLETED` or `RECORDED` Booking.
2. **Daily therapist compensation:** one row per therapist and local service date that has
   attendance, service work, a shop adjustment, or a payout allocation.
3. **Therapist payout summary:** one row per therapist with activity in the selected period.

Keeping Booking revenue separate from participant-level therapist allocations prevents couple
packages and multi-therapist Bookings from duplicating sales revenue. A future Excel workbook may
place these row grains on separate sheets, but XLSX output is not part of this decision.

### Sales columns and calculations

The sales CSV uses these Thai columns in order:

```text
วันที่ให้บริการ
เวลาเริ่มนวด
ระยะเวลานวด (นาที)
เลขที่รายการ
รายการขาย
ชื่อหมอนวด
ราคาขายสุทธิ (บาท)
ค่ามือหมอ (บาท)
เงินร้านจากค่าบริการ (บาท)
ทิปรวม (บาท)
ทิปหมอ (บาท)
ทิปร้าน (บาท)
สถานะชำระเงิน
สถานะสรุปค่าหมอ
```

`ราคาขายสุทธิ` is the Booking net service amount after discount and excludes tip.
`เงินร้านจากค่าบริการ` is net service amount minus therapist service pay. `ทิปร้าน` is received tip
minus therapist tip shares. Negative shop service amounts remain visible because the existing
Settlement contract explicitly permits audited loss-making allocations.

Massage duration uses `endAt - startAt`. For a legacy record without usable timestamps, it uses the
longest participant treatment timeline reconstructed from immutable service-line snapshots. Shared
couple-package duration is therefore not multiplied by participant count.

When Settlement is `PENDING` or `STALE`, therapist names and all derived therapist/shop allocation
cells are blank. The CSV must not represent missing or invalid allocation as zero. Booking net price,
received tip, payment status, and the Thai Settlement status remain visible.

### Therapist compensation columns and calculations

Daily and summary CSVs use the server-owned compensation projection. The invariant remains:

```text
guaranteeTopUp = present ? max(0, guaranteeRateSnapshot - servicePay) : 0
totalEarned = servicePay + therapistTip + guaranteeTopUp + signedShopAdjustments
outstanding = totalEarned - payoutDailyAllocations
```

Tips never reduce a hand guarantee. A present therapist with no customers receives the full daily
guarantee. An absent therapist receives no guarantee. Paid source records remain immutable and later
corrections remain signed adjustment entries.

### File, security, and audit contract

- CSV is UTF-8 with BOM, comma-delimited, CRLF-compatible, and uses Thai headers.
- Money is exported in baht with exactly two decimal places; raw satang is not exposed.
- Download responses provide an ASCII fallback filename plus an RFC 5987 UTF-8 Thai filename.
- Text cells that begin with spreadsheet formula control characters are prefixed safely.
- Export is `ADMIN`-only and excludes customer contact and health data and internal database IDs.
- Every export records actor, branch, report type/view, local-date range, filters, row count, and UTC
  creation time in `audit_events`.
- Sales retains the Insight limit of 366 inclusive dates and 5,000 rows. Compensation retains its
  93-day inclusive range limit.

### Admin typography

Admin Web textual sizes increase by approximately 3px, with a 12px minimum for operational text.
Decorative/icon glyph sizes are preserved. Tables retain horizontal scrolling rather than reducing
text size to force every column into the viewport. Thai and English layouts are validated at 1280px,
1440x900, and 1920x1080.

## Consequences

- Finance receives human-readable files without duplicating ledger calculations in the browser.
- Three downloads are required when the user needs the complete sales and payroll package.
- Larger text reduces information density and can increase horizontal scrolling, especially at the
  1280px minimum Admin viewport.
- Existing Settlement, attendance, guarantee, payout, and Booking schemas do not change; no data
  migration is required.

## Deployment and rollback

Deploy SPA API before Admin Web in Test, verify readiness, and download all three files through the
deployed Admin UI. Production deployment requires a reviewed, committed, clean `main` worktree and
all repository production gates. Record the current Cloud Run revisions before deployment. If API
readiness, Admin smoke testing, or post-deploy error checks fail, restore traffic to the recorded
revisions for both changed services.

## Alternatives considered

- **One CSV containing detail and totals:** rejected because mixed row grains produce ambiguous or
  duplicated totals.
- **Excel workbook with three sheets:** deferred because CSV satisfies the current requirement
  without adding a generation dependency.
- **Browser-side export:** rejected because the SPA API owns financial filtering, authorization,
  calculation, privacy projection, and audit evidence.
