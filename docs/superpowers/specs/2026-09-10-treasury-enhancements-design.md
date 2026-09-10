# Treasury Improvements & Event Payment Exports Specification

**Author:** Robot & Boss Kim  
**Date:** 2026-09-10  
**Target Application:** Student Treasurer (`C:\Users\MoyMoy\Desktop\StudentTreasurer`)  
**Status:** Approved by Boss Kim  

---

## 1. Executive Summary & Goals

The Student Treasurer application provides financial management for student organizations and classes. This specification defines upgrades to:
1. **Track Where the Money Has Gone:** Provide intuitive, high-visibility breakdowns of expenditures across categories (Refunds, Platform Services, Event Programs, Supplies, Operations) on the Dashboard and within the Transparency Report.
2. **Export Event Payments:** Implement multi-format export capabilities for event collections:
   - Single-event CSV export
   - Single-event styled Excel (`.xlsx`) export
   - Master Multi-Sheet Excel (`.xlsx`) workbook with **a dedicated named tab for each event** plus an Overview Summary sheet
   - Formal Table Form Print-to-PDF view ready for auditing and official liquidation sign-offs
3. **Fix and Enhance Existing Report Exports:** Enable date-range filtered transaction exports, per-student balance exports, and hardened UTF-8 BOM CSV handling.
4. **Fix UI and Usability Issues:** Repair broken active navigation link states in the sidebar and mobile bottom nav, streamline payment collection with quick-select shortcuts, and refine dark-mode table contrast.
5. **Zero Database Modifications:** Strictly guarantee that **no database schema migrations, table alters, index drops, or record deletions** occur. All calculations and exports run in application memory over existing collections (`events`, `payments`, `students`, `transactions`, `users`).

---

## 2. Constraints & Guarantees

* **Zero-DB-Touch Guarantee:**
  - No new MongoDB collections.
  - No changes to existing document structures in `events`, `payments`, `students`, `transactions`, or `users`.
  - Aggregations and categorizations occur at query/view layer in Python.
* **Libraries:**
  - Utilize existing Python environment packages (`Flask`, `pymongo`, `openpyxl`, `xlsxwriter`, `csv`, `io`).
  - No heavy native C-library dependencies (e.g. no WeasyPrint required); print-to-PDF uses high-fidelity browser print rendering (`@media print` CSS and window.print()).
* **Access Control:**
  - Exports respect `@login_required` and role-based access where appropriate.
  - Management actions remain restricted to `admin`, `mayor`, `treasurer`.

---

## 3. Detailed Technical Design

### 3.1. "Where the Money Has Gone" Visibility

#### Dashboard Enhancement (`app/dashboard.py`, `templates/dashboard.html`)
* Extract categorized disbursements dynamically from active expense transactions:
  - *Student Refunds & Adjustments*
  - *Platform & System Services*
  - *Event Remittances & Programs*
  - *Supplies & Materials*
  - *Operations & Miscellaneous*
* Render a **"Disbursement Categories (Where Money Went)"** card on the dashboard with percentage bars and peso amounts alongside recent outflows.
* Add an explicit link routing directly to the full Transparency & Liquidation breakdown.

#### Transparency & Liquidation View (`app/reports.py`, `templates/reports.html`)
* Provide instant category badges, variance analysis between event collections and disbursements, and Sinking Fund advance tracking.
* Add client-side search filtering on the Itemized Disbursements register so users can quickly locate specific payees, vouchers, or event expenses.

---

### 3.2. Event Payment Exports

#### A. Dedicated Single-Event Exports (`app/events.py` or `app/reports.py`)
1. **Route: `GET /events/export/<int:id>` (CSV)**
   * Streams `text/csv` with `utf-8-sig`.
   * **Header Info:** Event Title, Due Date, Fee Amount, Total Students, Collected Amount, Fully Paid Count, Generation Timestamp.
   * **Columns:** `No.`, `Student ID`, `Full Name`, `Course`, `Year`, `Target (PHP)`, `Amount Paid (PHP)`, `Balance Due (PHP)`, `Status`, `Confirmed At`, `Confirmed By`, `Notes`.
2. **Route: `GET /events/export_excel/<int:id>` (Single-Event `.xlsx`)**
   * Uses `openpyxl` with styled headers, alternating row fills, formatted currency cells (`₱#,##0.00`), colored status pills, and summary formulas (`=SUM(...)`).

#### B. Master Multi-Sheet Excel Workbook
1. **Route: `GET /events/export_all_excel` (Multi-Sheet `.xlsx`)**
   * **Sheet 1: "All Events Overview"**
     - Summary table of all events: Event Name, Unit Fee, Total Students, Target Total, Collected, Outstanding, Status.
     - Auto-summed totals row.
   * **Subsequent Sheets: One Sheet Per Event**
     - Sheet name sanitized and limited to 31 characters (e.g., `Sinking Fund`, `Acquaintance Party`, `UniScan`).
     - Full roster of all active students for that event with columns:
       `No.`, `Student ID`, `Full Name`, `Course`, `Year`, `Target (₱)`, `Amount Paid (₱)`, `Balance (₱)`, `Status`, `Confirmed At`, `Confirmed By`.
     - Built-in `=SUM(...)` formulas for columns F, G, and H.

#### C. Formal Table Form Print-to-PDF View
1. **Route: `GET /events/print/<int:id>` (HTML Print Form)**
   * Minimalist, elegant document layout optimized for A4 / Letter paper.
   * Header with class title, official document badge, and date.
   * Executive summary metrics box (Target, Collected, Balance, Paid Count).
   * Formatted student ledger table with crisp borders.
   * Formal Sign-off & Certification block:
     - Prepared by: **Class Treasurer**
     - Attested & Verified by: **Class Mayor / Auditor**
   * Auto-print trigger and "Print / Save PDF" button.

---

### 3.3. General & Report Export Fixes (`app/reports.py`)

1. **Date-Range Aware Transaction Export (`/export`)**:
   * Inspect `request.args.get('start')` and `request.args.get('end')`.
   * When present, filter both manual transactions and confirmed event payments to that date window.
   * Return file named `treasury_report_YYYY-MM-DD_to_YYYY-MM-DD.csv` when filtered.
2. **Per-Student Summary Export (`/export_students`)**:
   * Export all active students with columns: `Student ID`, `Name`, `Course`, `Total Paid (PHP)`, `Total Used (PHP)`, `Net Balance (PHP)`.
3. **Liquidation CSV Hardening (`/export_liquidation`)**:
   * Include event liquidation matrix summary in addition to itemized disbursements.
   * Ensure safe zero-handling and clean formatting.

---

### 3.4. UI & Usability Bug Fixes

1. **Active Navigation Links (`templates/base.html`)**:
   * Fix navigation checking logic: replace exact matches like `request.endpoint == 'dashboard'` with prefix/flexible checks (e.g. `request.endpoint.startswith('dashboard')`, `request.endpoint.startswith('payments')`, `request.endpoint.startswith('events')`, `request.endpoint.startswith('reports')`, `request.endpoint.startswith('admin')`).
   * Apply consistent active state handling across both the desktop sidebar and mobile bottom navigation bar.
2. **Payment Collection Enhancements (`templates/payments.html`)**:
   * Add a "Select All Pending" checkbox and a "Fill Target Amount" button in the table header.
   * Keep payment inputs intuitive while properly toggling input activation.
3. **UI Export Menus & Action Buttons**:
   * In `templates/events.html`: Add an export dropdown on each event card with options:
     - <i class="bi bi-filetype-csv"></i> Export CSV
     - <i class="bi bi-file-earmark-excel"></i> Export Excel (.xlsx)
     - <i class="bi bi-printer"></i> Print / Save PDF Form
   * Add a prominent **"Export All Events (Multi-Sheet Excel)"** button in the Events page header and Reports page.
   * In `templates/payments.html`: Add direct export buttons when an event is selected.
4. **DataTables & Theme Contrast**:
   * Ensure select dropdowns, search boxes, and pagination controls remain readable in both Light and Dark themes.

---

## 4. Testing & Verification Strategy

1. **Unit & Integration Tests (`tests/test_app.py`)**:
   * Test `/events/export/<id>` returns 200 and valid CSV content with student details.
   * Test `/events/export_excel/<id>` returns valid `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
   * Test `/events/export_all_excel` returns multi-sheet workbook with expected sheet names.
   * Test `/events/print/<id>` renders printable HTML form with student roster and certification block.
   * Test `/export` with `start` and `end` query parameters filters transactions correctly.
   * Test `/export_students` returns 200 and student balances CSV.
2. **Verification Execution**:
   * Execute full `pytest` suite ensuring 100% pass rate.
   * Check linting / formatting with `ruff`.

---

## 5. Implementation Scope

* **Files to Modify:**
  - `app/events.py`: Add single-event and all-events export routes (CSV, Excel, Print View).
  - `app/reports.py`: Add date-range filtering to `/export`, add `/export_students`, support Excel workbook links.
  - `app/dashboard.py`: Compute and pass disbursement category summary.
  - `templates/base.html`: Fix active navigation highlighting in sidebar and mobile nav; add theme adjustments.
  - `templates/events.html`: Add export action buttons (CSV, Excel, Multi-Sheet, Print).
  - `templates/payments.html`: Add export button and batch payment helper controls.
  - `templates/reports.html`: Add export buttons for student balances, date ranges, and multi-sheet Excel.
  - `templates/dashboard.html`: Display "Where the Money Went" category card.
  - `templates/event_print.html`: New clean printable table form template.
  - `tests/test_app.py`: Comprehensive test coverage for all new export and print routes.
