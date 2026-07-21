import os
with open(r'C:\Users\MoyMoy\Desktop\StudentTreasurer\.env') as f:
    for line in f:
        if line.startswith('MONGO_URI='):
            os.environ['MONGO_URI'] = line.split('=', 1)[1].strip()
            break
from datetime import datetime

from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URI'], tls=True, tlsInsecure=True)['student_treasury']

event = db.events.find_one({'title': {'$regex': 'Singking', '$options': 'i'}})
eid = event['_id']

kim = db.students.find_one({'name': {'$regex': 'CUTAMORA.*KIM', '$options': 'i'}})
kim_id = kim['_id']

others = list(db.payments.find({'event_id': eid, 'student_id': {'$ne': kim_id}}))
print(f"Removing {len(others)} accidental payments")
for p in others:
    db.transactions.delete_many({'payment_id': p['_id']})
    db.payments.delete_one({'_id': p['_id']})
    s = db.students.find_one({'_id': p['student_id']})
    print(f"  Deleted {s['name'] if s else 'UNKNOWN'}")

db.payments.update_one({'_id': 26}, {'$set': {'amount_paid': 7.0, 'locked': False, 'confirmed': True, 'confirmed_at': datetime.now()}})
db.transactions.delete_many({'payment_id': 26})
db.transactions.insert_one({
    '_id': 10000,
    'payment_id': 26,
    'type': 'income',
    'amount': 7.0,
    'student_id': kim_id,
    'description': 'Payment: Singking Fund',
    'transaction_date': '2026-07-21',
    'created_by': 4,
    'created_at': datetime.now()
})

remaining = list(db.payments.find({'event_id': eid}))
print(f"\nRemaining: {len(remaining)} payment(s)")
for p in remaining:
    s = db.students.find_one({'_id': p['student_id']})
    print(f"  {s['name'] if s else 'UNKNOWN'} - P{p.get('amount_paid')}/P{p['amount']} Locked:{p.get('locked')}")
print("\nDone!")
