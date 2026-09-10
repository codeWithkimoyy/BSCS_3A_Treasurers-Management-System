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
    txn = list(db.transactions.aggregate([
        {'$match': query},
        {'$sort': {'created_at': -1}}, {'$skip': skip}, {'$limit': per_page},
        {'$addFields': {
            'lookup_ids': {'$cond': [
                {'$and': [{'$isArray': '$student_ids'}, {'$gt': [{'$size': '$student_ids'}, 0]}]},
                '$student_ids',
                {'$cond': [{'$ne': ['$student_id', None]}, ['$student_id'], []]}
            ]}
        }},
        {'$lookup': {'from': 'students', 'localField': 'lookup_ids', 'foreignField': '_id', 'as': 'students'}},
        {'$lookup': {'from': 'users', 'localField': 'created_by', 'foreignField': '_id', 'as': 'user'}},
        {'$unwind': {'path': '$user', 'preserveNullAndEmptyArrays': True}},
        {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'description': 1, 'reference': 1, 'receipt': 1, 'payment_method': 1, 'created_at': 1, 'student_names': '$students.name', 'username': '$user.username'}}
    ]))
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
    student_ids_raw = request.form.getlist('student_ids')
    student_ids = [int(s) for s in student_ids_raw if s.strip()]
    db.transactions.insert_one({
        '_id': txn_id,
        'student_ids': student_ids if student_ids else None,
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
