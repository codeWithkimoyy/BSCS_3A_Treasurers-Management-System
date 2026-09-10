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
        user_map = {u['_id']: u.get('display_name') or u.get('username', '') for u in db.users.find({})}

        raw_expenses = [t for t in db.transactions.find({'type': 'expense'}) if not t.get('deleted')]
        raw_expenses.sort(key=lambda x: (x.get('transaction_date', '') or '', str(x.get('created_at', ''))), reverse=True)

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
            elif any(k in desc for k in ('freshface', 'acquaintance', 'event', 'party', 'activity', 'intrams')):
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

        return render_template(
            'reports.html',
            report_type='transparency',
            income=income,
            total_expense=total_expense,
            balance=balance,
            expenses=categorized_expenses,
            cat_summary=cat_summary,
            table_total=sum(float(e.get('amount', 0) or 0) for e in categorized_expenses)
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
    balance = income - expense

    # 1. Complete Monthly Breakdown combining both confirmed payments and manual transactions
    months = {}
    for p in db.payments.find({'confirmed': True}):
        dt = p.get('confirmed_at')
        if dt:
            m = dt.strftime('%Y-%m')
            months.setdefault(m, {'inc': 0.0, 'exp': 0.0})
            months[m]['inc'] += float(p.get('amount_paid', 0) or 0)

    for t in db.transactions.find():
        if t.get('deleted'):
            continue
        dt_str = t.get('transaction_date', '')
        if dt_str:
            m = dt_str[:7]
            months.setdefault(m, {'inc': 0.0, 'exp': 0.0})
            amt = float(t.get('amount', 0) or 0)
            if t.get('type') == 'income' and not (t.get('description') or '').startswith('Payment:'):
                months[m]['inc'] += amt
            elif t.get('type') == 'expense':
                months[m]['exp'] += amt

    sorted_m = sorted(months.keys(), reverse=True)
    monthly = [
        {'mon': m, 'inc': months[m]['inc'], 'exp': months[m]['exp'], 'net': months[m]['inc'] - months[m]['exp']}
        for m in sorted_m
    ]

    # 2. Detailed Inflow Breakdown (Event Collections & Direct Inflows)
    events = list(db.events.find({'deleted': {'$ne': True}}).sort('created_at', 1))
    inflow_sources = []
    for ev in events:
        pmts = list(db.payments.find({'event_id': ev['_id'], 'confirmed': True}))
        collected = sum(float(p.get('amount_paid', 0) or 0) for p in pmts)
        if collected > 0:
            inflow_sources.append({
                'title': ev.get('title', 'Event'),
                'type': 'Event Collection',
                'target': float(ev.get('amount', 0)),
                'payers': len(pmts),
                'amount': collected
            })

    manual_inflows = [
        t for t in db.transactions.find({'type': 'income'})
        if not t.get('deleted') and not (t.get('description') or '').startswith('Payment:')
    ]
    for t in manual_inflows:
        inflow_sources.append({
            'title': t.get('description') or 'Direct Contribution',
            'type': 'Direct Inflow',
            'target': float(t.get('amount', 0)),
            'payers': 1,
            'amount': float(t.get('amount', 0))
        })
    inflow_sources.sort(key=lambda x: -x['amount'])

    # 3. Outflow Categories Breakdown
    raw_expenses = [t for t in db.transactions.find({'type': 'expense'}) if not t.get('deleted')]
    categories = {
        'Student Refunds & Adjustments': 0.0,
        'Platform & System Services': 0.0,
        'Event Remittances & Programs': 0.0,
        'Supplies & Materials': 0.0,
        'Operations & Miscellaneous': 0.0,
    }
    for e in raw_expenses:
        desc = (e.get('description') or '').lower()
        amt = float(e.get('amount', 0) or 0)
        if 'refund' in desc or 'correction' in desc:
            cat = 'Student Refunds & Adjustments'
        elif any(k in desc for k in ('uniscan', 'system', 'software', 'platform', 'online')):
            cat = 'Platform & System Services'
        elif any(k in desc for k in ('freshface', 'acquaintance', 'event', 'party', 'activity', 'intrams')):
            cat = 'Event Remittances & Programs'
        elif any(k in desc for k in ('supplies', 'printing', 'ink', 'paper', 'materials')):
            cat = 'Supplies & Materials'
        else:
            cat = 'Operations & Miscellaneous'
        categories[cat] += amt

    cat_summary = [
        {'name': k, 'amount': v, 'pct': (v / expense * 100) if expense > 0 else 0}
        for k, v in categories.items() if v > 0
    ]
    cat_summary.sort(key=lambda x: -x['amount'])

    return render_template(
        'reports.html',
        report_type='summary',
        income=income,
        expense=expense,
        balance=balance,
        monthly=monthly,
        inflow_sources=inflow_sources,
        cat_summary=cat_summary,
        total_inflows_check=sum(s['amount'] for s in inflow_sources),
        total_outflows_check=sum(c['amount'] for c in cat_summary)
    )


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
    raw_expenses = [t for t in db.transactions.find({'type': 'expense'}) if not t.get('deleted')]
    raw_expenses.sort(key=lambda x: (x.get('transaction_date', '') or '', str(x.get('created_at', ''))))

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

