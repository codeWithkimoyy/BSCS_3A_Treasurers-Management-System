from datetime import date

from flask import Blueprint, render_template, request, send_file
from flask_login import login_required

from .db import db, get_confirmed_payment_rows, get_financial_totals

bp = Blueprint('reports', __name__)


@bp.route('/reports')
@login_required
def index():
    rt = request.args.get('type', 'summary')
    if rt == 'transparency':
        income, total_expense = get_financial_totals()
        balance = income - total_expense

        student_map = {s['_id']: s.get('name', '') for s in db.students.find({})}
        user_map = {u['_id']: u.get('username', '') for u in db.users.find({})}

        raw_expenses = list(db.transactions.find({'type': 'expense', 'deleted': {'$ne': True}}).sort([('transaction_date', -1), ('created_at', -1)]))

        expenses = []
        for e in raw_expenses:
            s_ids = e.get('student_ids') or ([e['student_id']] if e.get('student_id') else [])
            e['student_names'] = [student_map[sid] for sid in s_ids if sid in student_map]
            e['username'] = user_map.get(e.get('created_by'), '')
            expenses.append(e)

        # Category categorization
        categories = {
            'Student Refunds & Adjustments': 0.0,
            'Platform & System Services': 0.0,
            'Event Remittances & Programs': 0.0,
            'Supplies & Materials': 0.0,
            'Operations & Miscellaneous': 0.0,
        }

        categorized_expenses = []
        for e in expenses:
            desc = (e.get('description') or '').lower()
            amt = float(e.get('amount', 0))
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
            categories[cat] += amt
            e['category'] = cat
            categorized_expenses.append(e)

        cat_summary = [
            {'name': k, 'amount': v, 'pct': (v / total_expense * 100) if total_expense > 0 else 0}
            for k, v in categories.items() if v > 0
        ]
        cat_summary.sort(key=lambda x: -x['amount'])

        # Event-level fund reconciliation
        events = list(db.events.find({'deleted': {'$ne': True}}).sort('created_at', 1))
        event_recon = []
        for ev in events:
            ev_id = ev['_id']
            ev_title = ev.get('title', 'Untitled')
            # payments collected
            collected_agg = list(db.payments.aggregate([
                {'$match': {'event_id': ev_id, 'confirmed': True}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount_paid'}, 'count': {'$sum': 1}}}
            ]))
            collected = collected_agg[0]['total'] if collected_agg else 0.0
            payer_count = collected_agg[0]['count'] if collected_agg else 0

            # expenses tagged to this event
            exp_match = [
                e['amount'] for e in categorized_expenses
                if ev_title.lower() in (e.get('description') or '').lower()
            ]
            disbursed = sum(exp_match)
            variance = collected - disbursed

            event_recon.append({
                'title': ev_title,
                'target': ev.get('amount', 0),
                'collected': collected,
                'payers': payer_count,
                'disbursed': disbursed,
                'variance': variance,
                'status': 'Balanced' if variance == 0 else ('Fund Subsidized' if variance < 0 else 'Surplus')
            })

        # Sinking fund summary (non-event payments or Sinking Fund events)
        sinking_total = sum(r['collected'] for r in event_recon if 'sinking' in r['title'].lower())
        advances_total = sum(abs(r['variance']) for r in event_recon if r['variance'] < 0)

        return render_template(
            'reports.html',
            report_type='transparency',
            income=income,
            total_expense=total_expense,
            balance=balance,
            expenses=categorized_expenses,
            cat_summary=cat_summary,
            event_recon=event_recon,
            sinking_total=sinking_total,
            advances_total=advances_total,
            chart_labels=[c['name'] for c in cat_summary],
            chart_data=[c['amount'] for c in cat_summary]
        )

    if rt == 'student':
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
            row['total_paid'] = row.get('total_paid', 0) + paid_by_student.get(row['_id'], 0)
        return render_template('reports.html', report_type=rt, data=data)

    if rt == 'date_range':
        start = request.args.get('start', date.today().replace(day=1).isoformat())
        end = request.args.get('end', date.today().isoformat())
        txn = list(db.transactions.aggregate([
            {'$match': {'transaction_date': {'$gte': start, '$lte': end},
                        'description': {'$not': {'$regex': '^Payment:'}}, 'deleted': {'$ne': True}}},
            {'$sort': {'transaction_date': 1}},
            {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
            {'$lookup': {'from': 'users', 'localField': 'created_by', 'foreignField': '_id', 'as': 'user'}},
            {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
            {'$unwind': {'path': '$user', 'preserveNullAndEmptyArrays': True}},
            {'$project': {'transaction_date': 1, 'type': 1, 'amount': 1, 'description': 1, 'reference': 1, 'student_name': '$student.name', 'username': '$user.username'}}
        ]))
        txn.extend(get_confirmed_payment_rows(start, end))
        txn.sort(key=lambda row: row.get('transaction_date', ''))
        return render_template('reports.html', report_type=rt, transactions=txn, start=start, end=end,
            total_inc=sum(r['amount'] for r in txn if r['type'] == 'income'),
            total_exp=sum(r['amount'] for r in txn if r['type'] == 'expense'))

    income, expense = get_financial_totals()
    monthly = list(db.transactions.aggregate([
        {'$match': {'deleted': {'$ne': True}}},
        {'$group': {'_id': {'$substr': ['$transaction_date', 0, 7]}, 'inc': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}}, 'exp': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}}},
        {'$sort': {'_id': -1}}, {'$limit': 12}, {'$project': {'mon': '$_id', 'inc': 1, 'exp': 1, '_id': 0}}
    ]))
    return render_template('reports.html', report_type='summary', income=income, expense=expense,
        balance=income - expense, monthly=monthly)


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
    w.writerow(['Date', 'Type', 'Student', 'Amount', 'Description', 'Reference', 'Payment'])
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
    students = list(db.students.find({'is_active': 1, 'deleted': {'$ne': True}}).sort('name', 1))

    tx_by_student = {}
    for t in db.transactions.find({'deleted': {'$ne': True}, 'student_id': {'$exists': True}}):
        sid = t['student_id']
        tx_by_student.setdefault(sid, {'inc': 0.0, 'exp': 0.0})
        amt = float(t.get('amount', 0) or 0)
        if t.get('type') == 'income':
            tx_by_student[sid]['inc'] += amt
        elif t.get('type') == 'expense':
            tx_by_student[sid]['exp'] += amt

    for t in db.transactions.find({'deleted': {'$ne': True}, 'student_ids': {'$exists': True, '$ne': None}}):
        amt = float(t.get('amount', 0) or 0)
        sids = t.get('student_ids') or []
        for sid in sids:
            tx_by_student.setdefault(sid, {'inc': 0.0, 'exp': 0.0})
            if t.get('type') == 'income':
                tx_by_student[sid]['inc'] += amt
            elif t.get('type') == 'expense':
                tx_by_student[sid]['exp'] += amt

    pmt_by_student = {}
    for p in db.payments.find({'confirmed': True}):
        sid = p.get('student_id')
        amt = float(p.get('amount_paid', 0) or 0)
        pmt_by_student[sid] = pmt_by_student.get(sid, 0.0) + amt

    import csv
    import io
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['STUDENT TREASURY BALANCES & CONTRIBUTIONS'])
    w.writerow(['Generated Date', date.today().isoformat()])
    w.writerow([])
    w.writerow(['Student ID', 'Full Name', 'Course', 'Total Paid (PHP)', 'Total Used (PHP)', 'Net Balance (PHP)'])

    for s in students:
        sid = s['_id']
        tx_totals = tx_by_student.get(sid, {'inc': 0.0, 'exp': 0.0})
        total_paid = tx_totals['inc'] + pmt_by_student.get(sid, 0.0)
        total_used = tx_totals['exp']
        net_bal = total_paid - total_used
        w.writerow([
            s.get('student_id', ''),
            s.get('name', ''),
            s.get('course', '') or '—',
            f"{total_paid:.2f}",
            f"{total_used:.2f}",
            f"{net_bal:.2f}"
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f'student_treasury_balances_{date.today().isoformat()}.csv', mimetype='text/csv')


@bp.route('/export_liquidation')
@login_required
def export_liquidation():
    import csv
    import io
    output = io.StringIO()
    w = csv.writer(output)

    income, expense = get_financial_totals()
    w.writerow(['CLASS TREASURY FINANCIAL LIQUIDATION & TRANSPARENCY REPORT'])
    w.writerow(['Generated Date', date.today().isoformat()])
    w.writerow(['Total Inflows (PHP)', f"{income:.2f}"])
    w.writerow(['Total Outflows (PHP)', f"{expense:.2f}"])
    w.writerow(['Net Cash on Hand (PHP)', f"{income - expense:.2f}"])
    w.writerow([])

    w.writerow(['--- ITEMISED DISBURSEMENTS (WHERE THE MONEY WENT) ---'])
    w.writerow(['Date', 'Category', 'Description / Purpose', 'Recipient / Payee', 'Amount (PHP)', 'Reference / Voucher', 'Payment Method'])

    student_map = {s['_id']: s.get('name', '') for s in db.students.find({})}
    raw_expenses = list(db.transactions.find({'type': 'expense', 'deleted': {'$ne': True}}).sort('transaction_date', 1))

    for e in raw_expenses:
        desc = (e.get('description') or '')
        d_lower = desc.lower()
        if 'refund' in d_lower or 'correction' in d_lower:
            cat = 'Refunds & Reimbursements'
        elif any(k in d_lower for k in ('uniscan', 'system', 'software', 'platform')):
            cat = 'Platform & System Services'
        elif any(k in d_lower for k in ('freshface', 'acquaintance', 'event', 'party')):
            cat = 'Event Remittances'
        elif any(k in d_lower for k in ('supplies', 'materials', 'printing')):
            cat = 'Supplies & Materials'
        else:
            cat = 'Operations & Miscellaneous'

        s_ids = e.get('student_ids') or ([e['student_id']] if e.get('student_id') else [])
        s_names = [student_map[sid] for sid in s_ids if sid in student_map]
        students = ', '.join(s_names) or 'Organizer / Service Provider'
        w.writerow([
            e.get('transaction_date', ''),
            cat,
            desc or 'Direct Disbursement',
            students,
            f"{e.get('amount', 0):.2f}",
            e.get('reference') or e.get('receipt') or 'N/A',
            e.get('payment_method') or 'cash'
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name=f'liquidation_report_{date.today().isoformat()}.csv', mimetype='text/csv')

