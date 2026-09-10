from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .audit import log_audit
from .db import db, next_id
from .decorators import current_user_id, get_float, role_required, validate_csrf

bp = Blueprint('transactions', __name__)
ROLES_MANAGE = ('admin', 'mayor', 'treasurer')


@bp.route('/transactions')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    skip = (page - 1) * per_page
    query = {'deleted': {'$ne': True}}
    total = db.transactions.count_documents(query)

    student_map = {s['_id']: s.get('name', '') for s in db.students.find({})}
    user_map = {u['_id']: u.get('display_name') or u.get('username', '') for u in db.users.find({})}

    raw_txns = list(db.transactions.find(query).sort('created_at', -1).skip(skip).limit(per_page))
    txn = []
    for t in raw_txns:
        s_ids = t.get('student_ids') or ([t['student_id']] if t.get('student_id') else [])
        t['student_names'] = [student_map[sid] for sid in s_ids if sid in student_map]
        t['username'] = user_map.get(t.get('created_by'), '—')
        txn.append(t)

    return render_template('transactions.html', transactions=txn,
        students=list(db.students.find({'deleted': {'$ne': True}, 'is_active': 1}).sort('name', 1)),
        page=page, total_pages=(total + per_page - 1) // per_page)


@bp.route('/transactions/add', methods=['POST'])
@login_required
@role_required(*ROLES_MANAGE)
def add():
    validate_csrf()
    txn_type = request.form.get('type', '')
    if txn_type not in ('income', 'expense'):
        flash('Invalid transaction type', 'error')
        return redirect(url_for('transactions.index'))
    amount = get_float(request.form, 'amount')
    txn_id = next_id('transactions')
    receipt = f"RCP-{date.today().strftime('%Y%m%d')}-{txn_id:04d}"

    recipient_type = request.form.get('recipient_type', 'student')
    student_ids = None
    payee = None
    if recipient_type == 'student':
        student_ids_raw = request.form.getlist('student_ids')
        student_ids = [int(s) for s in student_ids_raw if s.strip()] or None
    else:
        payee = request.form.get('payee', '').strip() or None

    db.transactions.insert_one({
        '_id': txn_id,
        'student_ids': student_ids,
        'payee': payee,
        'recipient_type': recipient_type,
        'amount': amount,
        'type': txn_type,
        'description': request.form.get('description', ''),
        'reference': receipt,
        'receipt': receipt,
        'payment_method': request.form.get('payment_method', 'cash'),
        'transaction_date': request.form.get('transaction_date', date.today().isoformat()),
        'created_by': current_user_id(),
        'created_at': datetime.now(),
        'deleted': False,
    })
    log_audit('transaction_add', target=txn_id, detail=txn_type)
    flash(f'Transaction recorded — Receipt #{receipt}', 'success')
    return redirect(url_for('transactions.index'))


@bp.route('/transactions/delete/<int:id>', methods=['POST'])
@login_required
@role_required(*ROLES_MANAGE)
def delete(id):
    validate_csrf()
    # Soft-delete to preserve the audit trail.
    db.transactions.update_one({'_id': id}, {'$set': {'deleted': True}})
    log_audit('transaction_delete', target=id)
    flash('Transaction deleted', 'success')
    return redirect(url_for('transactions.index'))
