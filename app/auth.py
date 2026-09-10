import secrets
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .audit import log_audit
from .db import db, next_id
from .decorators import generate_csrf_token, rate_limit, validate_csrf
from .models import User

bp = Blueprint('auth', __name__)


def load_user(user_id):
    user = db.users.find_one({'_id': int(user_id)})
    if user:
        return User(user['_id'], user['username'], user['role'], user.get('display_name'),
                   user.get('google_email'), user.get('picture'))
    return None


@bp.route('/login', methods=['GET', 'POST'])
@rate_limit('login', 5, 300)
def login():
    if request.method == 'POST':
        validate_csrf()
        user = db.users.find_one({'username': request.form['username']})
        if user and check_password_hash(user['password'], request.form['password']):
            login_user(User(user['_id'], user['username'], user['role'],
                           user.get('display_name'), user.get('google_email'), user.get('picture')))
            session.pop('_csrf_token', None)
            log_audit('login', target=user['username'])
            return redirect(url_for('dashboard.index'))
        flash('Invalid username or password', 'error')
    return render_template('login.html', csrf_token=generate_csrf_token())


@bp.route('/login/google', methods=['POST'])
def google_login():
    validate_csrf()
    if not current_app.config['GOOGLE_CLIENT_ID']:
        return jsonify({'error': 'Google not configured'}), 400
    try:
        from google.auth.transport import requests as google_req
        from google.oauth2 import id_token as google_id_token
        data = request.get_json()
        token = data.get('credential')
        if not token:
            return jsonify({'error': 'No token'}), 400
        info = google_id_token.verify_oauth2_token(token, google_req.Request(), current_app.config['GOOGLE_CLIENT_ID'])
        email = info.get('email', '')
        if not email:
            return jsonify({'error': 'No email from Google'}), 400
        if not email.endswith('@bisu.edu.ph'):
            return jsonify({'error': 'Only @bisu.edu.ph emails allowed'}), 403
        user = db.users.find_one({'username': email}) or db.users.find_one({'google_email': email})
        if not user:
            base_username = email.split('@')[0]
            username = base_username
            i = 1
            while db.users.find_one({'username': username}):
                username = f"{base_username}{i}"
                i += 1
            user_id = next_id('users')
            db.users.insert_one({
                '_id': user_id,
                'username': username,
                'password': generate_password_hash(secrets.token_hex(32)),
                'google_email': email,
                'display_name': info.get('name') or email.split('@')[0],
                'picture': info.get('picture', ''),
                'role': 'staff',
                'created_at': datetime.now(),
            })
            user = db.users.find_one({'_id': user_id})
            log_audit('user_created_oauth', target=username)
        else:
            db.users.update_one({'_id': user['_id']}, {'$set': {
                'google_email': email,
                'display_name': info.get('name') or user.get('display_name') or user['username'],
                'picture': info.get('picture', user.get('picture', '')),
            }})
            user = db.users.find_one({'_id': user['_id']})
        login_user(User(user['_id'], user['username'], user['role'],
                       user.get('display_name'), user.get('google_email'), user.get('picture')))
        log_audit('login_google', target=user['username'])
        return jsonify({'ok': True, 'redirect': url_for('dashboard.index')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


def google_client_id():
    from flask import current_app
    return current_app.config['GOOGLE_CLIENT_ID']


def current_app_google_config():
    from flask import current_app
    return current_app.config['GOOGLE_CLIENT_ID']


@bp.route('/logout')
@login_required
def logout():
    log_audit('logout', target=current_user.username)
    logout_user()
    return redirect(url_for('auth.login'))
