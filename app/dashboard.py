from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template
from flask_login import login_required

from .db import db, get_financial_totals

bp = Blueprint('dashboard', __name__)


@bp.route('/health/db')
def db_health():
    is_mock = 'mongomock' in type(db._database).__module__
    raw_uri = current_app.config.get('MONGO_URI') or ''
    clean_uri = raw_uri.strip().strip('"').strip("'").strip()
    safe_prefix = clean_uri[:16] if clean_uri else 'EMPTY'

    try:
        events_cnt = db.events.count_documents({})
        students_cnt = db.students.count_documents({})
        txns_cnt = db.transactions.count_documents({})
    except Exception:
        events_cnt = -1
        students_cnt = -1
        txns_cnt = -1

    return jsonify({
        'status': 'connected' if not is_mock else 'offline_fallback',
        'is_mock': is_mock,
        'uri_starts_with': safe_prefix,
        'last_error': getattr(db, '_last_error', None),
        'database_name': getattr(db._database, 'name', None),
        'events_count': events_cnt,
        'students_count': students_cnt,
        'transactions_count': txns_cnt
    })


@bp.route('/')
@login_required
def index():
    income, expense = get_financial_totals()
    balance = income - expense
    member_count = db.students.count_documents({'is_active': 1})
    event_count = db.events.count_documents({'status': 'active'})
    pending_payments = db.payments.count_documents({'confirmed': False})

    student_map = {s['_id']: s.get('name', '') for s in db.students.find({})}

    raw_recent = list(db.transactions.find({'deleted': {'$ne': True}}).sort('created_at', -1).limit(5))
    recent = []
    for t in raw_recent:
        s_ids = t.get('student_ids') or ([t['student_id']] if t.get('student_id') else [])
        t['student_names'] = [student_map[sid] for sid in s_ids if sid in student_map]
        recent.append(t)

    recent_payments = list(db.payments.aggregate([
        {'$match': {'confirmed': True}},
        {'$sort': {'confirmed_at': -1}}, {'$limit': 10},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$lookup': {'from': 'events', 'localField': 'event_id', 'foreignField': '_id', 'as': 'event'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$unwind': {'path': '$event', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'amount': '$amount_paid', 'confirmed_at': 1, 'notes': 1, 'student_name': '$student.name', 'event_title': '$event.title'}}
    ]))

    raw_recent_expenses = list(db.transactions.find({'type': 'expense', 'deleted': {'$ne': True}}).sort([('transaction_date', -1), ('created_at', -1)]).limit(6))
    recent_expenses = []
    for e in raw_recent_expenses:
        s_ids = e.get('student_ids') or ([e['student_id']] if e.get('student_id') else [])
        e['student_names'] = [student_map[sid] for sid in s_ids if sid in student_map]
        recent_expenses.append(e)

    # Dynamic outflow category aggregation (Where the money has gone)
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

    six_months_ago = datetime.now()
    try:
        six_months_ago = six_months_ago.replace(month=six_months_ago.month - 6)
    except ValueError:
        six_months_ago = six_months_ago.replace(year=six_months_ago.year - 1, month=six_months_ago.month + 6)

    last_6 = list(db.transactions.aggregate([
        {'$match': {'transaction_date': {'$gte': six_months_ago.strftime('%Y-%m-%d')}, 'deleted': {'$ne': True}}},
        {'$group': {'_id': {'$substr': ['$transaction_date', 0, 7]}, 'inc': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}}, 'exp': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}}},
        {'$sort': {'_id': 1}}, {'$project': {'mon': '$_id', 'inc': 1, 'exp': 1, '_id': 0}}
    ]))

    payment_months = list(db.payments.aggregate([
        {'$match': {'confirmed': True, 'confirmed_at': {'$gte': six_months_ago}}},
        {'$group': {'_id': {'$dateToString': {'format': '%Y-%m', 'date': '$confirmed_at'}}, 'inc': {'$sum': '$amount_paid'}}},
        {'$project': {'_id': 0, 'mon': '$_id', 'inc': 1}}
    ]))
    monthly = {r['mon']: {'inc': r.get('inc', 0), 'exp': r.get('exp', 0)} for r in last_6}
    for payment_month in payment_months:
        monthly.setdefault(payment_month['mon'], {'inc': 0, 'exp': 0})
        monthly[payment_month['mon']]['inc'] += payment_month.get('inc', 0)
    trend_data = [{'mon': month, **monthly[month]} for month in sorted(monthly)]
    months = [r['mon'] for r in trend_data]

    has_trend = bool(trend_data)
    has_donut = income > 0 or expense > 0

    return render_template('dashboard.html',
        income=income, expense=expense, balance=balance,
        member_count=member_count, event_count=event_count, pending_payments=pending_payments,
        recent=recent, recent_payments=recent_payments, recent_expenses=recent_expenses,
        disbursement_categories=disbursement_categories,
        has_donut=has_donut, has_trend=has_trend,
        donut={'income': income, 'expense': expense},
        trend={'labels': months,
               'income': [r['inc'] for r in trend_data],
               'expense': [r['exp'] for r in trend_data]})
