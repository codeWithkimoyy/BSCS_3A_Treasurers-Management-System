from datetime import datetime, timedelta
from pathlib import Path

from pymongo import MongoClient


class _DB:
    """Stable proxy around the active Mongo database.

    Blueprints import ``db`` at module load time (when it is ``None``); keeping
    a single proxy object means reassigning the underlying database on startup
    is visible to every importer without a singleton accessor.
    """
    _database = None
    _last_error = None

    def __getattr__(self, name):
        if self._database is None:
            raise RuntimeError('Database not initialised')
        return getattr(self._database, name)

    def __setattr__(self, name, value):
        if name in ('_database', '_last_error'):
            object.__setattr__(self, name, value)
        else:
            setattr(self._database, name, value)

    def __bool__(self):
        return self._database is not None

    def __repr__(self):
        return f'<DB proxy connected={self._database is not None}>'


db = _DB()


def init_db_connection(app):
    mongo_uri = app.config.get('MONGO_URI')
    import certifi

    client = None
    try:
        # 1. Primary connection attempt with certifi root CAs
        client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=20000,
            connectTimeoutMS=20000,
            socketTimeoutMS=20000,
            tlsCAFile=certifi.where(),
        )
        client.admin.command('ping')
    except Exception as cert_err:
        # 2. Fallback attempt for environments with custom intermediate certificates
        try:
            client = MongoClient(
                mongo_uri,
                serverSelectionTimeoutMS=20000,
                connectTimeoutMS=20000,
                socketTimeoutMS=20000,
                tls=True,
                tlsAllowInvalidCertificates=True,
            )
            client.admin.command('ping')
        except Exception as retry_err:
            client = None
            db._last_error = f"{type(retry_err).__name__}: {retry_err}"

    if client is not None:
        try:
            target_db = client.get_default_database()
        except Exception:
            target_db = None

        if target_db is None or target_db.name in ('test', 'admin', 'local'):
            target_db = client.get_database('student_treasury')

        db._database = target_db
        db._last_error = None
        return db

    # Safe offline mode if cloud database is unreachable or rejected
    import sys
    sys.stderr.write(f"\n[!] Notice: MongoDB Atlas authentication/connection failed ({db._last_error}).\n")
    sys.stderr.write("[*] Activating safe local offline mode (mongomock) so your app runs without crashing.\n\n")
    import mongomock
    mock_client = mongomock.MongoClient()
    db._database = mock_client.get_database('student_treasury')
    return db


def init_db(app):
    """Create indexes and bootstrap the default admin. Runs on every startup."""
    if not db:
        return

    try:
        db.users.create_index('username', unique=True)
        db.students.create_index('student_id', unique=True)
        # Compound / query indexes used across the app
        db.payments.create_index([('event_id', 1), ('student_id', 1)])
        db.payments.create_index([('confirmed', 1), ('confirmed_at', 1)])
        db.transactions.create_index([('created_at', -1)])
        db.transactions.create_index([('transaction_date', 1)])
        db.events.create_index([('status', 1), ('created_at', -1)])
        db.audit_logs.create_index([('at', -1)])
    except Exception as e:
        import sys
        sys.stderr.write(f"[!] Index creation skipped: {e}\n")

    try:
        if 'counters' not in db.list_collection_names():
            for c in ['users', 'students', 'transactions', 'events', 'payments']:
                db.counters.insert_one({'_id': c, 'seq': 1})

        cfg = app.config
        if db.users.count_documents({}) == 0:
            from werkzeug.security import generate_password_hash
            uname = cfg.get('DEFAULT_ADMIN_USERNAME') or 'admin'
            pwd = cfg.get('DEFAULT_ADMIN_PASSWORD') or 'admin123'
            db.users.insert_one({
                '_id': next_id('users'),
                'username': uname,
                'password': generate_password_hash(pwd),
                'role': 'admin',
                'display_name': 'Kim C. Cutamora',
                'created_at': datetime.now(),
            })
    except Exception as e:
        import sys
        sys.stderr.write(f"[!] User setup skipped: {e}\n")


def next_id(collection_name):
    result = db.counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=True,
    )
    return result['seq']


ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def logo_file():
    for extension in ALLOWED_LOGO_EXTENSIONS:
        uploaded_logo = Path(app_instance_path()) / f'app_logo.{extension}'
        if uploaded_logo.is_file():
            return uploaded_logo
    default_logo = Path(__file__).parent.parent / 'static' / 'web_logo.png'
    return default_logo if default_logo.is_file() else None


def app_instance_path():
    # imported lazily to avoid circular import
    from flask import current_app
    return current_app.config['LOGO_UPLOAD_DIR']


def format_name(raw):
    raw = raw.strip()
    if ',' in raw:
        parts = [p.strip() for p in raw.split(',', 1)]
        last = parts[0].upper()
        first = parts[1].title() if len(parts) > 1 else ''
        return f"{last}, {first}"
    words = raw.split()
    if len(words) < 2:
        return raw.upper()
    last = words[-1].upper()
    first = ' '.join(words[:-1]).title()
    return f"{last}, {first}"


def get_financial_totals():
    """Canonical totals without counting payment ledger rows twice."""
    confirmed_payments = list(db.payments.aggregate([
        {'$match': {'confirmed': True}},
        {'$group': {'_id': None, 'total': {'$sum': '$amount_paid'}}}
    ]))
    manual_income = list(db.transactions.aggregate([
        {'$match': {
            'type': 'income',
            'deleted': {'$ne': True},
            '$or': [
                {'description': {'$exists': False}},
                {'description': {'$not': {'$regex': '^Payment:'}}}
            ]
        }},
        {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
    ]))
    expenses = list(db.transactions.aggregate([
        {'$match': {'type': 'expense', 'deleted': {'$ne': True}}},
        {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
    ]))
    income = (confirmed_payments[0]['total'] if confirmed_payments else 0) + \
        (manual_income[0]['total'] if manual_income else 0)
    expense = expenses[0]['total'] if expenses else 0
    return income, expense


def get_confirmed_payment_rows(start=None, end=None):
    """Return confirmed payments in the same shape used by ledger reports."""
    match = {'confirmed': True}
    if start:
        match['confirmed_at'] = {'$gte': datetime.fromisoformat(start)}
    if end:
        match.setdefault('confirmed_at', {})['$lt'] = datetime.fromisoformat(end) + timedelta(days=1)
    return list(db.payments.aggregate([
        {'$match': match},
        {'$lookup': {'from': 'students', 'localField': 'student_id', 'foreignField': '_id', 'as': 'student'}},
        {'$lookup': {'from': 'events', 'localField': 'event_id', 'foreignField': '_id', 'as': 'event'}},
        {'$unwind': {'path': '$student', 'preserveNullAndEmptyArrays': True}},
        {'$unwind': {'path': '$event', 'preserveNullAndEmptyArrays': True}},
        {'$project': {
            '_id': 1, 'student_id': 1, 'amount': '$amount_paid', 'notes': 1, 'confirmed_at': 1,
            'transaction_date': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$confirmed_at'}},
            'type': {'$literal': 'income'},
            'description': {'$concat': ['Payment: ', '$event.title']},
            'student': '$student.name', 'student_name': '$student.name', 'event_title': '$event.title',
            'payment_method': {'$literal': 'event payment'}
        }}
    ]))


def get_class_officers():
    """Dynamically return the assigned officers based on system user roles."""
    if not db:
        return {
            'treasurer': {'name': 'CLASS TREASURER', 'title': 'Class Treasurer'},
            'mayor': {'name': 'CLASS MAYOR', 'title': 'Class Mayor'},
            'auditor': {'name': 'CLASS AUDITOR', 'title': 'Class Auditor'}
        }

    treasurer_user = db.users.find_one({'role': 'treasurer'})
    mayor_user = db.users.find_one({'role': 'mayor'})
    admin_user = db.users.find_one({'role': 'admin', 'display_name': {'$exists': True, '$ne': None}}) or db.users.find_one({'role': 'admin'})

    t_name = (treasurer_user.get('display_name') or treasurer_user.get('username') or 'Class Treasurer') if treasurer_user else 'Class Treasurer'
    m_name = (mayor_user.get('display_name') or mayor_user.get('username') or 'Class Mayor') if mayor_user else 'Class Mayor'
    a_name = (admin_user.get('display_name') or admin_user.get('username') or 'Class Auditor') if admin_user else 'Class Auditor'

    return {
        'treasurer': {
            'name': t_name.upper(),
            'title': 'Class Treasurer'
        },
        'mayor': {
            'name': m_name.upper(),
            'title': 'Class Mayor'
        },
        'auditor': {
            'name': a_name.upper(),
            'title': 'Class Auditor / Administrator'
        }
    }
