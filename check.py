import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')
import os
client = MongoClient(os.environ.get('MONGO_URI'))
db = client.get_database()

print("Confirmed payments:", db.payments.count_documents({'confirmed': True}))
print("All payments:", db.payments.count_documents({}))

# Check if recent_payments query works
from datetime import datetime
recent_payments = list(db.payments.aggregate([
    {'$match': {'confirmed': True}},
    {'$sort': {'confirmed_at': -1}}, {'$limit': 10},
    {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
    {'$lookup': {'from': 'events', 'localField': 'event_id', 'foreignField': '_id', 'as': 'event'}},
    {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
    {'$unwind': {'path': '$event', 'preserveNullAndEmptyArrays': True}},
    {'$project': {'amount': 1, 'confirmed_at': 1, 'notes': 1, 'student_name': '$student.name', 'event_title': '$event.title'}}
]))
print(f"Query returned: {len(recent_payments)}")
for p in recent_payments:
    ca = p.get('confirmed_at')
    print(f"  {p.get('student_name')} - {p.get('event_title')} - P{p.get('amount')} - confirmed_at={ca} type={type(ca).__name__}")
    # Test strftime
    if ca:
        print(f"    strftime works: {ca.strftime('%b %d, %I:%M %p')}")
