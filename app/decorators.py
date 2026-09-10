import hmac
import secrets
import time
from functools import wraps

from flask import abort, current_app, flash, jsonify, redirect, request, session, url_for
from flask_login import current_user


def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def validate_csrf():
    token = session.get('_csrf_token')
    submitted = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or not submitted or not hmac.compare_digest(token, submitted):
        abort(403)


# ── In-memory rate limiting (single-process).
# TODO: swap for Flask-Limiter backed by Redis when scaling past one worker. ──
_login_attempts = {}
_action_attempts = {}


def rate_limit(key_prefix, max_attempts, window):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if current_app.config.get('TESTING'):
                return f(*args, **kwargs)
            now = time.time()
            ip = request.remote_addr or 'unknown'
            rl_key = f"{key_prefix}:{ip}"
            store = _login_attempts if key_prefix == 'login' else _action_attempts
            store.setdefault(rl_key, [])
            store[rl_key] = [t for t in store[rl_key] if now - t < window]
            if len(store[rl_key]) >= max_attempts:
                resp = jsonify({'error': 'Too many requests. Try again later.'})
                resp.status_code = 429
                resp.headers['Retry-After'] = str(window)
                return resp
            store[rl_key].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def role_required(*roles):
    """Block non-members with a friendly flash + redirect (preserves UX)."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                flash('Access denied', 'error')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def get_float(form, key, default=None):
    """Parse a form field as float or abort with 400 (no raw 500s)."""
    raw = form.get(key, '')
    if raw is None or raw == '':
        if default is not None:
            return default
        abort(400, description=f'Missing field: {key}')
    try:
        return float(raw)
    except (TypeError, ValueError):
        abort(400, description=f'Invalid number for {key}')


def require_fields(form, *keys):
    for key in keys:
        if not form.get(key, '').strip():
            abort(400, description=f'Missing field: {key}')


def current_user_id():
    return current_user.id


def current_username():
    return current_user.username
