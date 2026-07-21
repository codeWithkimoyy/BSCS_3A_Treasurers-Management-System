import os
with open(r'C:\Users\MoyMoy\Desktop\StudentTreasurer\.env') as f:
    for line in f:
        if line.startswith('MONGO_URI='):
            os.environ['MONGO_URI'] = line.split('=', 1)[1].strip()
            break

from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URI'], tls=True, tlsInsecure=True)['student_treasury']

print("=== All Payments ===")
for p in db.payments.find().sort('created_at', -1):
    sid = p.get('student_id')
    student = db.students.find_one({'_id': sid})
    sname = student['name'] if student else 'UNKNOWN'
    print(f"ID:{p['_id']}  Student:{sname}  Paid:P{p.get('amount_paid',0)}  Target:P{p['amount']}  Locked:{p.get('locked')}  Confirmed:{p.get('confirmed')}  At:{p.get('confirmed_at')}")

print("\n=== All Transactions ===")
for t in db.transactions.find().sort('created_at', -1):
    sid = t.get('student_id')
    student = db.students.find_one({'_id': sid})
    sname = student['name'] if student else 'UNKNOWN'
    print(f"PaymentID:{t.get('payment_id')}  Student:{sname}  Amt:P{t['amount']}  Desc:{t.get('description','')}  Date:{t.get('transaction_date')}")
