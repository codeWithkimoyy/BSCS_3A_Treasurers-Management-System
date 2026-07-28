import os
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / '.env')
client = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=5000, tls=True, tlsInsecure=True)
db = client.get_database()
students = list(db.students.find({}, {'name':1, 'student_id':1, 'course':1, 'year':1, 'phone':1}).sort('name',1))
print(f'Total students: {len(students)}\n')
print(f'{"S_ID":>8} | {"Name":40s} | {"Course":6s} | {"Year":10s} | {"Phone":15s}')
print('-' * 85)
for s in students:
    sid = s.get('student_id', '?')
    name = s.get('name', '?')
    course = s.get('course', '')
    year = s.get('year', '')
    phone = s.get('phone', '')
    print(f'{sid:>8} | {name:40s} | {course:6s} | {year:10s} | {phone:15s}')
