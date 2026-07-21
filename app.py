import os
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from dotenv import load_dotenv, set_key
import io
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
import secrets
from pathlib import Path

ENV_PATH = Path(__file__).parent / '.env'
load_dotenv(ENV_PATH)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(24).hex()
app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/student_treasury')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', '')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

os.makedirs(app.instance_path, exist_ok=True)

client = MongoClient(app.config['MONGO_URI'], serverSelectionTimeoutMS=10000, tls=True, tlsInsecure=True)
db = client.get_database()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

plt.rcParams['font.family'] = 'sans-serif'

ROLES = ['admin', 'mayor', 'treasurer', 'staff']

def can_override():
    return current_user.role in ['admin', 'mayor', 'treasurer']

def can_manage_data():
    return current_user.role in ['admin', 'mayor', 'treasurer']

def next_id(collection_name):
    result = db.counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=True
    )
    return result['seq']

def init_db():
    if 'users' not in db.list_collection_names():
        db.users.create_index('username', unique=True)
    if 'students' not in db.list_collection_names():
        db.students.create_index('student_id', unique=True)
    if 'counters' not in db.list_collection_names():
        for c in ['users', 'students', 'transactions', 'events', 'payments']:
            db.counters.insert_one({'_id': c, 'seq': 1})

    if db.users.count_documents({}) == 0:
        db.users.insert_one({
            '_id': next_id('users'),
            'username': 'admin',
            'password': generate_password_hash('admin123'),
            'role': 'admin',
            'created_at': datetime.now()
        })

def get_chart_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=80)
    buf.seek(0)
    data = base64.b64encode(buf.getvalue()).decode()
    plt.close(fig)
    return data

ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def logo_file():
    for extension in ALLOWED_LOGO_EXTENSIONS:
        candidate = Path(app.instance_path) / f'app_logo.{extension}'
        if candidate.exists():
            return candidate
    return None

def get_financial_totals():
    """Return canonical totals without counting payment ledger rows twice."""
    confirmed_payments = list(db.payments.aggregate([
        {'$match': {'confirmed': True}},
        {'$group': {'_id': None, 'total': {'$sum': '$amount_paid'}}}
    ]))
    manual_income = list(db.transactions.aggregate([
        {'$match': {
            'type': 'income',
            '$or': [
                {'description': {'$exists': False}},
                {'description': {'$not': {'$regex': '^Payment:'}}}
            ]
        }},
        {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
    ]))
    expenses = list(db.transactions.aggregate([
        {'$match': {'type': 'expense'}},
        {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
    ]))
    income = (confirmed_payments[0]['total'] if confirmed_payments else 0) + \
        (manual_income[0]['total'] if manual_income else 0)
    expense = expenses[0]['total'] if expenses else 0
    return income, expense

def get_confirmed_payment_rows(start=None, end=None):
    """Return confirmed payments in the same shape used by ledger reports."""
    match = {'confirmed': True}
    if start:
        match['confirmed_at'] = {'$gte': datetime.fromisoformat(start)}
    if end:
        match.setdefault('confirmed_at', {})['$lt'] = datetime.fromisoformat(end) + timedelta(days=1)
    return list(db.payments.aggregate([
        {'$match': match},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$lookup': {'from': 'events', 'localField': 'event_id', 'foreignField': '_id', 'as': 'event'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$unwind': {'path': '$event', 'preserveNullAndEmptyArrays': True}},
        {'$project': {
            '_id': 1, 'student_id': 1, 'amount': '$amount_paid', 'notes': 1, 'confirmed_at': 1,
            'transaction_date': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$confirmed_at'}},
            'type': {'$literal': 'income'},
            'description': {'$concat': ['Payment: ', '$event.title']},
            'student': '$student.name', 'student_name': '$student.name', 'event_title': '$event.title',
            'payment_method': {'$literal': 'event payment'}
        }}
    ]))

class User(UserMixin):
    def __init__(self, id, username, role, display_name=None, email=None, picture=None):
        self.id = id
        self.username = username
        self.role = role
        self.display_name = display_name or username
        self.email = email
        self.picture = picture

@login_manager.user_loader
def load_user(user_id):
    user = db.users.find_one({'_id': int(user_id)})
    if user:
        return User(user['_id'], user['username'], user['role'], user.get('display_name'), user.get('google_email'), user.get('picture'))
    return None

@app.context_processor
def inject_now():
    return {'now': datetime.now(), 'current_year': datetime.now().year, 'can_override': can_override, 'can_manage_data': can_manage_data, 'google_cid': app.config['GOOGLE_CLIENT_ID'], 'has_logo': logo_file() is not None}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.users.find_one({'username': request.form['username']})
        if user and check_password_hash(user['password'], request.form['password']):
            login_user(User(user['_id'], user['username'], user['role'], user.get('display_name'), user.get('google_email'), user.get('picture')))
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/login/google', methods=['POST'])
def google_login():
    if not app.config['GOOGLE_CLIENT_ID']:
        return jsonify({'error': 'Google not configured'}), 400
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_req
        data = request.get_json()
        token = data.get('credential')
        if not token:
            return jsonify({'error': 'No token'}), 400
        info = google_id_token.verify_oauth2_token(token, google_req.Request(), app.config['GOOGLE_CLIENT_ID'])
        email = info.get('email', '')
        if not email:
            return jsonify({'error': 'No email from Google'}), 400
        if not email.endswith('@bisu.edu.ph'):
            return jsonify({'error': 'Only @bisu.edu.ph emails allowed'}), 403
        user = db.users.find_one({'username': email})
        if not user:
            user = db.users.find_one({'google_email': email})
        if not user:
            base_username = email.split('@')[0]
            username = base_username
            i = 1
            while db.users.find_one({'username': username}):
                username = f"{base_username}{i}"
                i += 1
            user_id = next_id('users')
            db.users.insert_one({
                '_id': user_id,
                'username': username,
                'password': generate_password_hash(secrets.token_hex(32)),
                'google_email': email,
                'display_name': info.get('name') or email.split('@')[0],
                'picture': info.get('picture', ''),
                'role': 'staff',
                'created_at': datetime.now()
            })
            user = db.users.find_one({'_id': user_id})
        else:
            # Keep the local profile synchronized with the latest Google name
            # and avatar without replacing locally managed username or role.
            db.users.update_one({'_id': user['_id']}, {'$set': {
                'google_email': email,
                'display_name': info.get('name') or user.get('display_name') or user['username'],
                'picture': info.get('picture', user.get('picture', ''))
            }})
            user = db.users.find_one({'_id': user['_id']})
        login_user(User(user['_id'], user['username'], user['role'], user.get('display_name'), user.get('google_email'), user.get('picture')))
        return jsonify({'ok': True, 'redirect': url_for('dashboard')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    # Confirmed payments are the source of truth for money collected. Older
    # records may exist in `payments` without a matching `transactions` row,
    # so calculating income from transactions alone makes the dashboard show
    # zero even when payments have already been confirmed. Payment-generated
    # transaction rows are excluded here to avoid counting them twice.
    income, expense = get_financial_totals()
    balance = income - expense
    member_count = db.students.count_documents({'is_active': 1})
    event_count = db.events.count_documents({'status': 'active'})
    pending_payments = db.payments.count_documents({'confirmed': False})

    recent = list(db.transactions.aggregate([
        {'$sort': {'created_at': -1}}, {'$limit': 5},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'student_name': '$student.name'}}
    ]))

    recent_payments = list(db.payments.aggregate([
        {'$match': {'confirmed': True}},
        {'$sort': {'confirmed_at': -1}}, {'$limit': 10},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$lookup': {'from': 'events', 'localField': 'event_id', 'foreignField': '_id', 'as': 'event'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$unwind': {'path': '$event', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'amount': '$amount_paid', 'confirmed_at': 1, 'notes': 1, 'student_name': '$student.name', 'event_title': '$event.title'}}
    ]))

    six_months_ago = datetime.now()
    try: six_months_ago = six_months_ago.replace(month=six_months_ago.month - 6)
    except ValueError: six_months_ago = six_months_ago.replace(year=six_months_ago.year - 1, month=six_months_ago.month + 6)
    last_6 = list(db.transactions.aggregate([
        {'$match': {'transaction_date': {'$gte': six_months_ago.strftime('%Y-%m-%d')}}},
        {'$group': {'_id': {'$substr': ['$transaction_date', 0, 7]}, 'inc': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}}, 'exp': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}}},
        {'$sort': {'_id': 1}}, {'$project': {'mon': '$_id', 'inc': 1, 'exp': 1, '_id': 0}}
    ]))

    # Include confirmed payments in the trend even when a legacy payment has
    # no corresponding transaction document.
    payment_months = list(db.payments.aggregate([
        {'$match': {'confirmed': True, 'confirmed_at': {'$gte': six_months_ago}}},
        {'$group': {
            '_id': {'$dateToString': {'format': '%Y-%m', 'date': '$confirmed_at'}},
            'inc': {'$sum': '$amount_paid'}
        }},
        {'$project': {'_id': 0, 'mon': '$_id', 'inc': 1}}
    ]))
    monthly = {r['mon']: {'inc': r.get('inc', 0), 'exp': r.get('exp', 0)} for r in last_6}
    for payment_month in payment_months:
        monthly.setdefault(payment_month['mon'], {'inc': 0, 'exp': 0})
        monthly[payment_month['mon']]['inc'] += payment_month.get('inc', 0)
    trend_data = [
        {'mon': month, **monthly[month]}
        for month in sorted(monthly)
    ]
    months = [r['mon'] for r in trend_data]
    fig2, ax = plt.subplots(figsize=(8, 2.8))
    fig2.patch.set_facecolor('#f8f9fa')
    x = range(len(months))
    ax.bar(x, [r['inc'] for r in trend_data], width=0.35, label='Income', color='#28a745', alpha=0.8)
    ax.bar([i+0.35 for i in x], [r['exp'] for r in trend_data], width=0.35, label='Expense', color='#dc3545', alpha=0.8)
    ax.set_xticks([i+0.175 for i in x])
    ax.set_xticklabels(months, rotation=45, ha='right', fontsize=9)
    ax.legend(fontsize=9); ax.set_ylabel('Amount (PHP)', fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'₱{x:,.0f}'))
    trend_chart = get_chart_base64(fig2) if trend_data else None

    chart = None
    if income or expense:
        fig1, ax1 = plt.subplots(figsize=(7, 3.6))
        labels = [f'Income  ₱{income:,.2f}', f'Expenses  ₱{expense:,.2f}']
        ax1.pie(
            [income, expense],
            labels=labels,
            colors=['#28a745', '#dc3545'],
            autopct=lambda value: f'{value:.1f}%' if value else '',
            startangle=90,
            pctdistance=0.78,
            textprops={'fontsize': 9},
            wedgeprops={'width': 0.45, 'edgecolor': '#ffffff'}
        )
        ax1.set_title('Income vs Expense', fontsize=11, fontweight='bold', pad=10)
        chart = get_chart_base64(fig1)

    return render_template('dashboard.html', income=income, expense=expense, balance=balance,
        member_count=member_count, event_count=event_count, pending_payments=pending_payments,
        recent=recent, chart=chart, trend_chart=trend_chart, recent_payments=recent_payments)

@app.route('/events')
@login_required
def events():
    evts = list(db.events.find().sort('created_at', -1))
    for e in evts:
        total_paid = list(db.payments.aggregate([
            {'$match': {'event_id': e['_id'], 'confirmed': True}},
            {'$group': {'_id': None, 'total': {'$sum': '$amount_paid'}}}
        ]))
        total_students = db.students.count_documents({'is_active': 1})
        paid_count = db.payments.count_documents({'event_id': e['_id'], 'confirmed': True})
        e['collected'] = total_paid[0]['total'] if total_paid else 0
        e['paid_count'] = paid_count
        e['total_students'] = total_students
    return render_template('events.html', events=evts)

@app.route('/events/add', methods=['POST'])
@login_required
def add_event():
    db.events.insert_one({
        '_id': next_id('events'),
        'title': request.form['title'],
        'amount': float(request.form['amount']),
        'deadline': request.form.get('deadline', ''),
        'status': 'active',
        'created_by': current_user.id,
        'created_at': datetime.now()
    })
    flash('Event created', 'success')
    return redirect(url_for('events'))

@app.route('/events/close/<int:id>', methods=['POST'])
@login_required
def close_event(id):
    db.events.update_one({'_id': id}, {'$set': {'status': 'closed'}})
    flash('Event closed', 'success')
    return redirect(url_for('events'))

@app.route('/events/delete/<int:id>', methods=['POST'])
@login_required
def delete_event(id):
    db.payments.delete_many({'event_id': id})
    db.events.delete_one({'_id': id})
    flash('Event deleted', 'success')
    return redirect(url_for('events'))

@app.route('/payments')
@login_required
def payments():
    events = list(db.events.find({'status': 'active'}).sort('created_at', -1))
    selected_event_id = request.args.get('event_id')
    payments_list = []
    event = None
    students = list(db.students.find({'is_active': 1}).sort('name', 1))

    if selected_event_id:
        event = db.events.find_one({'_id': int(selected_event_id)})
        if event:
            payments_list = list(db.payments.aggregate([
                {'$match': {'event_id': event['_id']}},
                {'$sort': {'student_id': 1}},
                {'$lookup': {'from': 'users', 'localField': 'confirmed_by', 'foreignField': '_id', 'as': 'confirmer'}},
                {'$unwind': {'path': '$confirmer', 'preserveNullAndEmptyArrays': True}},
                {'$addFields': {'confirmer_name': '$confirmer.username'}},
                {'$project': {'confirmer': 0}}
            ]))

    return render_template('payments.html', events=events, event=event,
        students=students, payments=payments_list, selected_event_id=selected_event_id)

@app.route('/payments/confirm', methods=['POST'])
@login_required
def confirm_payments():
    if not can_manage_data():
        flash('Read-only accounts cannot confirm payments', 'error')
        return redirect(url_for('payments'))
    event_id = int(request.form['event_id'])
    event = db.events.find_one({'_id': event_id})
    if not event:
        flash('Event not found', 'error')
        return redirect(url_for('payments'))

    student_ids = request.form.getlist('student_ids')
    amounts_in = request.form.getlist('amounts')
    target = event['amount']
    count = 0

    for sid_str, amount_str in zip(student_ids, amounts_in):
        try:
            sid = int(sid_str)
            paid_now = float(amount_str)
        except (ValueError, TypeError):
            continue
        if paid_now <= 0:
            continue

        existing = db.payments.find_one({'event_id': event_id, 'student_id': sid})
        if existing and existing.get('locked'):
            continue

        if existing:
            payment_id = existing['_id']
            prev = existing.get('amount_paid', 0) or 0
            can_pay = min(paid_now, target - prev)
            if can_pay <= 0:
                continue
            new_amount_paid = prev + can_pay
            is_locked = new_amount_paid >= target
            db.payments.update_one({'_id': payment_id}, {'$set': {
                'confirmed': True,
                'amount_paid': new_amount_paid,
                'confirmed_by': current_user.id,
                'confirmed_at': datetime.now(),
                'locked': is_locked,
            }})
        else:
            payment_id = next_id('payments')
            can_pay = min(paid_now, target)
            if can_pay <= 0:
                continue
            new_amount_paid = can_pay
            is_locked = new_amount_paid >= target
            db.payments.insert_one({
                '_id': payment_id,
                'event_id': event_id,
                'student_id': sid,
                'amount': target,
                'amount_paid': new_amount_paid,
                'confirmed': True,
                'confirmed_by': current_user.id,
                'confirmed_at': datetime.now(),
                'locked': is_locked,
                'notes': '',
                'created_at': datetime.now()
            })

        db.transactions.insert_one({
            '_id': next_id('transactions'),
            'payment_id': payment_id,
            'type': 'income',
            'amount': can_pay,
            'student_id': sid,
            'description': f"Payment: {event['title']}" if event else 'Event payment',
            'transaction_date': date.today().isoformat(),
            'created_by': current_user.id,
            'created_at': datetime.now()
        })
        count += 1

    flash(f'{count} payment(s) confirmed', 'success')
    return redirect(url_for('payments', event_id=event_id))

@app.route('/payments/unconfirm/<int:payment_id>', methods=['POST'])
@login_required
def unconfirm_payment(payment_id):
    if not can_override():
        flash('Access denied. Only admin, mayor, or treasurer can override.', 'error')
        return redirect(url_for('payments'))

    payment = db.payments.find_one({'_id': payment_id})
    if not payment:
        flash('Payment not found', 'error')
        return redirect(url_for('payments'))

    db.payments.update_one({'_id': payment_id}, {'$set': {
        'confirmed': False,
        'amount_paid': 0,
        'locked': False,
        'notes': request.form.get('notes', 'Overridden by ' + current_user.username)
    }})
    db.transactions.delete_many({'payment_id': payment_id})
    flash('Payment unlocked', 'success')
    return redirect(url_for('payments', event_id=payment['event_id']))

@app.route('/students')
@login_required
def students():
    return render_template('students.html', students=list(db.students.find().sort([('is_active', -1), ('name', 1)])))

@app.route('/students/add', methods=['POST'])
@login_required
def add_student():
    try:
        db.students.insert_one({
            '_id': next_id('students'), 'student_id': request.form['student_id'],
            'name': request.form['name'], 'course': request.form.get('course',''),
            'year': request.form.get('year',''), 'email': request.form.get('email',''),
            'phone': request.form.get('phone',''), 'is_active': 1, 'created_at': datetime.now()
        })
        flash('Student added', 'success')
    except Exception:
        flash('Student ID already exists', 'error')
    return redirect(url_for('students'))

@app.route('/students/edit/<int:id>', methods=['POST'])
@login_required
def edit_student(id):
    db.students.update_one({'_id': id}, {'$set': {
        'name': request.form['name'], 'course': request.form.get('course',''),
        'year': request.form.get('year',''), 'email': request.form.get('email',''),
        'phone': request.form.get('phone',''), 'is_active': int(request.form.get('is_active', 0))
    }})
    flash('Student updated', 'success')
    return redirect(url_for('students'))

@app.route('/students/delete/<int:id>', methods=['POST'])
@login_required
def delete_student(id):
    db.students.delete_one({'_id': id})
    flash('Student removed', 'success')
    return redirect(url_for('students'))

@app.route('/transactions')
@login_required
def transactions():
    page = request.args.get('page', 1, type=int)
    per_page = 20; skip = (page - 1) * per_page
    total = db.transactions.count_documents({})
    txn = list(db.transactions.aggregate([
        {'$sort': {'created_at': -1}}, {'$skip': skip}, {'$limit': per_page},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$lookup': {'from': 'users', 'localField': 'created_by', 'foreignField': '_id', 'as': 'user'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$unwind': {'path': '$user', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'description': 1, 'reference': 1, 'payment_method': 1, 'created_at': 1, 'student_name': '$student.name', 'username': '$user.username'}}
    ]))
    return render_template('transactions.html', transactions=txn,
        students=list(db.students.find({'is_active': 1}).sort('name', 1)),
        page=page, total_pages=(total + per_page - 1) // per_page)

@app.route('/transactions/add', methods=['POST'])
@login_required
def add_transaction():
    db.transactions.insert_one({
        '_id': next_id('transactions'),
        'student_id': int(request.form.get('student_id')) if request.form.get('student_id') else None,
        'category_id': int(request.form['category_id']),
        'amount': float(request.form['amount']),
        'type': request.form['type'],
        'description': request.form.get('description',''),
        'reference': request.form.get('reference',''),
        'payment_method': request.form.get('payment_method','cash'),
        'transaction_date': request.form.get('transaction_date', date.today().isoformat()),
        'created_by': current_user.id,
        'created_at': datetime.now()
    })
    flash('Transaction recorded', 'success')
    return redirect(url_for('transactions'))

@app.route('/transactions/delete/<int:id>', methods=['POST'])
@login_required
def delete_transaction(id):
    db.transactions.delete_one({'_id': id})
    flash('Transaction deleted', 'success')
    return redirect(url_for('transactions'))

@app.route('/reports')
@login_required
def reports():
    rt = request.args.get('type', 'summary')
    if rt == 'student':
        data = list(db.students.aggregate([
            {'$match': {'is_active': 1}},
            {'$lookup': {'from': 'transactions', 'localField': '_id', 'foreignField': 'student_id', 'as': 'txns'}},
            {'$project': {'student_id': 1, 'name': 1, 'course': 1, 'total_paid': {'$sum': {'$cond': [{'$eq': ['$txns.type', 'income']}, '$txns.amount', 0]}}, 'total_used': {'$sum': {'$cond': [{'$eq': ['$txns.type', 'expense']}, '$txns.amount', 0]}}}},
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
            row['total_paid'] = row.get('total_paid', 0) + paid_by_student.get(row['_id'], 0)
        return render_template('reports.html', report_type=rt, data=data)
    if rt == 'date_range':
        start = request.args.get('start', date.today().replace(day=1).isoformat())
        end = request.args.get('end', date.today().isoformat())
        txn = list(db.transactions.aggregate([
            {'$match': {'transaction_date': {'$gte': start, '$lte': end}, 'description': {'$not': {'$regex': '^Payment:'}}}}, {'$sort': {'transaction_date': 1}},
            {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
            {'$lookup': {'from': 'users', 'localField': 'created_by', 'foreignField': '_id', 'as': 'user'}},
            {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
            {'$unwind': {'path': '$user', 'preserveNullAndEmptyArrays': True}},
            {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'description': 1, 'reference': 1, 'student_name': '$student.name', 'username': '$user.username'}}
        ]))
        txn.extend(get_confirmed_payment_rows(start, end))
        txn.sort(key=lambda row: row.get('transaction_date', ''))
        return render_template('reports.html', report_type=rt, transactions=txn, start=start, end=end,
            total_inc=sum(r['amount'] for r in txn if r['type']=='income'),
            total_exp=sum(r['amount'] for r in txn if r['type']=='expense'))
    income, expense = get_financial_totals()
    monthly = list(db.transactions.aggregate([
        {'$group': {'_id': {'$substr': ['$transaction_date', 0, 7]}, 'inc': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}}, 'exp': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}}},
        {'$sort': {'_id': -1}}, {'$limit': 12}, {'$project': {'mon': '$_id', 'inc': 1, 'exp': 1, '_id': 0}}
    ]))
    return render_template('reports.html', report_type='summary', income=income, expense=expense, balance=income-expense, monthly=monthly)

@app.route('/export')
@login_required
def export():
    txn = list(db.transactions.aggregate([
        {'$match': {'description': {'$not': {'$regex': '^Payment:'}}}},
        {'$sort': {'transaction_date': 1}},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'description': 1, 'reference': 1, 'payment_method': 1, 'student': '$student.name'}}
    ]))
    txn.extend(get_confirmed_payment_rows())
    txn.sort(key=lambda row: row.get('transaction_date', ''))
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['Date', 'Type', 'Student', 'Amount', 'Description', 'Reference', 'Payment'])
    for r in txn:
        w.writerow([r['transaction_date'], r['type'], r.get('student','') or '', f"{r['amount']:.2f}", r.get('description','') or '', r.get('reference','') or '', r.get('payment_method','')])
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f'treasury_report_{date.today().isoformat()}.csv', mimetype='text/csv')

@app.route('/api/balance')
@login_required
def api_balance():
    income, expense = get_financial_totals()
    return jsonify({'balance': income - expense})

@app.route('/users')
@login_required
def users():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    user_list = list(db.users.find({}, {'_id': 1, 'username': 1, 'role': 1, 'created_at': 1, 'display_name': 1, 'google_email': 1, 'picture': 1}).sort('username', 1))
    officer_count = sum(1 for user in user_list if user.get('role') in ['mayor', 'treasurer'])
    return render_template('users.html', users=user_list, officer_count=officer_count, has_logo=logo_file() is not None)

@app.route('/admin/logo', methods=['POST'])
@login_required
def upload_logo():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    upload = request.files.get('logo')
    if not upload or not upload.filename:
        flash('Choose a logo image first', 'error')
        return redirect(url_for('users'))
    filename = secure_filename(upload.filename)
    extension = Path(filename).suffix.lower().lstrip('.')
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        flash('Logo must be PNG, JPG, JPEG, or WebP', 'error')
        return redirect(url_for('users'))
    for old_extension in ALLOWED_LOGO_EXTENSIONS:
        old_file = Path(app.instance_path) / f'app_logo.{old_extension}'
        if old_file.exists():
            old_file.unlink()
    upload.save(Path(app.instance_path) / f'app_logo.{extension}')
    flash('Application logo updated', 'success')
    return redirect(url_for('users'))

@app.route('/app-logo')
def app_logo():
    path = logo_file()
    if not path:
        return '', 404
    return send_file(path)

@app.route('/users/add', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    role = request.form.get('role', 'staff').lower()
    if role not in ROLES:
        flash('Invalid officer role', 'error')
        return redirect(url_for('users'))
    try:
        db.users.insert_one({'_id': next_id('users'), 'username': request.form['username'], 'password': generate_password_hash(request.form['password']), 'role': role, 'created_at': datetime.now()})
        flash('User created', 'success')
    except Exception:
        flash('Username already exists', 'error')
    return redirect(url_for('users'))

@app.route('/users/<int:id>/role', methods=['POST'])
@login_required
def assign_user_role(id):
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    role = request.form.get('role', '').lower()
    if role not in ROLES:
        flash('Invalid officer role', 'error')
        return redirect(url_for('users'))
    user = db.users.find_one({'_id': id})
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('users'))
    db.users.update_one({'_id': id}, {'$set': {'role': role}})
    flash(f"{user['username']} is now {role.title()}", 'success')
    return redirect(url_for('users'))

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
