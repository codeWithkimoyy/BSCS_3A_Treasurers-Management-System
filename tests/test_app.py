import io
import re
from datetime import datetime

import openpyxl


def test_login_page_renders(client):
    resp = client.get('/login')
    assert resp.status_code == 200
    assert 'login' in resp.get_data(as_text=True).lower()


def test_protected_route_redirects_anonymous(client):
    resp = client.get('/students', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_csrf_blocks_post_without_token(client, db):
    _make_user(db, 'admin', 'admin')
    login(client, db, 'admin')
    # POST without CSRF token -> 403
    resp = client.post('/students/add', data={'student_id': 'S1', 'name': 'John Doe'}, follow_redirects=False)
    assert resp.status_code == 403


def test_staff_cannot_view_users(client, db):
    login(client, db, 'staff')
    resp = client.get('/users', follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'] != '/login'


def test_admin_can_view_users(client, db):
    login(client, db, 'admin')
    resp = client.get('/users')
    assert resp.status_code == 200


def test_staff_cannot_add_event(client, db):
    login(client, db, 'staff')
    token = _csrf(client)
    resp = client.post('/events/add', data={'title': 'X', 'amount': '100'}, follow_redirects=False)
    # role_required redirects (unauthenticated role) -> not /login, no event created
    assert resp.status_code == 302
    assert resp.headers['Location'] != '/login'
    assert db.events.count_documents({}) == 0


def test_admin_can_add_event(client, db):
    login(client, db, 'admin')
    token = _csrf(client)
    resp = client.post('/events/add', data={'title': 'Fundraiser', 'amount': '150', '_csrf_token': token},
                      follow_redirects=False)
    assert resp.status_code == 302
    assert db.events.count_documents({'title': 'Fundraiser'}) == 1


def test_student_soft_delete(client, db):
    login(client, db, 'admin')
    token = _csrf(client)
    client.post('/students/add', data={'student_id': 'S42', 'name': 'Jane Roe', '_csrf_token': token},
                follow_redirects=False)
    sid = db.students.find_one({'student_id': 'S42'})['_id']
    client.post(f'/students/delete/{sid}', data={'_csrf_token': token}, follow_redirects=False)
    doc = db.students.find_one({'_id': sid})
    assert doc['deleted'] is True
    # soft-deleted student excluded from listings
    assert db.students.count_documents({'deleted': {'$ne': True}, 'student_id': 'S42'}) == 0


def test_transparency_report_renders(client, db):
    login(client, db, 'admin')
    # Insert an expense transaction
    db.transactions.insert_one({
        '_id': 999,
        'type': 'expense',
        'amount': 330.0,
        'description': 'UniScan Payment',
        'reference': 'RCP-TEST-001',
        'payment_method': 'cash',
        'transaction_date': '2026-08-01',
        'deleted': False,
    })
    resp = client.get('/reports?type=transparency')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Transparency &amp; Disbursements' in html or 'Transparency' in html
    assert 'UniScan Payment' in html
    assert 'Where the Money Went' in html


def test_export_liquidation_csv(client, db):
    login(client, db, 'admin')
    resp = client.get('/export_liquidation')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers.get('Content-Type', '')
    assert 'liquidation_report_' in resp.headers.get('Content-Disposition', '')
    csv_text = resp.get_data(as_text=True)
    assert 'CLASS TREASURY FINANCIAL LIQUIDATION & TRANSPARENCY REPORT' in csv_text


def test_export_event_csv(client, db):
    login(client, db, 'admin')
    ev_id = 101
    db.events.insert_one({
        '_id': ev_id,
        'title': 'Test Gala',
        'amount': 250.0,
        'deadline': '2026-10-01',
        'status': 'active',
    })
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
    assert 'event_' in resp.headers.get('Content-Disposition', '')


def test_export_all_events_excel(client, db):
    login(client, db, 'admin')
    db.events.insert_one({'_id': 110, 'title': 'Sinking Fund', 'amount': 100.0, 'status': 'active'})
    db.events.insert_one({'_id': 111, 'title': 'Acquaintance Party', 'amount': 300.0, 'status': 'active'})
    db.students.insert_one({'_id': 210, 'student_id': 'STU-010', 'name': 'Santos, Pedro', 'is_active': 1, 'deleted': False})

    resp = client.get('/events/export_all_excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers.get('Content-Type', '')
    assert 'all_events_' in resp.headers.get('Content-Disposition', '')

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


def test_export_filtered_date_range(client, db):
    login(client, db, 'admin')
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
    assert 'Supplies' in html


def test_transaction_add_with_others_payee(client, db):
    login(client, db, 'admin')
    token = _csrf(client)
    resp = client.post('/transactions/add', data={
        '_csrf_token': token,
        'type': 'expense',
        'amount': '350.00',
        'recipient_type': 'others',
        'payee': 'Hardware Supply Co.',
        'description': 'Door hinge repair',
        'payment_method': 'cash'
    }, follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Hardware Supply Co.' in html


def _make_user(db, username, role, password='secret123'):
    from werkzeug.security import generate_password_hash
    db.users.insert_one({
        '_id': db.counters.find_one_and_update({'_id': 'users'}, {'$inc': {'seq': 1}}, upsert=True, return_document=True)['seq'],
        'username': username, 'password': generate_password_hash(password), 'role': role,
        'created_at': __import__('datetime').datetime.now(),
    })
    return username, password


def login(client, db, role):
    username, password = _make_user(db, f'{role}_user', role)
    resp = client.get('/login')
    m = re.search(r'name="_csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    token = m.group(1) if m else ''
    r = client.post('/login', data={'username': username, 'password': password, '_csrf_token': token}, follow_redirects=False)
    return client


def _csrf(client):
    resp = client.get('/students')
    m = re.search(r'name="_csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    return m.group(1) if m else ''
