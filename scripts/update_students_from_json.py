import json
import os
import re
import sys
from pathlib import Path
from pymongo import MongoClient
from dotenv import load_dotenv
from difflib import SequenceMatcher

load_dotenv(Path(__file__).parent / '.env')
client = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=10000, tls=True, tlsInsecure=True)
db = client.get_database()

with open(r'E:\Scanned\students_all.json', encoding='utf-8-sig') as f:
    all_students = json.load(f)

print(f'Loaded {len(all_students)} records from JSON')

existing = list(db.students.find({}, {
    '_id': 1, 'name': 1, 'student_id': 1, 'course': 1, 'year': 1, 'phone': 1
}).sort('name', 1))

print(f'Found {len(existing)} students in DB\n')

old_names = [s['name'] for s in existing]

def parse_name(name_str):
    """Return (last, first_tokens, middle) from 'LASTNAME, Firstname MI'"""
    name_str = name_str.strip().upper()
    if ',' in name_str:
        parts = name_str.split(',', 1)
        last = parts[0].strip()
        rest = parts[1].strip()
        tokens = rest.split()
        first = tokens[0] if tokens else ''
        middle = ' '.join(tokens[1:]) if len(tokens) > 1 else ''
        return last, first, middle
    tokens = name_str.split()
    if len(tokens) >= 2:
        last = tokens[-1]
        first = tokens[0]
        middle = ' '.join(tokens[1:-1])
        return last, first, middle
    return name_str, '', ''

def normalize(s):
    """Normalize for comparison: strip, uppercase, collapse spaces, replace accented chars"""
    s = s.strip().upper()
    replacements = {
        'Ñ': 'Ñ', 'ñ': 'Ñ',
        'Á': 'A', 'À': 'A', 'Â': 'A', 'Ã': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I',
        'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Õ': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U',
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    s = re.sub(r'\s+', ' ', s)
    return s

def name_similarity(a, b):
    """Return a similarity ratio between two normalized names"""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def find_match(full_name, json_records):
    """Find best match in json_records for a given full_name.

    Strategy:
    1. Exact last name + first token match
    2. Similarity score fallback
    """
    last, first, middle = parse_name(full_name)
    candidates = []

    for rec in json_records:
        j_last, j_first, j_middle = parse_name(rec['full_name'])

        last_match = normalize(last) == normalize(j_last)

        if not last_match:
            continue

        first_match = normalize(first) == normalize(j_first)

        sim = name_similarity(full_name, rec['full_name'])

        candidates.append({
            'rec': rec,
            'first_match': first_match,
            'sim': sim,
            'j_last': j_last,
            'j_first': j_first,
            'j_middle': j_middle
        })

    if not candidates:
        return None

    # Prefer exact first name match
    exact = [c for c in candidates if c['first_match']]
    if exact:
        if len(exact) == 1:
            return exact[0]
        # Multiple exact matches - pick highest similarity
        exact.sort(key=lambda c: c['sim'], reverse=True)
        return exact[0]

    # No exact first match - use best similarity
    candidates.sort(key=lambda c: c['sim'], reverse=True)
    if candidates[0]['sim'] >= 0.6:
        return candidates[0]

    return None

matches = []
unmatched = []
ambiguous = []

for s in existing:
    result = find_match(s['name'], all_students)
    if result is None:
        unmatched.append(s)
        continue

    rec = result['rec']
    first_exact = result['first_match']

    # Store match info with the student
    matches.append({
        'db_student': s,
        'json_rec': rec,
        'first_exact': first_exact,
        'similarity': result['sim']
    })

# Now sort matches alphabetically by lastname
matches.sort(key=lambda m: parse_name(m['db_student']['name'])[0])

print('=' * 100)
header = f'{"#":>3} | {"DB Name":40s} | {"JSON Name":40s} | {"S_ID":>8s} | {"Prog":6s} | {"Year":10s} | {"Phone":15s}'
print(header)
print('=' * 100)

for i, m in enumerate(matches, 1):
    flag = ''
    if not m['first_exact']:
        flag = ' ** FIRST NAME MISMATCH'
    elif m['similarity'] < 0.9:
        flag = ' * PARTIAL'
    db_n = m['db_student']['name'][:38]
    j_n = m['json_rec']['full_name'][:38]
    j_id = m['json_rec']['student_id']
    j_prog = m['json_rec']['program']
    j_year = m['json_rec']['year']
    j_phone = m['json_rec'].get('contact_number', '')
    print(f'{i:>3} | {db_n:40s} | {j_n:40s} | {j_id:>8s} | {j_prog:6s} | {j_year:10s} | {j_phone:15s}{flag}')

print(f'\n--- UNMATCHED ({len(unmatched)}) ---')
for s in unmatched:
    print(f'  {s["student_id"]:>6} | {s["name"]}')

print(f'\nMatches: {len(matches)}, Unmatched: {len(unmatched)}')

# Ask for confirmation before updating
if unmatched:
    print(f'\n⚠ WARNING: {len(unmatched)} students could not be matched!')
else:
    print('\n All 33 students matched!')

confirm = input('\nProceed with MongoDB update? (yes/no): ')
if confirm.lower() != 'yes':
    print('Aborted.')
    sys.exit(0)

updated_count = 0
for m in matches:
    rec = m['json_rec']
    db_student = m['db_student']

    new_student_id = rec['student_id']
    new_course = rec['program']
    new_year = rec['year']

    raw_phone = rec.get('contact_number', '')
    if raw_phone == 'null' or not raw_phone:
        new_phone = ''
    else:
        new_phone = raw_phone

    db.students.update_one(
        {'_id': db_student['_id']},
        {'$set': {
            'student_id': new_student_id,
            'course': new_course,
            'year': new_year,
            'phone': new_phone
        }}
    )
    updated_count += 1
    print(f'  Updated {db_student["name"]:40s} → ID:{new_student_id:>8s} | {new_course:6s} | {new_year:10s} | {new_phone:15s}')

print(f'\nDone! {updated_count} students updated.')

# Re-read and print final sorted list
final = list(db.students.find({}, {
    'name': 1, 'student_id': 1, 'course': 1, 'year': 1, 'phone': 1
}).sort('name', 1))

print('\n=== FINAL STUDENT LIST (sorted by name) ===')
print(f'{"ID":>8} | {"Name":40s} | {"Course":6s} | {"Year":10s} | {"Phone":15s}')
print('-' * 85)
for s in final:
    print(f'{s.get("student_id","?"):>8} | {s.get("name","?"):40s} | {s.get("course",""):6s} | {s.get("year",""):10s} | {s.get("phone",""):15s}')
