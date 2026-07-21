import os
with open(r'C:\Users\MoyMoy\Desktop\StudentTreasurer\.env') as f:
    for line in f:
        if line.startswith('MONGO_URI='):
            os.environ['MONGO_URI'] = line.split('=', 1)[1].strip()
            break

from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URI'], tls=True, tlsInsecure=True)['student_treasury']

# Find the "Singking Fund" event
event = db.events.find_one({'title': {'$regex': 'Singking', '$options': 'i'}})
if not event:
    # Try the most recent event
    event = db.events.find_one({}, sort=[('created_at', -1)])
    
print(f"Event: {event['title']} (ID:{event['_id']}) Amount: {event['amount']}")

# Find KIM CUTAMORA's legitimate payment
kim = db.students.find_one({'name': {'$regex': 'CUTAMORA.*KIM', '$options': 'i'}})
print(f"Kim ID: {kim['_id'] if kim else 'NOT FOUND'}")

# Delete ALL accidental payments for this event EXCEPT Kim's
event_id = event['_id']
kim_id = kim['_id'] if kim else None

# First, delete transactions for all accidental payments
result = db.transactions.delete_many({
    'payment_id': {'$nin': [26]},  # Keep Kim's by payment ID
    'description': {'$regex': 'Singking', '$options': 'i'}
})
print(f"Deleted {result.deleted_count} transactions for Singking Fund")

# Delete payments that are NOT Kim's
all_payments = list(db.payments.find({'event_id': event_id}))
for p in all_payments:
    if p['_id'] != 26:  # Keep Kim's ₱7 payment
        db.payments.delete_one({'_id': p['_id']})
        sid = p.get('student_id')
        s = db.students.find_one({'_id': sid})
        print(f"  Deleted payment ID:{p['_id']} for {s['name'] if s else 'UNKNOWN'}")

# Verify Kim's payment still exists
kim_payment = db.payments.find_one({'_id': 26})
if kim_payment:
    print(f"\nKept Kim's payment: ₱{kim_payment.get('amount_paid')} / ₱{kim_payment['amount']} Locked:{kim_payment.get('locked')}")
else:
    print("\nERROR: Kim's payment was also deleted!")
    
print("\nDone! Remaining payments for this event:")
remaining = list(db.payments.find({'event_id': event_id}))
for p in remaining:
    sid = p.get('student_id')
    s = db.students.find_one({'_id': sid})
    print(f"  ID:{p['_id']} {s['name'] if s else 'UNKNOWN'} - ₱{p.get('amount_paid')}/₱{p['amount']}")
