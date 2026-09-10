import os
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    current_app,
    g,
    jsonify,
    render_template,
    request,
)
from flask_login import LoginManager, current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .db import init_db, init_db_connection
from .decorators import generate_csrf_token

ENV_PATH = Path(__file__).parent.parent / '.env'
load_dotenv(ENV_PATH)

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'error'


def create_app(config=None):
    root = Path(__file__).parent.parent
    app = Flask(__name__,
                template_folder=str(root / 'templates'),
                static_folder=str(root / 'static'))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or os.urandom(24).hex(),
        MONGO_URI=os.environ.get('MONGO_URI', 'mongodb://localhost:27017/student_treasury'),
        GOOGLE_CLIENT_ID=os.environ.get('GOOGLE_CLIENT_ID', ''),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        LOGO_UPLOAD_DIR=os.environ.get('LOGO_UPLOAD_DIR', app.instance_path),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,  # 12h for a financial app
    )

    if config:
        app.config.update(config)
    if os.environ.get('SESSION_COOKIE_DOMAIN'):
        app.config['SESSION_COOKIE_DOMAIN'] = os.environ.get('SESSION_COOKIE_DOMAIN')

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config['LOGO_UPLOAD_DIR'], exist_ok=True)

    # App-level configuration sourced from env
    app.config['AUTO_ACTIVATE_ACCOUNT'] = os.environ.get('AUTO_ACTIVATE_ACCOUNT', 'false').lower() == 'true'
    app.config['DEFAULT_ADMIN_USERNAME'] = os.environ.get('DEFAULT_ADMIN_USERNAME', '')
    app.config['DEFAULT_ADMIN_PASSWORD'] = os.environ.get('DEFAULT_ADMIN_PASSWORD', '')

    login_manager.init_app(app)
    from .auth import load_user
    login_manager.user_loader(load_user)

    # Connect to Mongo and ensure indexes/admin on every startup (gunicorn safe)
    try:
        init_db_connection(app)
        init_db(app)
    except Exception as db_err:
        import sys
        sys.stderr.write(f"\n[!] Warning: Database init error ({db_err}). Continuing in resilient mode...\n\n")

    _register_context_processors(app)
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_general_rate_limit(app)

    # Blueprints
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .dashboard import bp as dashboard_bp
    from .events import bp as events_bp
    from .payments import bp as payments_bp
    from .reports import bp as reports_bp
    from .students import bp as students_bp
    from .transactions import bp as transactions_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)

    return app


def _register_context_processors(app):
    @app.context_processor
    def inject_globals():
        g.csp_nonce = os.urandom(16).hex()
        from .db import get_class_officers
        return {
            'csp_nonce': g.csp_nonce,
            'now': __import__('datetime').datetime.now(),
            'current_year': __import__('datetime').datetime.now().year,
            'can_override': lambda: current_user.is_authenticated and current_user.role in ['admin', 'mayor', 'treasurer'],
            'can_manage_data': lambda: current_user.is_authenticated and current_user.role in ['admin', 'mayor', 'treasurer'],
            'google_cid': app.config['GOOGLE_CLIENT_ID'],
            'has_logo': _logo_exists(app),
            'csrf_token': generate_csrf_token(),
            'officers': get_class_officers(),
        }

    @app.context_processor
    def inject_user():
        return {'current_user': current_user}


def _logo_exists(app):
    from .db import logo_file
    return logo_file() is not None


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors.html', code=404, message='Page not found'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors.html', code=403, message='Access denied'), 403

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template('errors.html', code=405, message='Method not allowed'), 405

    @app.errorhandler(429)
    def too_many(e):
        return render_template('errors.html', code=429, message='Too many requests'), 429

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception('Unhandled exception')
        return render_template('errors.html', code=500, message='Internal server error'), 500


def _register_general_rate_limit(app):
    from .decorators import _action_attempts

    @app.before_request
    def general_rate_limit():
        if current_app.config.get('TESTING'):
            return None
        if request.method == 'POST' and request.endpoint != 'static':
            now = time.time()
            ip = request.remote_addr or 'unknown'
            key = f"general:{ip}"
            _action_attempts.setdefault(key, [])
            _action_attempts[key] = [t for t in _action_attempts[key] if now - t < 300]
            if len(_action_attempts[key]) >= 60:
                resp = jsonify({'error': 'Too many requests. Try again later.', 'retry_after': 300})
                resp.status_code = 429
                resp.headers['Retry-After'] = '300'
                return resp
            _action_attempts[key].append(now)


def _register_security_headers(app):
    @app.after_request
    def inject_security_headers(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        resp.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        resp.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        resp.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        resp.headers['Server'] = ''
        nonce = getattr(g, 'csp_nonce', '')
        nonce_str = f"'nonce-{nonce}' " if nonce else ''
        csp = (
            f"default-src 'self'; "
            f"script-src 'self' https://accounts.google.com https://cdn.jsdelivr.net https://code.jquery.com https://cdn.datatables.net 'unsafe-inline' blob: {nonce_str}; "
            f"style-src 'self' https://accounts.google.com https://cdn.jsdelivr.net https://fonts.googleapis.com https://cdn.datatables.net 'unsafe-inline' {nonce_str}; "
            f"style-src-elem 'self' https://accounts.google.com https://cdn.jsdelivr.net https://fonts.googleapis.com https://cdn.datatables.net 'unsafe-inline' {nonce_str}; "
            f"style-src-attr 'unsafe-inline'; "
            f"font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            f"img-src 'self' data: https: blob:; "
            f"connect-src 'self' https://accounts.google.com https://cdn.jsdelivr.net blob: data:; "
            f"worker-src 'self' blob:; "
            f"frame-src https://accounts.google.com; "
            f"form-action 'self'; "
            f"base-uri 'self'; "
            f"object-src 'none'; "
            f"frame-ancestors 'none'; "
        )
        resp.headers['Content-Security-Policy'] = csp
        return resp


_app_instance = None


def __getattr__(name):
    """Enable WSGI entry points like 'gunicorn app:app' to load cleanly."""
    if name == 'app':
        global _app_instance
        if _app_instance is None:
            _app_instance = create_app()
        return _app_instance
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
