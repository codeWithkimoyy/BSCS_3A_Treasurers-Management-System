from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from .audit import log_audit
from .db import db, get_financial_totals, logo_file, next_id
from .decorators import role_required, validate_csrf

bp = Blueprint('admin', __name__)
ROLES = ['admin', 'mayor', 'treasurer', 'staff']
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


@bp.route('/users')
@login_required
@role_required('admin')
def users():
    user_list = list(db.users.find({}, {'_id': 1, 'username': 1, 'role': 1, 'created_at': 1, 'display_name': 1, 'google_email': 1, 'picture': 1}).sort('username', 1))
    officer_count = sum(1 for user in user_list if user.get('role') in ['mayor', 'treasurer'])
    return render_template('users.html', users=user_list, officer_count=officer_count, has_logo=logo_file() is not None)


@bp.route('/admin/logo', methods=['POST'])
@login_required
@role_required('admin')
def upload_logo():
    validate_csrf()
    upload = request.files.get('logo')
    if not upload or not upload.filename:
        flash('Choose a logo image first', 'error')
        return redirect(url_for('admin.users'))
    filename = secure_filename(upload.filename)
    extension = Path(filename).suffix.lower().lstrip('.')
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        flash('Logo must be PNG, JPG, JPEG, or WebP', 'error')
        return redirect(url_for('admin.users'))
    for old_extension in ALLOWED_LOGO_EXTENSIONS:
        old_file = Path(current_app.config['LOGO_UPLOAD_DIR']) / f'app_logo.{old_extension}'
        if old_file.exists():
            old_file.unlink()
    upload.save(Path(current_app.config['LOGO_UPLOAD_DIR']) / f'app_logo.{extension}')
    log_audit('logo_upload')
    flash('Application logo updated', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/app-logo')
def app_logo():
    path = logo_file()
    if not path:
        return '', 404
    response = make_response(send_file(path))
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@bp.route('/users/add', methods=['POST'])
@login_required
@role_required('admin')
def add_user():
    validate_csrf()
    role = request.form.get('role', 'staff').lower()
    if role not in ROLES:
        flash('Invalid officer role', 'error')
        return redirect(url_for('admin.users'))
    try:
        db.users.insert_one({
            '_id': next_id('users'),
            'username': request.form['username'].strip(),
            'password': generate_password_hash(request.form['password']),
            'role': role,
            'created_at': datetime.now(),
        })
        log_audit('user_add', target=request.form['username'])
        flash('User created', 'success')
    except Exception:
        flash('Username already exists', 'error')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:id>/role', methods=['POST'])
@login_required
@role_required('admin')
def assign_user_role(id):
    validate_csrf()
    role = request.form.get('role', '').lower()
    if role not in ROLES:
        flash('Invalid officer role', 'error')
        return redirect(url_for('admin.users'))
    user = db.users.find_one({'_id': id})
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('admin.users'))
    db.users.update_one({'_id': id}, {'$set': {'role': role}})
    log_audit('user_role_change', target=user['username'], detail=role)
    flash(f"{user['username']} is now {role.title()}", 'success')
    return redirect(url_for('admin.users'))


@bp.route('/api/balance')
@login_required
def api_balance():
    income, expense = get_financial_totals()
    return jsonify({'balance': income - expense})
