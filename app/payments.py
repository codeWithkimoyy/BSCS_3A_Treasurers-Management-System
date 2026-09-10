from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .audit import log_audit
from .db import db, next_id
from .decorators import current_user_id, current_username, role_required, validate_csrf

bp = Blueprint('payments', __name__)

ROLES_MANAGE = ('admin', 'mayor', 'treasurer')
ROLES_OVERRIDE = ('admin', 'mayor', 'treasurer')


@bp.route('/payments')
@login_required
def index():
    events = list(db.events.find({'status': 'active'}).sort('created_at', -1))
    for e in events:
        e['amount'] = float(e.get('amount', 0) or 0)

    selected_event_id = request.args.get('event_id')
    payments_list = []
    event = None
    students = list(db.students.find({'is_active': 1}).sort('name', 1))

    if selected_event_id:
        query_ids = []
        try:
            query_ids.append({'_id': int(selected_event_id)})
        except (ValueError, TypeError):
            pass
        query_ids.append({'_id': str(selected_event_id)})

        event = db.events.find_one({'$or': query_ids}) if len(query_ids) > 1 else db.events.find_one(query_ids[0])
        if event:
            event['amount'] = float(event.get('amount', 0) or 0)
            ev_id = event['_id']
            match_ids = [ev_id]
            try:
                match_ids.append(int(ev_id))
            except (ValueError, TypeError):
                pass
            match_ids.append(str(ev_id))

            payments_list = list(db.payments.aggregate([
                {'$match': {'event_id': {'$in': list(set(match_ids))}}},
                {'$sort': {'student_id': 1}},
                {'$lookup': {'from': 'users', 'localField': 'confirmed_by', 'foreignField': '_id', 'as': 'confirmer'}},
                {'$unwind': {'path': '$confirmer', 'preserveNullAndEmptyArrays': True}},
                {'$addFields': {'confirmer_name': '$confirmer.username'}},
                {'$project': {'confirmer': 0}}
            ]))
            for p in payments_list:
                p['amount_paid'] = float(p.get('amount_paid', 0) or 0)
                p['locked'] = bool(p.get('locked', False))

    return render_template('payments.html', events=events, event=event,
        students=students, payments=payments_list, selected_event_id=selected_event_id)


@bp.route('/payments/confirm', methods=['POST'])
@login_required
@role_required(*ROLES_MANAGE)
def confirm():
    validate_csrf()
    event_id = int(request.form['event_id'])
    event = db.events.find_one({'_id': event_id})
    if not event:
        flash('Event not found', 'error')
        return redirect(url_for('payments.index'))

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
                'confirmed_by': current_user_id(),
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
                'confirmed_by': current_user_id(),
                'confirmed_at': datetime.now(),
                'locked': is_locked,
                'notes': '',
                'created_at': datetime.now(),
            })

        db.transactions.insert_one({
            '_id': next_id('transactions'),
            'payment_id': payment_id,
            'type': 'income',
            'amount': can_pay,
            'student_id': sid,
            'description': f"Payment: {event['title']}" if event else 'Event payment',
            'transaction_date': date.today().isoformat(),
            'created_by': current_user_id(),
            'created_at': datetime.now(),
        })
        count += 1

    log_audit('payments_confirm', target=event_id, detail=f'{count} confirmed')
    flash(f'{count} payment(s) confirmed', 'success')
    return redirect(url_for('payments.index', event_id=event_id))


@bp.route('/payments/unconfirm/<int:payment_id>', methods=['POST'])
@login_required
@role_required(*ROLES_OVERRIDE)
def unconfirm(payment_id):
    validate_csrf()
    payment = db.payments.find_one({'_id': payment_id})
    if not payment:
        flash('Payment not found', 'error')
        return redirect(url_for('payments.index'))

    db.payments.update_one({'_id': payment_id}, {'$set': {
        'confirmed': False,
        'amount_paid': 0,
        'locked': False,
        'notes': request.form.get('notes', 'Overridden by ' + current_username()),
    }})
    db.transactions.delete_many({'payment_id': payment_id})
    log_audit('payment_unconfirm', target=payment_id)
    flash('Payment unlocked', 'success')
    return redirect(url_for('payments.index', event_id=payment['event_id']))
