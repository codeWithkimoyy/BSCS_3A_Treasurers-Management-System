import json, os, re, sys
from pathlib import Path
from difflib import SequenceMatcher
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
client = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=10000, tls=True, tlsInsecure=True)
db = client.get_database()

with open(r'E:\Scanned\students_all.json', encoding='utf-8-sig') as f:
    all_students = json.load(f)

print(f'Loaded {len(all_students)} records from JSON')

existing = list(db.students.find({}, {'_id': 1, 'name': 1, 'student_id': 1}).sort('name', 1))
print(f'Found {len(existing)} students in DB\n')

# Overrides: key = exact DB name, value = criteria to search in JSON (LAST_NAME, FIRST_NAME)
# If the DB name and JSON name differ, use this mapping
NAME_OVERRIDES = {
    'COUNARES, Junmar Q':       ('COLINARES',   'JUNMAR'),
    'EBARILE, Joyce Elizabeth N': ('EBARLE',     'JOYCE'),
    'BUSLON, Wy May A':          ('BUSLON',      'IVY'),
    'DAIGAN, Honaster L':        ('DAIGAN',      'JHON ASTER'),
    'JAPITANA, Hecel P':         ('JAPITANA',    'HECEI'),
}

def parse_name(n):
    n = n.strip().upper()
    if ',' in n:
        last = n.split(',', 1)[0].strip()
        rest = n.split(',', 1)[1].strip()
        tokens = rest.split()
        first = tokens[0] if tokens else ''
        return last, first
    tokens = n.split()
    return tokens[-1] if tokens else '', tokens[0] if tokens else ''

def normalize(s):
    s = s.strip().upper()
    s = s.replace('\u00d1', 'N').replace('\u00f1', 'N')
    s = re.sub(r'\s+', ' ', s)
    return s

def find_json_match(db_name):
    """Find JSON record by (last, first) exact match, then fuzzy fallback."""
    # Check override first
    if db_name in NAME_OVERRIDES:
        search_last, search_first = NAME_OVERRIDES[db_name]
        search_prefix = normalize(f'{search_last}, {search_first}')
        for rec in all_students:
            jn = normalize(rec['full_name'])
            if jn.startswith(search_prefix):
                return rec, f'Override: {db_name} -> {rec["full_name"]}'
        return None, f'FAILED override: {db_name} -> ({search_last}, {search_first})'

    # Exact match on last + first token
    last, first = parse_name(db_name)
    for rec in all_students:
        j_last, j_first = parse_name(rec['full_name'])
        if normalize(j_last) == normalize(last) and normalize(j_first) == normalize(first):
            return rec, None

    # Fuzzy fallback: same last name, best similarity
    best_rec, best_sim = None, 0
    for rec in all_students:
        j_last, _ = parse_name(rec['full_name'])
        if normalize(j_last) == normalize(last):
            sim = SequenceMatcher(None, normalize(db_name), normalize(rec['full_name'])).ratio()
            if sim > best_sim:
                best_sim = sim
                best_rec = rec
    if best_rec and best_sim >= 0.6:
        return best_rec, f'Fuzzy: {db_name} -> {best_rec["full_name"]} (sim={best_sim:.2f})'
    return None, f'No match: {db_name}'

matches = []
unmatched = []
warnings = []

for s in existing:
    rec, note = find_json_match(s['name'])
    if rec:
        matches.append((s, rec))
        if note:
            warnings.append(note)
    else:
        unmatched.append(s)
        if note:
            warnings.append(note)

# Sort matches alphabetically by lastname
matches.sort(key=lambda m: parse_name(m[0]['name'])[0])

print(f'{"#":>3} | {"DB Name":40s} | {"JSON Name":40s} | {"S_ID":>8s} | {"Course":6s} | {"Year":10s} | {"Phone":15s}')
print('=' * 110)
for i, (s, rec) in enumerate(matches, 1):
    dn = s['name']
    rn = rec['full_name']
    sid = rec['student_id']
    prog = rec['program']
    yr = rec['year']
    ph = rec.get('contact_number', '')
    print(f'{i:>3} | {dn:40s} | {rn:40s} | {sid:>8s} | {prog:6s} | {yr:10s} | {ph:15s}')

print(f'\n--- MATCHED: {len(matches)} / {len(existing)} ---')
print(f'--- UNMATCHED: {len(unmatched)} ---')
for s in unmatched:
    print(f'  {s["student_id"]} | {s["name"]}')

if warnings:
    print(f'\n--- WARNINGS ({len(warnings)}) ---')
    for w in warnings:
        print(f'  {w}')

confirm = input('\nProceed with MongoDB update? (yes/no): ')
if confirm.lower() != 'yes':
    print('Aborted.')
    sys.exit(0)

updated = 0
for s, rec in matches:
    raw_phone = rec.get('contact_number', '')
    phone = '' if raw_phone == 'null' or not raw_phone else raw_phone
    db.students.update_one(
        {'_id': s['_id']},
        {'$set': {
            'student_id': rec['student_id'],
            'course': rec['program'],
            'year': rec['year'],
            'phone': phone
        }}
    )
    updated += 1
    print(f'  OK {s["name"]:40s} -> ID={rec["student_id"]}, {rec["program"]}, {rec["year"]}')

print(f'\nDone! {updated} updated.')
if unmatched:
    print(f'\n=== UNMATCHED (need manual entry) ===')
    for s in unmatched:
        print(f'  {s["name"]} (current ID: {s["student_id"]})')
