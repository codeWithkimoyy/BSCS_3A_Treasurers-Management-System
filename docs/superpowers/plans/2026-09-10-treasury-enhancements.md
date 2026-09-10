# Treasury Improvements & Event Payment Exports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide full expense transparency ("Where the money has gone"), single & multi-sheet Excel/CSV/PDF event payment exports, date-range and student report exports, and comprehensive UI fixes without touching the MongoDB database.

**Architecture:** Implement application-layer aggregation and streaming export endpoints in Flask blueprints (`events.py`, `reports.py`, `dashboard.py`) leveraging Python's `csv`, `io`, and `openpyxl`. Fix Jinja2 navigation matching and table UI in `templates/base.html`, `templates/events.html`, `templates/payments.html`, `templates/reports.html`, and `templates/dashboard.html`.

**Tech Stack:** Python 3.14, Flask 3.1.3, openpyxl, Jinja2, Bootstrap 5.3, DataTables 1.13, Pytest.

## Global Constraints

- **No Touching the Database:** Absolutely zero changes to database schemas, collections, indexes, or document structures.
- **Dependency Safety:** Use existing Python libraries (`openpyxl`, `csv`, `io`); do not introduce uninstalled system dependencies.
- **Security & Authorization:** All export and management endpoints must be protected by `@login_required` and role checks (`admin`, `mayor`, `treasurer`) where applicable.
- **Encoding:** All generated CSVs must use UTF-8 BOM (`utf-8-sig`) to ensure proper display in Microsoft Excel.

---

### Task 1: Event Payment Single Exports (CSV & Styled Excel)

**Files:**
- Modify: `app/events.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `db.events`, `db.payments`, `db.students`, `db.users`
- Produces:
  - Route: `GET /events/export/<int:id>` -> CSV download (`event_payments_<id>_<date>.csv`)
  - Route: `GET /events/export_excel/<int:id>` -> Excel download (`event_payments_<id>_<date>.xlsx`)

- [ ] **Step 1: Write failing tests for single-event CSV and Excel exports**

Add to `tests/test_app.py`:
```python
def test_export_event_csv(client, db):
    login(client, db, 'admin')
    # Create event
    ev_id = 101
    db.events.insert_one({
        '_id': ev_id,
        'title': 'Test Gala',
        'amount': 250.0,
        'deadline': '2026-10-01',
        'status': 'active',
    })
    # Create student
    st_id = 201
    db.students.insert_one({
        '_id': st_id,
        'student_id': 'STU-001',
        'name': 'Cruz, Juan',
        'course': 'BSCS',
        'year': '3rd',
        'is_active': 1,
        'deleted': False,
    })
    # Create payment
    db.payments.insert_one({
        '_id': 301,
        'event_id': ev_id,
        'student_id': st_id,
        'amount': 250.0,
        'amount_paid': 250.0,
        'confirmed': True,
        'locked': True,
        'confirmed_at': datetime(2026, 9, 10, 10, 0),
        'confirmed_by': 1,
        'notes': 'Paid in full',
    })

    resp = client.get(f'/events/export/{ev_id}')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers.get('Content-Type', '')
    csv_text = resp.get_data(as_text=True)
    assert 'Test Gala' in csv_text
    assert 'Cruz, Juan' in csv_text
    assert 'STU-001' in csv_text
    assert 'Fully Paid' in csv_text


def test_export_event_excel(client, db):
    login(client, db, 'admin')
    ev_id = 102
    db.events.insert_one({
        '_id': ev_id,
        'title': 'Intramurals 2026',
        'amount': 150.0,
        'deadline': '2026-11-15',
        'status': 'active',
    })
    st_id = 202
    db.students.insert_one({
        '_id': st_id,
        'student_id': 'STU-002',
        'name': 'Reyes, Maria',
        'course': 'BSIT',
        'year': '2nd',
        'is_active': 1,
        'deleted': False,
    })
    resp = client.get(f'/events/export_excel/{ev_id}')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers.get('Content-Type', '')
    assert 'event_payments_' in resp.headers.get('Content-Disposition', '')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py::test_export_event_csv tests/test_app.py::test_export_event_excel`  
Expected: FAIL with 404 (routes not implemented).

- [ ] **Step 3: Implement single-event CSV and Excel exports in `app/events.py`**

In `app/events.py`, add imports:
```python
import csv
import io
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from flask import send_file
```

Add helper function `get_event_payment_roster(event_id)`:
```python
def get_event_payment_roster(event_id):
    event = db.events.find_one({'_id': event_id})
    if not event:
        return None, None
    students = list(db.students.find({'is_active': 1, 'deleted': {'$ne': True}}).sort('name', 1))
    payments = {p['student_id']: p for p in db.payments.find({'event_id': event_id})}
    user_map = {u['_id']: u.get('display_name') or u.get('username') for u in db.users.find({})}

    target = float(event.get('amount', 0))
    roster = []
    for idx, s in enumerate(students, 1):
        pmt = payments.get(s['_id'])
        paid = float(pmt.get('amount_paid', 0)) if pmt else 0.0
        balance = max(0.0, target - paid)
        if pmt and pmt.get('locked'):
            status = 'Fully Paid'
        elif paid > 0:
            status = 'Partial'
        else:
            status = 'Pending'
        
        conf_by = user_map.get(pmt.get('confirmed_by'), '') if pmt else ''
        conf_at = pmt.get('confirmed_at').strftime('%Y-%m-%d %H:%M') if pmt and pmt.get('confirmed_at') else ''

        roster.append({
            'num': idx,
            'student_id': s.get('student_id', ''),
            'name': s.get('name', ''),
            'course': s.get('course', ''),
            'year': s.get('year', ''),
            'target': target,
            'paid': paid,
            'balance': balance,
            'status': status,
            'confirmed_at': conf_at,
            'confirmed_by': conf_by,
            'notes': pmt.get('notes', '') if pmt else ''
        })
    return event, roster
```

Add routes:
```python
@bp.route('/events/export/<int:id>')
@login_required
def export_csv(id):
    event, roster = get_event_payment_roster(id)
    if not event:
        flash('Event not found', 'error')
        return redirect(url_for('events.index'))

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['EVENT PAYMENT ROSTER & AUDIT REPORT'])
    w.writerow(['Event Title', event.get('title', '')])
    w.writerow(['Fee Amount (PHP)', f"{event.get('amount', 0):.2f}"])
    w.writerow(['Deadline', event.get('deadline', 'N/A')])
    w.writerow(['Total Members', len(roster)])
    total_collected = sum(r['paid'] for r in roster)
    total_balance = sum(r['balance'] for r in roster)
    w.writerow(['Total Collected (PHP)', f"{total_collected:.2f}"])
    w.writerow(['Total Outstanding (PHP)', f"{total_balance:.2f}"])
    w.writerow(['Generated At', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    w.writerow([])
    w.writerow(['No.', 'Student ID', 'Full Name', 'Course', 'Year', 'Target (PHP)', 'Amount Paid (PHP)', 'Balance Due (PHP)', 'Status', 'Date Confirmed', 'Confirmed By', 'Notes'])

    for r in roster:
        w.writerow([
            r['num'], r['student_id'], r['name'], r['course'], r['year'],
            f"{r['target']:.2f}", f"{r['paid']:.2f}", f"{r['balance']:.2f}",
            r['status'], r['confirmed_at'], r['confirmed_by'], r['notes']
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    slug = "".join(c if c.isalnum() else "_" for c in event.get('title', 'event'))
    return send_file(mem, as_attachment=True, download_name=f'event_{slug}_{date.today().isoformat()}.csv', mimetype='text/csv')


@bp.route('/events/export_excel/<int:id>')
@login_required
def export_excel(id):
    event, roster = get_event_payment_roster(id)
    if not event:
        flash('Event not found', 'error')
        return redirect(url_for('events.index'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Event Payments"[:31]

    # Styles
    navy_fill = PatternFill(start_color="1E1B4B", end_color="1E1B4B", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Arial", size=14, bold=True, color="1E1B4B")
    sub_font = Font(name="Arial", size=10, italic=True, color="64748B")
    bold_font = Font(name="Arial", size=10, bold=True)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # Title Block
    ws['A1'] = "OFFICIAL EVENT PAYMENT ROSTER"
    ws['A1'].font = title_font
    ws['A2'] = f"Event: {event.get('title', '')} | Fee: ₱{event.get('amount', 0):.2f} | Deadline: {event.get('deadline') or 'N/A'}"
    ws['A2'].font = sub_font
    ws['A3'] = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ws['A3'].font = sub_font

    # Headers
    headers = ['No.', 'Student ID', 'Full Name', 'Course', 'Year', 'Target (₱)', 'Amount Paid (₱)', 'Balance (₱)', 'Status', 'Confirmed Date', 'Confirmed By']
    start_row = 5
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col_idx, value=h)
        cell.fill = navy_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if col_idx in (1, 4, 5, 9) else ("right" if col_idx in (6, 7, 8) else "left"))

    # Rows
    for idx, r in enumerate(roster, start_row + 1):
        ws.cell(row=idx, column=1, value=r['num']).alignment = Alignment(horizontal="center")
        ws.cell(row=idx, column=2, value=r['student_id']).alignment = Alignment(horizontal="center")
        ws.cell(row=idx, column=3, value=r['name'])
        ws.cell(row=idx, column=4, value=r['course']).alignment = Alignment(horizontal="center")
        ws.cell(row=idx, column=5, value=r['year']).alignment = Alignment(horizontal="center")
        
        c_target = ws.cell(row=idx, column=6, value=r['target'])
        c_target.number_format = '₱#,##0.00'
        c_paid = ws.cell(row=idx, column=7, value=r['paid'])
        c_paid.number_format = '₱#,##0.00'
        c_bal = ws.cell(row=idx, column=8, value=r['balance'])
        c_bal.number_format = '₱#,##0.00'

        c_status = ws.cell(row=idx, column=9, value=r['status'])
        c_status.alignment = Alignment(horizontal="center")
        if r['status'] == 'Fully Paid':
            c_status.font = Font(name="Arial", size=10, bold=True, color="059669")
        elif r['status'] == 'Partial':
            c_status.font = Font(name="Arial", size=10, bold=True, color="D97706")
        else:
            c_status.font = Font(name="Arial", size=10, color="94A3B8")

        ws.cell(row=idx, column=10, value=r['confirmed_at'])
        ws.cell(row=idx, column=11, value=r['confirmed_by'])

        for c in range(1, 12):
            ws.cell(row=idx, column=c).border = thin_border

    # Totals Row
    last_row = start_row + len(roster)
    total_row = last_row + 1
    ws.cell(row=total_row, column=3, value="TOTALS").font = bold_font
    ws.cell(row=total_row, column=6, value=f"=SUM(F{start_row+1}:F{last_row})").number_format = '₱#,##0.00'
    ws.cell(row=total_row, column=7, value=f"=SUM(G{start_row+1}:G{last_row})").number_format = '₱#,##0.00'
    ws.cell(row=total_row, column=8, value=f"=SUM(H{start_row+1}:H{last_row})").number_format = '₱#,##0.00'
    for c in (3, 6, 7, 8):
        ws.cell(row=total_row, column=c).font = bold_font

    # Column Widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    mem = io.BytesIO()
    wb.save(mem)
    mem.seek(0)
    slug = "".join(c if c.isalnum() else "_" for c in event.get('title', 'event'))
    return send_file(mem, as_attachment=True, download_name=f'event_{slug}_{date.today().isoformat()}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py::test_export_event_csv tests/test_app.py::test_export_event_excel`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/events.py tests/test_app.py
git commit -m "feat: add single-event CSV and Excel payment export endpoints"
```

---

### Task 2: Multi-Sheet Master Excel Workbook & Printable Table Form View

**Files:**
- Create: `templates/event_print.html`
- Modify: `app/events.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `db.events`, `db.payments`, `db.students`, `db.users`
- Produces:
  - Route: `GET /events/export_all_excel` -> Multi-sheet Excel workbook with Overview tab + a sheet per event
  - Route: `GET /events/print/<int:id>` -> Rendered HTML print form

- [ ] **Step 1: Write failing tests for multi-sheet workbook and print form**

Add to `tests/test_app.py`:
```python
def test_export_all_events_excel(client, db):
    login(client, db, 'admin')
    # Insert 2 events
    db.events.insert_one({'_id': 110, 'title': 'Sinking Fund', 'amount': 100.0, 'status': 'active'})
    db.events.insert_one({'_id': 111, 'title': 'Acquaintance Party', 'amount': 300.0, 'status': 'active'})
    db.students.insert_one({'_id': 210, 'student_id': 'STU-010', 'name': 'Santos, Pedro', 'is_active': 1, 'deleted': False})

    resp = client.get('/events/export_all_excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers.get('Content-Type', '')
    assert 'all_events_' in resp.headers.get('Content-Disposition', '')

    # Verify sheets with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(resp.data))
    sheet_names = wb.sheetnames
    assert 'Overview' in sheet_names
    assert any('Sinking' in s for s in sheet_names)
    assert any('Acquaintance' in s for s in sheet_names)


def test_event_print_form(client, db):
    login(client, db, 'admin')
    ev_id = 120
    db.events.insert_one({'_id': ev_id, 'title': 'Graduation Fee', 'amount': 500.0, 'status': 'active'})
    db.students.insert_one({'_id': 220, 'student_id': 'STU-020', 'name': 'Del Rosario, Ana', 'is_active': 1, 'deleted': False})

    resp = client.get(f'/events/print/{ev_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'OFFICIAL EVENT PAYMENT ROSTER' in html
    assert 'Graduation Fee' in html
    assert 'Del Rosario, Ana' in html
    assert 'Class Treasurer' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py::test_export_all_events_excel tests/test_app.py::test_event_print_form`  
Expected: FAIL with 404.

- [ ] **Step 3: Create `templates/event_print.html`**

Create `templates/event_print.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Roster - {{ event.title }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        @page { size: A4 portrait; margin: 12mm 15mm; }
        body { background: #fff; color: #0f172a; font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; line-height: 1.3; }
        .print-btn-bar { background: #f8fafc; border-bottom: 1px solid #e2e8f0; padding: 10px 20px; }
        @media print { .no-print { display: none !important; } body { padding: 0 !important; } }
        .table-print { width: 100%; border-collapse: collapse; margin-top: 15px; }
        .table-print th { background: #1e1b4b !important; color: #fff !important; font-size: 8pt; text-transform: uppercase; padding: 6px 8px; border: 1px solid #1e1b4b; }
        .table-print td { padding: 5px 8px; border: 1px solid #cbd5e1; font-size: 8.5pt; }
        .table-print tr:nth-child(even) { background-color: #f8fafc; }
        .summary-card { border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px 14px; background: #f8fafc; }
        .status-badge { font-weight: 700; font-size: 7.5pt; text-transform: uppercase; }
        .status-paid { color: #059669; }
        .status-partial { color: #d97706; }
        .status-pending { color: #64748b; }
    </style>
</head>
<body>
    <div class="no-print print-btn-bar d-flex justify-content-between align-items-center">
        <div>
            <strong>{{ event.title }}</strong> &mdash; Printable Payment Table Form
        </div>
        <div class="d-flex gap-2">
            <button onclick="window.print()" class="btn btn-primary btn-sm"><i class="bi bi-printer"></i> Print / Save as PDF</button>
            <button onclick="window.close()" class="btn btn-outline-secondary btn-sm">Close</button>
        </div>
    </div>

    <div class="container-fluid p-4">
        <div class="text-center mb-3">
            <h5 class="mb-0 fw-bold" style="letter-spacing: -0.3px;">STUDENT TREASURY & FINANCIAL MANAGEMENT</h5>
            <h6 class="text-muted mb-1" style="font-size: 9pt;">OFFICIAL EVENT PAYMENT ROSTER & LIQUIDATION RECORD</h6>
            <div style="font-size: 8pt; color: #64748b;">Academic Year 2026-2027 | Generated: {{ now_str }}</div>
            <hr style="margin: 10px 0; border-top: 2px solid #0f172a;">
        </div>

        <div class="row g-2 mb-3">
            <div class="col-3">
                <div class="summary-card">
                    <small class="text-muted d-block" style="font-size: 7.5pt;">EVENT TITLE</small>
                    <strong style="font-size: 9pt;">{{ event.title }}</strong>
                </div>
            </div>
            <div class="col-3">
                <div class="summary-card">
                    <small class="text-muted d-block" style="font-size: 7.5pt;">TARGET FEE PER STUDENT</small>
                    <strong style="font-size: 9.5pt; color: #1e1b4b;">₱{{ "%.2f"|format(event.amount) }}</strong>
                </div>
            </div>
            <div class="col-3">
                <div class="summary-card">
                    <small class="text-muted d-block" style="font-size: 7.5pt;">TOTAL COLLECTED</small>
                    <strong style="font-size: 9.5pt; color: #059669;">₱{{ "%.2f"|format(total_collected) }}</strong>
                </div>
            </div>
            <div class="col-3">
                <div class="summary-card">
                    <small class="text-muted d-block" style="font-size: 7.5pt;">COLLECTION PROGRESS</small>
                    <strong style="font-size: 9.5pt;">{{ paid_count }} / {{ roster|length }} Students</strong>
                </div>
            </div>
        </div>

        <table class="table-print">
            <thead>
                <tr>
                    <th style="width: 30px; text-align: center;">#</th>
                    <th style="width: 90px; text-align: center;">Student ID</th>
                    <th>Full Name</th>
                    <th style="width: 70px; text-align: center;">Course</th>
                    <th style="width: 80px; text-align: right;">Target</th>
                    <th style="width: 80px; text-align: right;">Amount Paid</th>
                    <th style="width: 80px; text-align: right;">Balance</th>
                    <th style="width: 75px; text-align: center;">Status</th>
                    <th style="width: 100px;">Date Confirmed</th>
                    <th style="width: 90px;">Confirmed By</th>
                </tr>
            </thead>
            <tbody>
                {% for r in roster %}
                <tr>
                    <td style="text-align: center;">{{ r.num }}</td>
                    <td style="text-align: center; font-family: monospace;">{{ r.student_id }}</td>
                    <td><strong>{{ r.name }}</strong></td>
                    <td style="text-align: center;">{{ r.course }} {{ r.year }}</td>
                    <td style="text-align: right;">₱{{ "%.2f"|format(r.target) }}</td>
                    <td style="text-align: right; font-weight: 600; color: #059669;">₱{{ "%.2f"|format(r.paid) }}</td>
                    <td style="text-align: right; color: {{ '#dc2626' if r.balance > 0 else '#64748b' }};">₱{{ "%.2f"|format(r.balance) }}</td>
                    <td style="text-align: center;">
                        <span class="status-badge {{ 'status-paid' if r.status == 'Fully Paid' else ('status-partial' if r.status == 'Partial' else 'status-pending') }}">
                            {{ r.status }}
                        </span>
                    </td>
                    <td style="font-size: 7.5pt;">{{ r.confirmed_at or '—' }}</td>
                    <td style="font-size: 7.5pt;">{{ r.confirmed_by or '—' }}</td>
                </tr>
                {% endfor %}
            </tbody>
            <tfoot>
                <tr style="background: #f1f5f9; font-weight: bold;">
                    <td colspan="4" style="text-align: right;">TOTALS:</td>
                    <td style="text-align: right;">₱{{ "%.2f"|format(total_target) }}</td>
                    <td style="text-align: right; color: #059669;">₱{{ "%.2f"|format(total_collected) }}</td>
                    <td style="text-align: right; color: #dc2626;">₱{{ "%.2f"|format(total_balance) }}</td>
                    <td colspan="3"></td>
                </tr>
            </tfoot>
        </table>

        <!-- Sign-off Block -->
        <div class="row mt-5 pt-4">
            <div class="col-6 text-center">
                <div style="width: 75%; margin: 0 auto; border-top: 1.5px solid #0f172a; padding-top: 4px;">
                    <strong style="font-size: 9.5pt;">KIM C. CUTAMORA</strong><br>
                    <span class="text-muted" style="font-size: 8pt;">Class Treasurer</span>
                </div>
            </div>
            <div class="col-6 text-center">
                <div style="width: 75%; margin: 0 auto; border-top: 1.5px solid #0f172a; padding-top: 4px;">
                    <strong style="font-size: 9.5pt;">CLASS AUDITOR / MAYOR</strong><br>
                    <span class="text-muted" style="font-size: 8pt;">Verified & Attested Correct</span>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
```

- [ ] **Step 4: Implement multi-sheet Excel export and print route in `app/events.py`**

In `app/events.py`, add:
```python
@bp.route('/events/print/<int:id>')
@login_required
def print_roster(id):
    event, roster = get_event_payment_roster(id)
    if not event:
        flash('Event not found', 'error')
        return redirect(url_for('events.index'))

    total_collected = sum(r['paid'] for r in roster)
    total_balance = sum(r['balance'] for r in roster)
    total_target = sum(r['target'] for r in roster)
    paid_count = sum(1 for r in roster if r['status'] == 'Fully Paid')

    return render_template(
        'event_print.html',
        event=event,
        roster=roster,
        total_collected=total_collected,
        total_balance=total_balance,
        total_target=total_target,
        paid_count=paid_count,
        now_str=datetime.now().strftime('%B %d, %Y %I:%M %p')
    )


@bp.route('/events/export_all_excel')
@login_required
def export_all_excel():
    events = list(db.events.find({'deleted': {'$ne': True}}).sort('created_at', 1))
    students = list(db.students.find({'is_active': 1, 'deleted': {'$ne': True}}).sort('name', 1))
    user_map = {u['_id']: u.get('display_name') or u.get('username') for u in db.users.find({})}

    wb = openpyxl.Workbook()
    # Sheet 1: Overview
    ws_ov = wb.active
    ws_ov.title = "Overview"

    navy_fill = PatternFill(start_color="1E1B4B", end_color="1E1B4B", fill_type="solid")
    header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    bold_font = Font(name="Arial", size=10, bold=True)
    title_font = Font(name="Arial", size=13, bold=True, color="1E1B4B")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    ws_ov['A1'] = "CLASS TREASURY - ALL EVENTS SUMMARY"
    ws_ov['A1'].font = title_font
    ws_ov['A2'] = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ws_ov['A2'].font = Font(name="Arial", size=9, italic=True, color="64748B")

    ov_headers = ['#', 'Event Title', 'Deadline', 'Status', 'Fee (₱)', 'Eligible Students', 'Expected Total (₱)', 'Collected (₱)', 'Balance (₱)', 'Completion']
    for c_idx, h in enumerate(ov_headers, 1):
        cell = ws_ov.cell(row=4, column=c_idx, value=h)
        cell.fill = navy_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if c_idx in (1, 3, 4, 6, 10) else ("right" if c_idx in (5, 7, 8, 9) else "left"))

    used_sheet_names = {"Overview"}
    for ev_idx, ev in enumerate(events, 1):
        ev_id = ev['_id']
        ev_title = ev.get('title', f'Event {ev_idx}')
        fee = float(ev.get('amount', 0))
        total_students = len(students)
        expected = fee * total_students

        pmts = {p['student_id']: p for p in db.payments.find({'event_id': ev_id})}
        collected = sum(float(p.get('amount_paid', 0)) for p in pmts.values() if p.get('confirmed'))
        balance = max(0.0, expected - collected)
        pct = (collected / expected * 100) if expected > 0 else 0

        row = 4 + ev_idx
        ws_ov.cell(row=row, column=1, value=ev_idx).alignment = Alignment(horizontal="center")
        ws_ov.cell(row=row, column=2, value=ev_title)
        ws_ov.cell(row=row, column=3, value=ev.get('deadline') or '—').alignment = Alignment(horizontal="center")
        ws_ov.cell(row=row, column=4, value=ev.get('status', 'active').title()).alignment = Alignment(horizontal="center")
        
        c_fee = ws_ov.cell(row=row, column=5, value=fee)
        c_fee.number_format = '₱#,##0.00'
        ws_ov.cell(row=row, column=6, value=total_students).alignment = Alignment(horizontal="center")
        
        c_exp = ws_ov.cell(row=row, column=7, value=expected)
        c_exp.number_format = '₱#,##0.00'
        c_col = ws_ov.cell(row=row, column=8, value=collected)
        c_col.number_format = '₱#,##0.00'
        c_bal = ws_ov.cell(row=row, column=9, value=balance)
        c_bal.number_format = '₱#,##0.00'
        ws_ov.cell(row=row, column=10, value=f"{pct:.1f}%").alignment = Alignment(horizontal="center")

        for c in range(1, 11):
            ws_ov.cell(row=row, column=c).border = thin_border

        # Build dedicated sheet for this event
        safe_name = "".join(c for c in ev_title if c.isalnum() or c in (' ', '_', '-'))[:28].strip() or f"Event_{ev_idx}"
        sheet_name = safe_name
        counter = 1
        while sheet_name.lower() in [s.lower() for s in used_sheet_names]:
            sheet_name = f"{safe_name[:25]}_{counter}"
            counter += 1
        used_sheet_names.add(sheet_name)

        ws_ev = wb.create_sheet(title=sheet_name)
        ws_ev['A1'] = f"{ev_title.upper()} - PAYMENT LEDGER"
        ws_ev['A1'].font = title_font
        ws_ev['A2'] = f"Fee: ₱{fee:.2f} | Deadline: {ev.get('deadline') or 'N/A'}"
        ws_ev['A2'].font = Font(name="Arial", size=9, italic=True, color="64748B")

        ev_headers = ['No.', 'Student ID', 'Full Name', 'Course', 'Year', 'Target (₱)', 'Amount Paid (₱)', 'Balance (₱)', 'Status', 'Confirmed Date', 'Confirmed By']
        for c_idx, h in enumerate(ev_headers, 1):
            c = ws_ev.cell(row=4, column=c_idx, value=h)
            c.fill = navy_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center" if c_idx in (1, 4, 5, 9) else ("right" if c_idx in (6, 7, 8) else "left"))

        for s_idx, s in enumerate(students, 1):
            p = pmts.get(s['_id'])
            p_paid = float(p.get('amount_paid', 0)) if p else 0.0
            p_bal = max(0.0, fee - p_paid)
            if p and p.get('locked'):
                p_status = 'Fully Paid'
            elif p_paid > 0:
                p_status = 'Partial'
            else:
                p_status = 'Pending'

            r_idx = 4 + s_idx
            ws_ev.cell(row=r_idx, column=1, value=s_idx).alignment = Alignment(horizontal="center")
            ws_ev.cell(row=r_idx, column=2, value=s.get('student_id', '')).alignment = Alignment(horizontal="center")
            ws_ev.cell(row=r_idx, column=3, value=s.get('name', ''))
            ws_ev.cell(row=r_idx, column=4, value=s.get('course', '')).alignment = Alignment(horizontal="center")
            ws_ev.cell(row=r_idx, column=5, value=s.get('year', '')).alignment = Alignment(horizontal="center")
            
            ws_ev.cell(row=r_idx, column=6, value=fee).number_format = '₱#,##0.00'
            ws_ev.cell(row=r_idx, column=7, value=p_paid).number_format = '₱#,##0.00'
            ws_ev.cell(row=r_idx, column=8, value=p_bal).number_format = '₱#,##0.00'
            
            c_stat = ws_ev.cell(row=r_idx, column=9, value=p_status)
            c_stat.alignment = Alignment(horizontal="center")
            if p_status == 'Fully Paid':
                c_stat.font = Font(name="Arial", size=10, bold=True, color="059669")
            elif p_status == 'Partial':
                c_stat.font = Font(name="Arial", size=10, bold=True, color="D97706")
            else:
                c_stat.font = Font(name="Arial", size=10, color="94A3B8")

            c_date = p.get('confirmed_at').strftime('%Y-%m-%d %H:%M') if p and p.get('confirmed_at') else ''
            c_user = user_map.get(p.get('confirmed_by'), '') if p else ''
            ws_ev.cell(row=r_idx, column=10, value=c_date)
            ws_ev.cell(row=r_idx, column=11, value=c_user)

            for c in range(1, 12):
                ws_ev.cell(row=r_idx, column=c).border = thin_border

        # Event sheet totals
        tot_row = 5 + len(students)
        ws_ev.cell(row=tot_row, column=3, value="TOTALS").font = bold_font
        ws_ev.cell(row=tot_row, column=6, value=f"=SUM(F5:F{tot_row-1})").number_format = '₱#,##0.00'
        ws_ev.cell(row=tot_row, column=7, value=f"=SUM(G5:G{tot_row-1})").number_format = '₱#,##0.00'
        ws_ev.cell(row=tot_row, column=8, value=f"=SUM(H5:H{tot_row-1})").number_format = '₱#,##0.00'
        for c in (3, 6, 7, 8):
            ws_ev.cell(row=tot_row, column=c).font = bold_font

        for col in ws_ev.columns:
            m_len = max(len(str(cell.value or '')) for cell in col)
            ws_ev.column_dimensions[get_column_letter(col[0].column)].width = max(m_len + 3, 11)

    # Adjust Overview column widths
    for col in ws_ov.columns:
        m_len = max(len(str(cell.value or '')) for cell in col)
        ws_ov.column_dimensions[get_column_letter(col[0].column)].width = max(m_len + 3, 11)

    mem = io.BytesIO()
    wb.save(mem)
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f'all_events_treasury_{date.today().isoformat()}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_app.py::test_export_all_events_excel tests/test_app.py::test_event_print_form`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/events.py templates/event_print.html tests/test_app.py
git commit -m "feat: add multi-sheet Excel master workbook and printable table form view"
```

---

### Task 3: Date-Range Filtered & Student Ledger Report Exports

**Files:**
- Modify: `app/reports.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `db.transactions`, `db.payments`, `db.students`
- Produces:
  - Route: `GET /export?start=YYYY-MM-DD&end=YYYY-MM-DD` -> Filtered CSV
  - Route: `GET /export_students` -> Student balances CSV

- [ ] **Step 1: Write failing tests for filtered and student exports**

Add to `tests/test_app.py`:
```python
def test_export_filtered_date_range(client, db):
    login(client, db, 'admin')
    # Insert transactions at different dates
    db.transactions.insert_one({
        '_id': 401, 'type': 'income', 'amount': 500.0, 'description': 'Sponsor Donation',
        'transaction_date': '2026-05-15', 'deleted': False
    })
    db.transactions.insert_one({
        '_id': 402, 'type': 'expense', 'amount': 150.0, 'description': 'Class Supplies',
        'transaction_date': '2026-09-05', 'deleted': False
    })

    resp = client.get('/export?start=2026-09-01&end=2026-09-30')
    assert resp.status_code == 200
    csv_text = resp.get_data(as_text=True)
    assert 'Class Supplies' in csv_text
    assert 'Sponsor Donation' not in csv_text


def test_export_students_csv(client, db):
    login(client, db, 'admin')
    db.students.insert_one({
        '_id': 501, 'student_id': 'STU-999', 'name': 'Abalos, Grace', 'course': 'BSCS',
        'is_active': 1, 'deleted': False
    })
    db.transactions.insert_one({
        '_id': 502, 'type': 'income', 'amount': 200.0, 'student_id': 501, 'deleted': False
    })

    resp = client.get('/export_students')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers.get('Content-Type', '')
    csv_text = resp.get_data(as_text=True)
    assert 'STU-999' in csv_text
    assert 'Abalos, Grace' in csv_text
    assert '200.00' in csv_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py::test_export_filtered_date_range tests/test_app.py::test_export_students_csv`  
Expected: FAIL with missing route or unconsumed date filter.

- [ ] **Step 3: Update `app/reports.py` to support date filter and student export**

In `app/reports.py`:
Update `export()`:
```python
@bp.route('/export')
@login_required
def export():
    start = request.args.get('start')
    end = request.args.get('end')

    match_cond = {'description': {'$not': {'$regex': '^Payment:'}}, 'deleted': {'$ne': True}}
    if start and end:
        match_cond['transaction_date'] = {'$gte': start, '$lte': end}
    elif start:
        match_cond['transaction_date'] = {'$gte': start}
    elif end:
        match_cond['transaction_date'] = {'$lte': end}

    txn = list(db.transactions.aggregate([
        {'$match': match_cond},
        {'$sort': {'transaction_date': 1}},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'description': 1, 'reference': 1, 'payment_method': 1, 'student': '$student.name'}}
    ]))
    txn.extend(get_confirmed_payment_rows(start=start, end=end))
    txn.sort(key=lambda row: row.get('transaction_date', '') or '')

    import csv
    import io
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['Date', 'Type', 'Student', 'Amount (PHP)', 'Description', 'Reference', 'Payment Method'])
    for r in txn:
        amt = float(r.get('amount', 0) or 0)
        w.writerow([r.get('transaction_date', ''), r.get('type', ''), r.get('student', '') or '', f"{amt:.2f}", r.get('description', '') or '', r.get('reference', '') or '', r.get('payment_method', '')])
    
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    filename = f"treasury_report_{start}_to_{end}.csv" if start and end else f"treasury_report_{date.today().isoformat()}.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype='text/csv')


@bp.route('/export_students')
@login_required
def export_students():
    data = list(db.students.aggregate([
        {'$match': {'is_active': 1, 'deleted': {'$ne': True}}},
        {'$lookup': {'from': 'transactions', 'let': {'sid': '$_id'},
                     'pipeline': [
                         {'$match': {'$expr': {'$eq': ['$student_id', '$$sid']}, 'deleted': {'$ne': True}}},
                     ], 'as': 'txns'}},
        {'$project': {'student_id': 1, 'name': 1, 'course': 1,
                      'total_paid': {'$sum': {'$cond': [{'$eq': ['$txns.type', 'income']}, '$txns.amount', 0]}},
                      'total_used': {'$sum': {'$cond': [{'$eq': ['$txns.type', 'expense']}, '$txns.amount', 0]}}}},
        {'$sort': {'name': 1}}
    ]))
    paid_by_student = {
        row['_id']: row['total']
        for row in db.payments.aggregate([
            {'$match': {'confirmed': True}},
            {'$group': {'_id': '$student_id', 'total': {'$sum': '$amount_paid'}}}
        ])
    }
    for row in data:
        row['total_paid'] = float(row.get('total_paid', 0) + paid_by_student.get(row['_id'], 0))
        row['total_used'] = float(row.get('total_used', 0))
        row['net_balance'] = row['total_paid'] - row['total_used']

    import csv
    import io
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['STUDENT TREASURY BALANCES & CONTRIBUTIONS'])
    w.writerow(['Generated Date', date.today().isoformat()])
    w.writerow([])
    w.writerow(['Student ID', 'Full Name', 'Course', 'Total Paid (PHP)', 'Total Used (PHP)', 'Net Balance (PHP)'])
    for d in data:
        w.writerow([
            d.get('student_id', ''),
            d.get('name', ''),
            d.get('course', '') or '—',
            f"{d['total_paid']:.2f}",
            f"{d['total_used']:.2f}",
            f"{d['net_balance']:.2f}"
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f'student_treasury_balances_{date.today().isoformat()}.csv', mimetype='text/csv')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py::test_export_filtered_date_range tests/test_app.py::test_export_students_csv`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/reports.py tests/test_app.py
git commit -m "feat: add date-range filtered export and per-student balance export"
```

---

### Task 4: "Where the Money Has Gone" Dashboard Category Breakdown & UI Views

**Files:**
- Modify: `app/dashboard.py`
- Modify: `templates/dashboard.html`
- Modify: `templates/reports.html`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `db.transactions` (expenses), `get_financial_totals`
- Produces: `disbursement_categories` in dashboard context and interactive category visual cards in HTML.

- [ ] **Step 1: Write test verifying dashboard passes disbursement categories**

Add to `tests/test_app.py`:
```python
def test_dashboard_disbursement_categories(client, db):
    login(client, db, 'admin')
    db.transactions.insert_one({
        '_id': 601, 'type': 'expense', 'amount': 450.0, 'description': 'Paper and printer ink',
        'deleted': False
    })
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Where the Money Has Gone' in html or 'Disbursement Categories' in html
    assert 'Supplies &amp; Materials' in html or 'Supplies' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py::test_dashboard_disbursement_categories`  
Expected: FAIL (card not rendered on dashboard).

- [ ] **Step 3: Update `app/dashboard.py` to calculate disbursement categories**

In `app/dashboard.py`, before the return in `index()`:
```python
    # Dynamic outflow category aggregation
    all_expenses = list(db.transactions.find({'type': 'expense', 'deleted': {'$ne': True}}))
    cat_totals = {
        'Student Refunds & Adjustments': 0.0,
        'Platform & System Services': 0.0,
        'Event Remittances & Programs': 0.0,
        'Supplies & Materials': 0.0,
        'Operations & Miscellaneous': 0.0,
    }
    for e in all_expenses:
        desc = (e.get('description') or '').lower()
        amt = float(e.get('amount', 0) or 0)
        if 'refund' in desc or 'correction' in desc:
            cat = 'Student Refunds & Adjustments'
        elif any(k in desc for k in ('uniscan', 'system', 'software', 'platform', 'online')):
            cat = 'Platform & System Services'
        elif any(k in desc for k in ('freshface', 'acquaintance', 'event', 'party', 'activity')):
            cat = 'Event Remittances & Programs'
        elif any(k in desc for k in ('supplies', 'printing', 'ink', 'paper', 'materials')):
            cat = 'Supplies & Materials'
        else:
            cat = 'Operations & Miscellaneous'
        cat_totals[cat] += amt

    disbursement_categories = [
        {'name': k, 'amount': v, 'pct': (v / expense * 100) if expense > 0 else 0}
        for k, v in cat_totals.items() if v > 0
    ]
    disbursement_categories.sort(key=lambda x: -x['amount'])
```
Pass `disbursement_categories=disbursement_categories` to `render_template()`.

- [ ] **Step 4: Update `templates/dashboard.html` to render the Outflow Category card**

Insert under the Quick Action cards in `templates/dashboard.html`:
```html
<div class="card-modern mb-4 animate-in" style="animation-delay:.42s">
    <div class="card-header-modern d-flex justify-content-between align-items-center">
        <span><i class="bi bi-pie-chart-fill" style="color:var(--danger)"></i> Where the Money Has Gone (Disbursement Breakdown)</span>
        <a href="{{ url_for('reports.index', type='transparency') }}" class="btn btn-modern-outline btn-modern-sm"><i class="bi bi-eye"></i> View Full Audit</a>
    </div>
    <div class="card-body-modern">
        <div class="row g-3 align-items-center">
            {% for c in disbursement_categories %}
            <div class="col-md-6 col-lg-4">
                <div class="p-3 border rounded-3" style="background:var(--surface-hover);border-color:var(--border-color)!important;">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span style="font-size:0.8rem;font-weight:600;color:var(--text-secondary);">{{ c.name }}</span>
                        <strong style="font-size:0.85rem;color:var(--danger);">₱{{ "%.2f"|format(c.amount) }}</strong>
                    </div>
                    <div class="progress-modern" style="height:6px;">
                        <div class="progress-bar-modern" style="width:{{ c.pct }}%;background:{% if 'Refund' in c.name %}#f59e0b{% elif 'Platform' in c.name %}#3b82f6{% elif 'Event' in c.name %}#10b981{% elif 'Supplies' in c.name %}#8b5cf6{% else %}#ef4444{% endif %};"></div>
                    </div>
                    <div class="d-flex justify-content-between mt-1" style="font-size:0.7rem;color:var(--text-muted);">
                        <span>Share of total outflows</span>
                        <span>{{ "%.1f"|format(c.pct) }}%</span>
                    </div>
                </div>
            </div>
            {% endfor %}
            {% if not disbursement_categories %}
            <div class="col-12 py-3 text-center text-muted">
                <i class="bi bi-shield-check fs-4 d-block mb-1 text-success"></i>
                No disbursements recorded yet. All treasury inflows are currently in balance.
            </div>
            {% endif %}
        </div>
    </div>
</div>
```

- [ ] **Step 5: Run tests to verify it passes**

Run: `pytest tests/test_app.py::test_dashboard_disbursement_categories`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboard.py templates/dashboard.html tests/test_app.py
git commit -m "feat: display where money went category breakdown on dashboard"
```

---

### Task 5: UI Bug Fixes - Navigation States, Batch Payment Selection & Theme Contrast

**Files:**
- Modify: `templates/base.html`
- Modify: `templates/events.html`
- Modify: `templates/payments.html`
- Modify: `templates/reports.html`

- [ ] **Step 1: Fix navigation active link matching in `templates/base.html`**

In `templates/base.html`:
Replace:
```html
<a class="nav-link {% if request.endpoint == 'dashboard' %}active{% endif %}" href="{{ url_for('dashboard.index') }}">
...
<a class="nav-link {% if request.endpoint == 'transactions' %}active{% endif %}" href="{{ url_for('transactions.index') }}">
<a class="nav-link {% if request.endpoint == 'students' %}active{% endif %}" href="{{ url_for('students.index') }}">
<a class="nav-link {% if request.endpoint == 'payments' %}active{% endif %}" href="{{ url_for('payments.index') }}">
<a class="nav-link {% if request.endpoint == 'events' %}active{% endif %}" href="{{ url_for('events.index') }}">
<a class="nav-link {% if request.endpoint == 'reports' and request.args.get('type') != 'transparency' %}active{% endif %}" href="{{ url_for('reports.index') }}">
<a class="nav-link {% if request.endpoint == 'reports' and request.args.get('type') == 'transparency' %}active{% endif %}" href="{{ url_for('reports.index', type='transparency') }}">
<a class="nav-link {% if request.endpoint == 'export' %}active{% endif %}" href="{{ url_for('reports.export') }}">
<a class="nav-link {% if request.endpoint == 'users' %}active{% endif %}" href="{{ url_for('admin.users') }}">
```
With robust prefix checks:
```html
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('dashboard') %}active{% endif %}" href="{{ url_for('dashboard.index') }}">
...
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('transactions') %}active{% endif %}" href="{{ url_for('transactions.index') }}">
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('students') %}active{% endif %}" href="{{ url_for('students.index') }}">
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('payments') %}active{% endif %}" href="{{ url_for('payments.index') }}">
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('events') %}active{% endif %}" href="{{ url_for('events.index') }}">
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('reports') and request.args.get('type') != 'transparency' %}active{% endif %}" href="{{ url_for('reports.index') }}">
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('reports') and request.args.get('type') == 'transparency' %}active{% endif %}" href="{{ url_for('reports.index', type='transparency') }}">
<a class="nav-link {% if request.endpoint == 'reports.export' %}active{% endif %}" href="{{ url_for('reports.export') }}">
<a class="nav-link {% if request.endpoint and request.endpoint.startswith('admin') %}active{% endif %}" href="{{ url_for('admin.users') }}">
```
Apply the same prefix checks for mobile bottom nav links (`dashboard`, `payments`, `events`, `students`, `reports`).

- [ ] **Step 2: Add Export buttons to `templates/events.html`**

In `templates/events.html`:
Add header button:
```html
<a href="{{ url_for('events.export_all_excel') }}" class="btn btn-modern-outline btn-modern-sm" title="Export All Events to Multi-Sheet Excel">
    <i class="bi bi-file-earmark-spreadsheet text-success"></i> Master Excel (All Events)
</a>
```
On each event card:
Add an export dropdown button:
```html
<div class="dropdown d-inline">
    <button class="btn btn-modern-outline btn-modern-sm dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false" title="Export Event Payments">
        <i class="bi bi-download"></i> Export
    </button>
    <ul class="dropdown-menu dropdown-menu-end shadow-sm" style="font-size:0.85rem;">
        <li><a class="dropdown-item" href="{{ url_for('events.export_csv', id=e._id) }}"><i class="bi bi-filetype-csv text-primary me-2"></i>Export CSV</a></li>
        <li><a class="dropdown-item" href="{{ url_for('events.export_excel', id=e._id) }}"><i class="bi bi-file-earmark-excel text-success me-2"></i>Export Excel (.xlsx)</a></li>
        <li><hr class="dropdown-divider"></li>
        <li><a class="dropdown-item" href="{{ url_for('events.print_roster', id=e._id) }}" target="_blank"><i class="bi bi-printer text-dark me-2"></i>Print / Save PDF Form</a></li>
    </ul>
</div>
```

- [ ] **Step 3: Enhance `templates/payments.html` with Batch Payment Selection & Direct Export**

In `templates/payments.html`:
When an event is selected, add in header:
```html
<div class="d-flex gap-2 align-items-center">
    <div class="dropdown">
        <button class="btn btn-modern-outline btn-modern-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
            <i class="bi bi-download"></i> Export Event
        </button>
        <ul class="dropdown-menu dropdown-menu-end">
            <li><a class="dropdown-item" href="{{ url_for('events.export_csv', id=event._id) }}"><i class="bi bi-filetype-csv text-primary me-2"></i>CSV Roster</a></li>
            <li><a class="dropdown-item" href="{{ url_for('events.export_excel', id=event._id) }}"><i class="bi bi-file-earmark-excel text-success me-2"></i>Excel (.xlsx)</a></li>
            <li><a class="dropdown-item" href="{{ url_for('events.print_roster', id=event._id) }}" target="_blank"><i class="bi bi-printer me-2"></i>Print / PDF Form</a></li>
        </ul>
    </div>
</div>
```
Add "Select All Pending" and "Fill Target" script and control buttons in the table header of `payments.html`.

- [ ] **Step 4: Update `templates/reports.html` with context-aware exports**

In `templates/reports.html`:
Update the export button group:
- In `student` tab: add `<a href="{{ url_for('reports.export_students') }}" class="btn btn-modern-sm btn-outline-primary"><i class="bi bi-file-earmark-person"></i> Export Student Balances</a>`
- In `date_range` tab: add `<a href="{{ url_for('reports.export', start=start, end=end) }}" class="btn btn-modern-sm btn-modern-primary"><i class="bi bi-funnel"></i> Export Filtered CSV</a>`
- Add master multi-sheet Excel button: `<a href="{{ url_for('events.export_all_excel') }}" class="btn btn-modern-sm btn-outline-success"><i class="bi bi-file-earmark-spreadsheet"></i> Master Events Excel</a>`

- [ ] **Step 5: Run pytest suite to verify all routes and templates render cleanly**

Run: `pytest`  
Expected: PASS (100% passing)

- [ ] **Step 6: Commit**

```bash
git add templates/base.html templates/events.html templates/payments.html templates/reports.html
git commit -m "fix(ui): repair navigation active states, add batch payment shortcuts and report export buttons"
```

---

### Task 6: Final Verification & Standards Check

**Files:**
- Entire codebase
- Tests: `tests/test_app.py`

- [ ] **Step 1: Execute full test suite**

Run: `pytest -v`  
Expected: All tests PASS with zero errors.

- [ ] **Step 2: Verify zero database changes**

Confirm no migrations, scripts, or schema alterations exist in git status.

- [ ] **Step 3: Run git diff and status verification**

Run: `git status`  
Expected: Clean working tree on committed changes.
