import os
with open(r'C:\Users\MoyMoy\Desktop\StudentTreasurer\.env') as f:
    for line in f:
        if line.startswith('MONGO_URI='):
            os.environ['MONGO_URI'] = line.split('=', 1)[1].strip()
            break

from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URI'], tls=True, tlsInsecure=True)['student_treasury']

event = db.events.find_one({'title': {'$regex': 'Singking', '$options': 'i'}})
print(f"Event: {event['title']} (ID:{event['_id']})")

payments = list(db.payments.find({'event_id': event['_id']}).sort('_id', 1))
print(f"Total payments: {len(payments)}")
for p in payments:
    sid = p.get('student_id')
    s = db.students.find_one({'_id': sid})
    name = s['name'] if s else 'UNKNOWN'
    print(f"  ID:{p['_id']} {name} Paid:P{p.get('amount_paid',0)}/{p['amount']} Locked:{p.get('locked')}")
